import os
import time
from typing import List, Optional
import numpy as np
from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink
from PyQt6.QtWidgets import (

    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from engine.preview_engine import PreviewEngine
from models.clip import Clip
from models.project import Project
from .media_pool_view import MediaPoolView
from .player_view import PlayerView
from .timeline_view import ClipWidget, TimelineView


class WorkerSignals(QObject):
    """Signals for background thumbnail generation worker."""
    thumbnails_ready = pyqtSignal(object, list, object)  # (clip_widget, list[np.ndarray], worker)


class ThumbnailWorker(QRunnable):
    """Background worker that extracts filmstrip thumbnails without blocking the UI thread."""

    def __init__(
        self,
        engine: PreviewEngine,
        clip_widget: ClipWidget,
        file_path: str,
        source_start: float,
        duration: float,
        count: int = 8,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.engine = engine
        self.clip_widget = clip_widget
        self.file_path = file_path
        self.source_start = source_start
        self.duration = duration
        self.count = count
        self.signals = WorkerSignals()
        self.is_cancelled = False

    def cancel(self) -> None:
        self.is_cancelled = True

    @pyqtSlot()
    def run(self):
        if self.is_cancelled:
            return
        try:
            from PyQt6 import sip
            if self.clip_widget is None or sip.isdeleted(self.clip_widget):
                return
        except Exception:
            return

        try:
            thumbs = self.engine.extract_clip_thumbnails(
                file_path=self.file_path,
                source_start=self.source_start,
                duration=self.duration,
                count=self.count,
                thumb_height=36,
            )
            if not self.is_cancelled:
                try:
                    from PyQt6 import sip
                    if self.clip_widget is not None and not sip.isdeleted(self.clip_widget):
                        self.signals.thumbnails_ready.emit(self.clip_widget, thumbs, self)
                except Exception:
                    pass
        except Exception:
            pass


class MainWindow(QMainWindow):
    """The master layout, playback coordinator, audio coordinator, and event coordinator of the application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Movie Editor - Studio")
        self.resize(1360, 780)
        self.setStyleSheet("background-color: #121214; color: #f4f4f5;")

        # Thread pool and active worker tracking
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers: set = set()

        # 1. Instantiate Engine and Project Data Model
        self.preview_engine = PreviewEngine(cache_size=160)
        self.fps: float = 30.0
        self.sample_rate: int = 44100
        self.project = Project(name="AI Studio Project", resolution=(1920, 1080), fps=self.fps)

        # Standard Tracks (Video 1, Video 2, Audio 1)
        self.track_v1 = self.project.add_track("Video 1", track_type="video")
        self.track_v2 = self.project.add_track("Video 2", track_type="video")
        self.track_a1 = self.project.add_track("Audio 1", track_type="audio")

        # High-Precision Playback Timing State
        self.current_playback_time: float = 0.0
        self._is_playing: bool = False
        self._playback_start_wall_time: float = 0.0
        self._playback_start_timeline_time: float = 0.0
        self._last_rendered_quant_time: int = -1
        self.selected_clip_widget: Optional[ClipWidget] = None

        # 2. Audio Playback Subsystem
        self.audio_format = QAudioFormat()
        self.audio_format.setSampleRate(self.sample_rate)
        self.audio_format.setChannelCount(2)
        self.audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.audio_sink = QAudioSink(self.audio_format, self)
        self.audio_buffer: Optional[QBuffer] = None
        self.volume: float = 1.0
        self.is_muted: bool = False
        self.audio_sink.setVolume(1.0)

        # 3. Multi-Pane Splitter Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Main horizontal splitter (Media Pool on Left, Player & Timeline on Right)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #27272a; }")

        # Left pane: Media Pool
        self.media_pool_view = MediaPoolView()
        main_splitter.addWidget(self.media_pool_view)

        # Right pane: Vertical splitter (Player on Top, Timeline on Bottom)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setStyleSheet("QSplitter::handle { background-color: #27272a; }")

        self.player_view = PlayerView()
        self.timeline_view = TimelineView()
        right_splitter.addWidget(self.player_view)
        right_splitter.addWidget(self.timeline_view)
        right_splitter.setSizes([450, 270])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([270, 1070])

        main_layout.addWidget(main_splitter)

        # 4. High-Frequency (60 FPS) Animation Timer for Silky-Smooth Playhead and Playback
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(16)  # ~60 FPS
        self.playback_timer.timeout.connect(self._on_playback_tick)

        # 5. Connect PlayerView Controls & Audio Signals
        self.player_view.toggle_play_requested.connect(self.toggle_play)
        self.player_view.play_requested.connect(self.play)
        self.player_view.pause_requested.connect(self.pause)
        self.player_view.rewind_requested.connect(self.rewind)
        self.player_view.step_forward_requested.connect(lambda: self.step_frame(1))
        self.player_view.step_backward_requested.connect(lambda: self.step_frame(-1))
        self.player_view.volume_changed.connect(self._on_volume_changed)
        self.player_view.mute_toggled.connect(self._on_mute_toggled)

        # 6. Connect MediaPool Signals
        self.media_pool_view.media_imported.connect(self._on_media_imported)

        # 7. Connect Timeline Signals
        self.timeline_view.scrub_started.connect(self.pause)
        self.timeline_view.seek_requested.connect(self._on_timeline_seek)
        self.timeline_view.clip_dropped.connect(self._on_clip_dropped)
        self.timeline_view.clip_selected.connect(self._on_clip_selected)
        self.timeline_view.clip_delete_requested.connect(self._on_clip_delete_requested)

        # Locate sample video candidates and preload if available
        video_candidates = [
            r"C:\Users\rastisx\Desktop\Crystal Castles - Celestica.mp4",
            r"C:\Users\rastisx\Desktop\0609 (1).mp4",
            r"C:\Users\rastisx\Videos\2026-01-27 08-41-55.mp4",
            os.path.abspath("Getting hit by a lance..mp4"),
        ]
        sample_path = next((p for p in video_candidates if os.path.exists(p)), None)

        if sample_path:
            self.media_pool_view.add_media_item(sample_path)
            sample_dur = self.preview_engine.get_media_duration(sample_path)
            initial_clip = Clip(
                file_path=sample_path,
                name=os.path.basename(sample_path),
                source_start=0.0,
                source_end=sample_dur,
                timeline_position=0.0,
            )
            self.track_v1.clips.append(initial_clip)
            clip_w = self.timeline_view.add_clip(
                track_index=0,
                file_path=sample_path,
                timeline_position=0.0,
                duration=sample_dur,
            )
            if clip_w:
                self._load_thumbnails_async(clip_w, sample_path, 0.0, sample_dur)

        # Sync max timeline boundary with loaded clips
        self.timeline_view.set_max_duration(self.get_max_timeline_duration())

        # Render initial frame at 0.0s
        self._render_current_frame(force=True)

    def get_max_timeline_duration(self) -> float:
        """Calculates the maximum end timestamp across all clips on the timeline."""
        return self.project.get_total_duration()

    def _load_thumbnails_async(
        self,
        clip_widget: ClipWidget,
        file_path: str,
        source_start: float,
        duration: float,
    ) -> None:
        """Launches a background worker to extract thumbnail frames for the clip's filmstrip."""
        worker = ThumbnailWorker(
            engine=self.preview_engine,
            clip_widget=clip_widget,
            file_path=file_path,
            source_start=source_start,
            duration=duration,
            count=10,
        )
        self._active_workers.add(worker)
        worker.signals.thumbnails_ready.connect(self._on_thumbnails_ready)
        self.thread_pool.start(worker)

    @pyqtSlot(object, list, object)
    def _on_thumbnails_ready(
        self,
        clip_widget: ClipWidget,
        thumbnails: List[np.ndarray],
        worker: object,
    ) -> None:
        """Applies loaded thumbnail frames to the clip widget on the UI thread."""
        self._active_workers.discard(worker)
        try:
            from PyQt6 import sip
            if clip_widget is not None and not sip.isdeleted(clip_widget):
                clip_widget.set_thumbnails(thumbnails)
        except (RuntimeError, ReferenceError, Exception):
            pass

    @pyqtSlot(object)
    def _on_clip_selected(self, clip_widget: ClipWidget) -> None:
        """Stores the currently selected ClipWidget."""
        self.selected_clip_widget = clip_widget

    @pyqtSlot(object)
    def _on_clip_delete_requested(self, clip_widget: ClipWidget) -> None:
        """Deletes the specified clip widget and its model representation."""
        self.selected_clip_widget = clip_widget
        self.delete_selected_clip()

    def delete_selected_clip(self) -> None:
        """Deletes the currently selected clip from the project model and timeline canvas."""
        if not self.selected_clip_widget:
            return

        cw = self.selected_clip_widget

        # Cancel any active background thumbnail workers for this clip widget
        for worker in list(self._active_workers):
            if getattr(worker, "clip_widget", None) is cw:
                if hasattr(worker, "cancel"):
                    worker.cancel()

        track_index = getattr(cw, "track_index", -1)

        if 0 <= track_index < len(self.project.tracks):
            track = self.project.tracks[track_index]
            # Match by path and timeline position
            matching = [
                c for c in track.clips
                if c.file_path == cw.file_path and abs(c.timeline_position - cw.timeline_position) < 0.01
            ]
            for m in matching:
                track.clips.remove(m)

        # Remove from UI canvas
        self.timeline_view.remove_clip_widget(cw)
        self.selected_clip_widget = None

        # Update max duration boundary
        max_dur = self.get_max_timeline_duration()
        self.timeline_view.set_max_duration(max_dur)
        if self.current_playback_time > max_dur:
            self.current_playback_time = max_dur

        # Re-cue audio if active
        if self._is_playing:
            self._start_audio()

        # Update preview frame immediately
        self._render_current_frame(force=True)

    @pyqtSlot(str, int, float)
    def _on_clip_dropped(self, file_path: str, track_index: int, timeline_pos: float) -> None:
        """Invoked when a media file is dragged and dropped onto a timeline track."""
        if not file_path or not os.path.exists(file_path):
            return

        if not (0 <= track_index < len(self.project.tracks)):
            return

        # Ensure the media item is also registered in the Media Pool
        self.media_pool_view.add_media_item(file_path)

        real_duration = self.preview_engine.get_media_duration(file_path)
        if real_duration <= 0.0:
            real_duration = 5.0

        new_clip = Clip(
            file_path=file_path,
            name=os.path.basename(file_path),
            source_start=0.0,
            source_end=real_duration,
            timeline_position=timeline_pos,
        )
        self.project.tracks[track_index].clips.append(new_clip)

        # Place visual ClipWidget
        clip_w = self.timeline_view.add_clip(
            track_index=track_index,
            file_path=file_path,
            timeline_position=timeline_pos,
            duration=real_duration,
        )

        # Asynchronously extract filmstrip thumbnail frames
        if clip_w:
            self._load_thumbnails_async(clip_w, file_path, 0.0, real_duration)

        # Update max boundary for playhead
        self.timeline_view.set_max_duration(self.get_max_timeline_duration())

        # Stop and re-cue audio if playing
        was_playing = self._is_playing
        self.current_playback_time = timeline_pos
        self._render_current_frame(force=True)

        if was_playing:
            self.play()

    @pyqtSlot(float)
    def _on_timeline_seek(self, time_sec: float) -> None:
        """Invoked when user clicks/scrubs on the timeline."""
        was_playing = self._is_playing
        self._stop_audio()
        max_dur = self.get_max_timeline_duration()
        if max_dur > 0:
            self.current_playback_time = max(0.0, min(time_sec, max_dur))
        else:
            self.current_playback_time = 0.0
        self._render_current_frame(force=True)

        if was_playing:
            self.play()

    @pyqtSlot(str)
    def _on_media_imported(self, file_path: str) -> None:
        """Preloads media metadata in the engine without blocking the UI."""
        self.preview_engine.get_media_info(file_path)

    @pyqtSlot(float)
    def _on_volume_changed(self, vol: float) -> None:
        """Updates audio sink volume."""
        self.volume = vol
        if not self.is_muted:
            self.audio_sink.setVolume(vol)

    @pyqtSlot(bool)
    def _on_mute_toggled(self, is_muted: bool) -> None:
        """Mutes/unmutes audio sink."""
        self.is_muted = is_muted
        self.audio_sink.setVolume(0.0 if is_muted else self.volume)

    def _start_audio(self) -> None:
        """Starts streaming mixed multi-track audio from current playback position."""
        self._stop_audio()
        max_duration = self.get_max_timeline_duration()
        remaining_duration = max(0.05, max_duration - self.current_playback_time)

        pcm_bytes = self.preview_engine.get_project_audio_pcm(
            self.project,
            start_time=self.current_playback_time,
            duration=remaining_duration,
            sample_rate=self.sample_rate,
        )

        if pcm_bytes:
            qba = QByteArray(pcm_bytes)
            self.audio_buffer = QBuffer(self)
            self.audio_buffer.setData(qba)
            self.audio_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self.audio_sink.start(self.audio_buffer)

    def _stop_audio(self) -> None:
        """Stops and cleans up audio playback sink and buffer cleanly."""
        if self.audio_sink:
            self.audio_sink.reset()
        if self.audio_buffer:
            self.audio_buffer.close()
            self.audio_buffer = None

    @pyqtSlot()
    def toggle_play(self) -> None:
        """Toggles between play and pause."""
        if self._is_playing:
            self.pause()
        else:
            self.play()

    @pyqtSlot()
    def play(self) -> None:
        """Starts high-precision playback clock and synchronized audio."""
        max_duration = self.get_max_timeline_duration()
        if max_duration <= 0.0:
            return

        if self.current_playback_time >= max_duration:
            self.current_playback_time = 0.0

        self._is_playing = True
        self._playback_start_wall_time = time.perf_counter()
        self._playback_start_timeline_time = self.current_playback_time
        self.player_view.set_playing_state(True)

        # Start audio playback stream
        self._start_audio()

        if not self.playback_timer.isActive():
            self.playback_timer.start()

    @pyqtSlot()
    def pause(self) -> None:
        """Pauses playback and audio."""
        self._is_playing = False
        if self.playback_timer.isActive():
            self.playback_timer.stop()
        self._stop_audio()
        self.player_view.set_playing_state(False)

    @pyqtSlot()
    def rewind(self) -> None:
        """Rewinds playback to 0.0s."""
        self.pause()
        self.current_playback_time = 0.0
        self._render_current_frame(force=True)

    def step_frame(self, frame_delta: int) -> None:
        """Steps forward or backward by the specified number of frames."""
        self.pause()
        frame_time = 1.0 / max(1.0, self.fps)
        new_time = max(0.0, self.current_playback_time + (frame_delta * frame_time))
        max_dur = self.get_max_timeline_duration()
        if max_dur > 0:
            new_time = min(new_time, max_dur)
        self.current_playback_time = new_time
        self._render_current_frame(force=True)

    @pyqtSlot()
    def _on_playback_tick(self) -> None:
        """Fired ~60 times per second for smooth playhead motion and wall-clock sync."""
        if not self._is_playing:
            return

        elapsed_wall = time.perf_counter() - self._playback_start_wall_time
        self.current_playback_time = self._playback_start_timeline_time + elapsed_wall

        max_duration = self.get_max_timeline_duration()
        if max_duration > 0.0 and self.current_playback_time >= max_duration:
            self.current_playback_time = max_duration
            self._render_current_frame(force=True)
            self.pause()
            return

        self._render_current_frame()

    def _render_current_frame(self, force: bool = False) -> None:
        """
        Extracts composite frame and updates PlayerView and Timeline playhead.
        Quantizes render calls to avoid redundant frame redraws while maintaining 60 FPS playhead.
        """
        # Smoothly advance the visual playhead at 60 FPS
        self.timeline_view.set_playhead_time(self.current_playback_time)

        # Check if frame index changed (at project FPS)
        quant_time = int(round(self.current_playback_time * self.fps))
        if force or quant_time != self._last_rendered_quant_time:
            self._last_rendered_quant_time = quant_time

            # Update Frame / Timecode / Status Header
            status = self.preview_engine.get_playback_status(self.project, self.current_playback_time)
            self.player_view.update_status(status)

            # Update Video Frame Preview (Top-down layered)
            frame = self.preview_engine.get_project_frame(self.project, self.current_playback_time)
            self.player_view.update_frame(frame)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Global keyboard shortcuts for video playback and clip deletion."""
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
            event.accept()
        elif key == Qt.Key.Key_Left:
            self.step_frame(-1)
            event.accept()
        elif key == Qt.Key.Key_Right:
            self.step_frame(1)
            event.accept()
        elif key == Qt.Key.Key_Home:
            self.rewind()
            event.accept()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_clip()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Clean up background threads, audio sink, timers, and engine resources."""
        self.playback_timer.stop()
        self._stop_audio()
        for worker in list(self._active_workers):
            if hasattr(worker, "cancel"):
                worker.cancel()
        self._active_workers.clear()
        self.thread_pool.waitForDone(500)
        self.preview_engine.close()
        super().closeEvent(event)