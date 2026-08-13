"""Main window and application coordinator conforming to Phase 2 guidelines.

Features:
- CapCut-inspired sleek dark styling with glowing cyan/blue accents and header bar.
- Dedicated Export action button and modal dialog for MP4/WebM rendering.
- Scissors/Razor tool splitting (click split and split-at-playhead Ctrl+B).
- Interactive edge trimming with instant live updates and data model sync.
- Multi-track timeline synchronization and 60 FPS playhead preview.
"""

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
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtMultimedia import QAudioFormat, QAudioSink
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from engine.preview_engine import PreviewEngine
from models.clip import Clip, detect_media_type
from models.project import Project
from .export_dialog import ExportDialog
from .media_pool_view import MediaPoolView
from .player_view import PlayerView
from .timeline_view import ClipWidget, TimelineView


class WorkerSignals(QObject):
    """Signals for background thumbnail generation worker."""
    thumbnails_ready = pyqtSignal(object, list, object)


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
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.engine = engine
        self.clip_widget = clip_widget
        self.file_path = file_path
        self.source_start = source_start
        self.duration = duration
        self.count = count
        self.rotation = rotation
        self.flip_horizontal = flip_horizontal
        self.flip_vertical = flip_vertical
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
                rotation=self.rotation,
                flip_horizontal=self.flip_horizontal,
                flip_vertical=self.flip_vertical,
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
        self.setWindowTitle("MovieEditor - Studio")
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0c0a17;
                color: #f5f3ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QSplitter {
                background-color: #0c0a17;
            }
            QSplitter::handle {
                background-color: #2b2154;
            }
            QSplitter::handle:hover {
                background-color: #7c3aed;
            }
            QPushButton.export-btn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:0.5 #9333ea, stop:1 #d946ef);
                color: #ffffff;
                border: 1px solid #c084fc;
                border-radius: 5px;
                padding: 6px 18px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton.export-btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:0.5 #a855f7, stop:1 #e879f9);
                border-color: #f0abfc;
            }
            QPushButton.export-btn:pressed {
                background-color: #581c87;
            }
        """)

        # Responsive sizing
        self.setMinimumSize(850, 520)
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(1400, max(1000, int(avail.width() * 0.88)))
            h = min(850, max(600, int(avail.height() * 0.88)))
            self.resize(w, h)
        else:
            self.resize(1280, 720)

        # Thread pool and active worker tracking
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers: set = set()

        # 1. Instantiate Engine and Project Data Model
        self.preview_engine = PreviewEngine(cache_size=160)
        self.fps: float = 30.0
        self.sample_rate: int = 44100
        self.project = Project(name="MovieEditor Project", resolution=(1920, 1080), fps=self.fps)

        # Standard Tracks (Video 1, Video 2, Audio 1)
        self.track_v1 = self.project.add_track("Video 1", track_type="video")
        self.track_v2 = self.project.add_track("Video 2", track_type="video")
        self.track_a1 = self.project.add_track("Audio 1", track_type="audio")

        # Playback Timing State
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

        # 3. Main Central Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Top Header Bar (Futuristic Violet Theme)
        header_bar = QWidget()
        header_bar.setFixedHeight(38)
        header_bar.setStyleSheet("""
            QWidget {
                background-color: #120e24;
                border: 1px solid #2d2159;
                border-radius: 6px;
            }
        """)
        h_layout = QHBoxLayout(header_bar)
        h_layout.setContentsMargins(12, 2, 12, 2)
        h_layout.setSpacing(10)

        lbl_app = QLabel("🎬  MovieEditor Studio")
        lbl_app.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_app.setStyleSheet("color: #c084fc; background: transparent; border: none;")
        h_layout.addWidget(lbl_app)

        self.lbl_proj_info = QLabel("• 1080p 30fps")
        self.lbl_proj_info.setStyleSheet("color: #a78bfa; font-size: 11px; background: transparent; border: none;")
        h_layout.addWidget(self.lbl_proj_info)

        h_layout.addStretch()

        self.btn_export = QPushButton("🚀 Export Video")
        self.btn_export.setProperty("class", "export-btn")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setToolTip("Export project as MP4 or WebM (Ctrl+E)")
        self.btn_export.clicked.connect(self._open_export_dialog)
        h_layout.addWidget(self.btn_export)

        main_layout.addWidget(header_bar)

        # Main horizontal splitter (Media Pool on Left, Player & Timeline on Right)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)

        # Left pane: Media Pool
        self.media_pool_view = MediaPoolView()
        self.media_pool_view.setMinimumWidth(270)
        main_splitter.addWidget(self.media_pool_view)

        # Right pane: Vertical splitter (Player on Top, Timeline on Bottom)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setChildrenCollapsible(False)

        self.player_view = PlayerView()
        self.player_view.setMinimumSize(320, 220)

        self.timeline_view = TimelineView()
        self.timeline_view.setMinimumSize(320, 180)

        right_splitter.addWidget(self.player_view)
        right_splitter.addWidget(self.timeline_view)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setSizes([550, 350])

        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setSizes([290, 1200])

        main_layout.addWidget(main_splitter)

        # 4. Playback Timer (~60 FPS)
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(16)
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
        self.media_pool_view.add_to_timeline_requested.connect(self._on_media_add_to_timeline)
        self.media_pool_view.duration_changed.connect(self._on_media_duration_changed)

        # 7. Connect Timeline Signals
        self.timeline_view.scrub_started.connect(self.pause)
        self.timeline_view.seek_requested.connect(self._on_timeline_seek)
        self.timeline_view.clip_dropped.connect(self._on_clip_dropped)
        self.timeline_view.clip_selected.connect(self._on_clip_selected)
        self.timeline_view.clip_delete_requested.connect(self._on_clip_delete_requested)
        self.timeline_view.split_requested.connect(self._on_split_requested)
        self.timeline_view.trim_requested.connect(self._on_trim_requested)
        self.timeline_view.clip_moved.connect(self._on_clip_moved)
        self.timeline_view.clip_time_updated.connect(self._on_clip_time_updated)
        self.timeline_view.clip_transform_changed.connect(self._on_clip_transform_changed)
        self.timeline_view.split_at_playhead_requested.connect(self._on_split_at_playhead)
        self.timeline_view.track_volume_changed.connect(self._on_track_volume_changed)
        self.timeline_view.track_mute_toggled.connect(self._on_track_mute_toggled)

        # Sync initial track strips with project model track IDs & volume/mute state
        for idx, track in enumerate(self.project.tracks):
            if idx < len(self.timeline_view.canvas.track_strips):
                strip = self.timeline_view.canvas.track_strips[idx]
                strip.track_id = track.id
                strip.header.track_id = track.id
                strip.header.set_volume(track.volume)
                strip.header.set_muted(track.is_muted)

        # Sync max timeline boundary with initial project state
        self.timeline_view.set_max_duration(self.get_max_timeline_duration())
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
        rot = int(getattr(clip_widget, "rotation", 0))
        flip_h = bool(getattr(clip_widget, "flip_horizontal", False))
        flip_v = bool(getattr(clip_widget, "flip_vertical", False))
        worker = ThumbnailWorker(
            engine=self.preview_engine,
            clip_widget=clip_widget,
            file_path=file_path,
            source_start=source_start,
            duration=duration,
            count=10,
            rotation=rot,
            flip_horizontal=flip_h,
            flip_vertical=flip_v,
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
        self._active_workers.discard(worker)
        try:
            from PyQt6 import sip
            if clip_widget is not None and not sip.isdeleted(clip_widget):
                clip_widget.set_thumbnails(thumbnails)
        except (RuntimeError, ReferenceError, Exception):
            pass

    @pyqtSlot(object)
    def _on_clip_selected(self, clip_widget: ClipWidget) -> None:
        self.selected_clip_widget = clip_widget

    @pyqtSlot(object)
    def _on_clip_delete_requested(self, clip_widget: ClipWidget) -> None:
        self.selected_clip_widget = clip_widget
        self.delete_selected_clip()

    def delete_selected_clip(self) -> None:
        """Deletes the currently selected clip from the project model and timeline canvas."""
        if not self.selected_clip_widget:
            return

        cw = self.selected_clip_widget
        for worker in list(self._active_workers):
            if getattr(worker, "clip_widget", None) is cw:
                if hasattr(worker, "cancel"):
                    worker.cancel()

        track_index = getattr(cw, "track_index", -1)
        if 0 <= track_index < len(self.project.tracks):
            track = self.project.tracks[track_index]
            matching = [
                c for c in track.clips
                if c.id == cw.clip_id or (c.file_path == cw.file_path and abs(c.timeline_position - cw.timeline_position) < 0.01)
            ]
            for m in matching:
                track.clips.remove(m)

        self.timeline_view.remove_clip_widget(cw)
        self.selected_clip_widget = None

        max_dur = self.get_max_timeline_duration()
        self.timeline_view.set_max_duration(max_dur)
        if self.current_playback_time > max_dur:
            self.current_playback_time = max_dur

        if self._is_playing:
            self._start_audio()

        self._render_current_frame(force=True)

    @pyqtSlot(str, float)
    def _on_split_requested(self, clip_id: str, global_time: float) -> None:
        """Splits the specified clip at global_time and refreshes the timeline blocks."""
        res = self.project.split_clip(clip_id, global_time)
        if not res:
            return

        self._rebuild_timeline_widgets()

    @pyqtSlot()
    def _on_split_at_playhead(self) -> None:
        """Splits the active clip underneath the current playhead position."""
        target_clip_id: Optional[str] = None

        # 1. Prefer explicitly selected clip
        if self.selected_clip_widget and hasattr(self.selected_clip_widget, "clip_id"):
            cw = self.selected_clip_widget
            if cw.timeline_position < self.current_playback_time < cw.timeline_position + cw.duration:
                target_clip_id = cw.clip_id

        # 2. Fallback to top-most active clip at playhead
        if not target_clip_id:
            match = self.project.find_clip_at(self.current_playback_time)
            if match:
                _, clip, _ = match
                target_clip_id = clip.id

        if target_clip_id:
            self._on_split_requested(target_clip_id, self.current_playback_time)

    @pyqtSlot(object, float, bool)
    def _on_trim_requested(self, clip_widget: ClipWidget, new_value: float, is_left: bool) -> None:
        """Applies edge trimming and slow-motion stretching to the model and updates playhead bounds."""
        track_index = getattr(clip_widget, "track_index", -1)
        if not (0 <= track_index < len(self.project.tracks)):
            return

        track = self.project.tracks[track_index]
        clip_id = getattr(clip_widget, "clip_id", "")

        if is_left:
            track.trim_clip_left(clip_id, new_value)
        else:
            track.trim_clip_right(clip_id, new_value)

        clip_model = track.find_clip_by_id(clip_id)
        if clip_model:
            clip_widget.duration = clip_model.duration
            if hasattr(clip_widget, "lbl_dur"):
                if abs(clip_model.speed - 1.0) >= 0.05:
                    clip_widget.lbl_dur.setText(f"{clip_model.duration:.1f}s ({clip_model.speed:.2f}x)")
                else:
                    clip_widget.lbl_dur.setText(f"{clip_model.duration:.1f}s")

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())
        self._render_current_frame(force=True)

    @pyqtSlot(object, float, int)
    def _on_clip_moved(
        self,
        clip_widget: ClipWidget,
        new_timeline_pos: float,
        target_track_index: int = -1,
    ) -> None:
        """Updates clip's timeline position and moves between tracks (e.g. Video 1 <-> Video 2)."""
        source_track_index = getattr(clip_widget, "track_index", -1)
        clip_id = getattr(clip_widget, "clip_id", "")
        if not clip_id:
            return

        if target_track_index < 0:
            target_track_index = source_track_index

        if not (0 <= target_track_index < len(self.project.tracks)):
            target_track_index = max(0, min(len(self.project.tracks) - 1, source_track_index))

        # Check track compatibility (e.g., video clips move between video tracks)
        source_track = self.project.tracks[source_track_index] if 0 <= source_track_index < len(self.project.tracks) else None
        target_track = self.project.tracks[target_track_index]

        # Prevent moving video clip to audio track if types mismatch
        if source_track and source_track.track_type != target_track.track_type:
            target_track_index = source_track_index

        # Move clip in the Project model
        moved = self.project.move_clip_to_track(
            clip_id=clip_id,
            target_track_index=target_track_index,
            new_timeline_position=new_timeline_pos,
        )

        if moved and target_track_index != source_track_index:
            # Rebuild widgets so the visual clip block sits on the target track lane
            self._rebuild_timeline_widgets()
            # Restore selection on the moved clip
            for strip in self.timeline_view.canvas.track_strips:
                for cw in strip.lane.clip_widgets:
                    if cw.clip_id == clip_id:
                        cw.set_selected(True)
                        self.selected_clip_widget = cw
                        break
        else:
            clip_widget.timeline_position = max(0.0, new_timeline_pos)
            new_x = int(clip_widget.timeline_position * clip_widget.pixels_per_second)
            clip_widget.move(new_x, clip_widget.y())

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())
        self._render_current_frame(force=True)

    @pyqtSlot(str, float, float)
    def _on_clip_time_updated(self, clip_id: str, new_start: float, new_end: float) -> None:
        """Invoked when user updates clip in/out play time via SetTimeDialog.

        Updates the underlying Clip model, synchronizes widget duration and max timeline length,
        reloads filmstrip thumbnails, and refreshes the preview display.

        Args:
            clip_id (str): UUID identifier of the target clip.
            new_start (float): New in-point source timestamp in seconds.
            new_end (float): New out-point source timestamp in seconds.
        """
        if not clip_id:
            return

        target_clip: Optional[Clip] = None
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    target_clip = clip
                    break
            if target_clip:
                break

        if not target_clip:
            return

        try:
            target_clip.update_source_times(new_start, new_end)
        except ValueError:
            return

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())

        # Update matching ClipWidget and reload thumbnails for new time span
        for strip in self.timeline_view.canvas.track_strips:
            for cw in strip.lane.clip_widgets:
                if cw.clip_id == clip_id:
                    cw.source_start = target_clip.source_start
                    cw.source_end = target_clip.source_end
                    cw.duration = target_clip.duration
                    self._load_thumbnails_async(cw, target_clip.file_path, target_clip.source_start, target_clip.duration)
                    break

        self._render_current_frame(force=True)

    @pyqtSlot(str, int, bool, bool)
    def _on_clip_transform_changed(
        self,
        clip_id: str,
        rotation: int,
        flip_h: bool,
        flip_v: bool,
    ) -> None:
        """Invoked when user modifies clip rotation or flip state via context menu.

        Updates the underlying Clip model, reloads filmstrip thumbnails to reflect transformed
        orientation, and refreshes the preview display.

        Args:
            clip_id (str): UUID identifier of the target clip.
            rotation (int): Clockwise rotation angle in degrees.
            flip_h (bool): True if mirrored horizontally.
            flip_v (bool): True if mirrored vertically.
        """
        if not clip_id:
            return

        target_clip: Optional[Clip] = None
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    target_clip = clip
                    break
            if target_clip:
                break

        if not target_clip:
            return

        target_clip.set_rotation(rotation)
        target_clip.flip_horizontal = flip_h
        target_clip.flip_vertical = flip_v

        # Update matching ClipWidget and reload thumbnails
        for strip in self.timeline_view.canvas.track_strips:
            for cw in strip.lane.clip_widgets:
                if cw.clip_id == clip_id:
                    cw.rotation = rotation
                    cw.flip_horizontal = flip_h
                    cw.flip_vertical = flip_v
                    self._load_thumbnails_async(cw, target_clip.file_path, target_clip.source_start, target_clip.duration)
                    break

        self._render_current_frame(force=True)

    def _rebuild_timeline_widgets(self) -> None:
        """Cleans and re-instantiates clip widgets matching the current project model."""
        # Cancel running workers
        for worker in list(self._active_workers):
            if hasattr(worker, "cancel"):
                worker.cancel()
        self._active_workers.clear()

        # Remove all existing widgets from all track strips
        for strip in self.timeline_view.canvas.track_strips:
            for cw in list(strip.lane.clip_widgets):
                strip.lane.remove_clip(cw)

        # Re-add matching clips from model
        for t_idx, track in enumerate(self.project.tracks):
            if t_idx < len(self.timeline_view.canvas.track_strips):
                strip = self.timeline_view.canvas.track_strips[t_idx]
                strip.track_id = track.id
                strip.header.track_id = track.id
                strip.header.set_volume(track.volume)
                strip.header.set_muted(track.is_muted)
            for clip in track.clips:
                clip_w = self.timeline_view.add_clip(
                    track_index=t_idx,
                    file_path=clip.file_path,
                    timeline_position=clip.timeline_position,
                    duration=clip.duration,
                    clip_id=clip.id,
                    source_start=clip.source_start,
                    source_end=clip.source_end,
                    rotation=clip.rotation,
                    flip_horizontal=clip.flip_horizontal,
                    flip_vertical=clip.flip_vertical,
                )
                if clip_w:
                    self._load_thumbnails_async(clip_w, clip.file_path, clip.source_start, clip.duration)

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())
        self._render_current_frame(force=True)

    @pyqtSlot(str, int, float)
    def _on_clip_dropped(self, file_path: str, track_index: int, timeline_pos: float) -> None:
        """Invoked when a media file (video or image) is dropped onto a timeline track."""
        if not file_path or not os.path.exists(file_path):
            return

        if not (0 <= track_index < len(self.project.tracks)):
            return

        self.media_pool_view.add_media_item(file_path)

        custom_dur = None
        if hasattr(self.media_pool_view, "get_custom_duration"):
            custom_dur = self.media_pool_view.get_custom_duration(file_path)

        media_type = detect_media_type(file_path)
        if media_type == "image":
            real_duration = custom_dur if (custom_dur is not None and custom_dur > 0) else 5.0
            new_clip = Clip(
                file_path=file_path,
                name=os.path.basename(file_path),
                media_type="image",
                image_duration=real_duration,
                timeline_position=timeline_pos,
            )
        else:
            full_duration = self.preview_engine.get_media_duration(file_path)
            if full_duration <= 0.0:
                full_duration = 5.0
            real_duration = min(full_duration, custom_dur) if (custom_dur is not None and custom_dur > 0) else full_duration
            new_clip = Clip(
                file_path=file_path,
                name=os.path.basename(file_path),
                source_start=0.0,
                source_end=real_duration,
                timeline_position=timeline_pos,
                media_type=media_type,
            )

        self.project.tracks[track_index].clips.append(new_clip)

        clip_w = self.timeline_view.add_clip(
            track_index=track_index,
            file_path=file_path,
            timeline_position=timeline_pos,
            duration=real_duration,
            clip_id=new_clip.id,
            source_start=new_clip.source_start,
            source_end=new_clip.source_end,
        )

        if clip_w:
            self._load_thumbnails_async(clip_w, file_path, new_clip.source_start, real_duration)

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())

        was_playing = self._is_playing
        self.current_playback_time = timeline_pos
        self._render_current_frame(force=True)

        if was_playing:
            self.play()

    @pyqtSlot(list, float)
    def _on_media_add_to_timeline(self, file_paths: List[str], duration: float) -> None:
        """Appends selected media files from Media Pool to Track 1 ending at the specified duration (1.0x speed)."""
        if not file_paths:
            return

        target_track_index = 0
        if not (0 <= target_track_index < len(self.project.tracks)):
            target_track_index = 0

        track = self.project.tracks[target_track_index]
        current_pos = track.get_track_duration()

        for fp in file_paths:
            if not fp or not os.path.exists(fp):
                continue

            self.media_pool_view.add_media_item(fp)
            media_type = detect_media_type(fp)

            if media_type == "image":
                real_dur = duration if duration > 0 else 5.0
                new_clip = Clip(
                    file_path=fp,
                    name=os.path.basename(fp),
                    media_type="image",
                    image_duration=real_dur,
                    timeline_position=current_pos,
                )
            else:
                full_dur = self.preview_engine.get_media_duration(fp)
                if full_dur <= 0.0:
                    full_dur = 5.0
                real_dur = min(full_dur, duration) if duration > 0 else full_dur
                new_clip = Clip(
                    file_path=fp,
                    name=os.path.basename(fp),
                    source_start=0.0,
                    source_end=real_dur,
                    timeline_position=current_pos,
                    media_type=media_type,
                )

            track.clips.append(new_clip)
            clip_w = self.timeline_view.add_clip(
                track_index=target_track_index,
                file_path=fp,
                timeline_position=current_pos,
                duration=real_dur,
                clip_id=new_clip.id,
                source_start=new_clip.source_start,
                source_end=new_clip.source_end,
            )
            if clip_w:
                self._load_thumbnails_async(clip_w, fp, new_clip.source_start, real_dur)

            current_pos += real_dur

        self.timeline_view.set_max_duration(self.get_max_timeline_duration())
        self._render_current_frame(force=True)

    @pyqtSlot(list, float)
    def _on_media_duration_changed(self, file_paths: List[str], duration: float) -> None:
        """Updates end duration for any active timeline clip matching selected files without altering playback speed."""
        if duration <= 0:
            return

        modified = False
        if self.selected_clip_widget and hasattr(self.selected_clip_widget, "clip_id"):
            cw = self.selected_clip_widget
            if cw.file_path in file_paths:
                for track in self.project.tracks:
                    clip = track.find_clip_by_id(cw.clip_id)
                    if clip:
                        if clip.is_image:
                            clip.image_duration = duration
                        else:
                            clip.source_end = clip.source_start + duration
                            clip.playback_duration = None
                        modified = True

        if modified:
            self._rebuild_timeline_widgets()

    @pyqtSlot(float)
    def _on_timeline_seek(self, time_sec: float) -> None:
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
        self.preview_engine.get_media_info(file_path)

    @pyqtSlot(float)
    def _on_volume_changed(self, vol: float) -> None:
        self.volume = vol
        if not self.is_muted:
            self.audio_sink.setVolume(vol)

    @pyqtSlot(bool)
    def _on_mute_toggled(self, is_muted: bool) -> None:
        self.is_muted = is_muted
        self.audio_sink.setVolume(0.0 if is_muted else self.volume)

    @pyqtSlot(str, float)
    def _on_track_volume_changed(self, track_id: str, new_volume: float) -> None:
        """Updates track volume in the data model and refreshes audio playback."""
        for track in self.project.tracks:
            if track.id == track_id:
                track.set_volume(new_volume)
                break
        if self._is_playing:
            self._start_audio()

    @pyqtSlot(str, bool)
    def _on_track_mute_toggled(self, track_id: str, is_muted: bool) -> None:
        """Toggles track muting in the data model and refreshes audio playback."""
        for track in self.project.tracks:
            if track.id == track_id:
                track.set_muted(is_muted)
                break
        if self._is_playing:
            self._start_audio()

    def _start_audio(self) -> None:
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
        if self.audio_sink:
            self.audio_sink.reset()
        if self.audio_buffer:
            self.audio_buffer.close()
            self.audio_buffer = None

    @pyqtSlot()
    def toggle_play(self) -> None:
        if self._is_playing:
            self.pause()
        else:
            self.play()

    @pyqtSlot()
    def play(self) -> None:
        max_duration = self.get_max_timeline_duration()
        if max_duration <= 0.0:
            return

        if self.current_playback_time >= max_duration:
            self.current_playback_time = 0.0

        self._is_playing = True
        self._playback_start_wall_time = time.perf_counter()
        self._playback_start_timeline_time = self.current_playback_time
        self.player_view.set_playing_state(True)

        self._start_audio()

        if not self.playback_timer.isActive():
            self.playback_timer.start()

    @pyqtSlot()
    def pause(self) -> None:
        self._is_playing = False
        if self.playback_timer.isActive():
            self.playback_timer.stop()
        self._stop_audio()
        self.player_view.set_playing_state(False)

    @pyqtSlot()
    def rewind(self) -> None:
        self.pause()
        self.current_playback_time = 0.0
        self._render_current_frame(force=True)

    def step_frame(self, frame_delta: int) -> None:
        self.pause()
        frame_time = 1.0 / max(1.0, self.fps)
        new_time = max(0.0, self.current_playback_time + (frame_delta * frame_time))
        max_dur = self.get_max_timeline_duration()
        if max_dur > 0:
            new_time = min(new_time, max_dur)
        self.current_playback_time = new_time
        self._render_current_frame(force=True)

    @pyqtSlot()
    def _open_export_dialog(self) -> None:
        """Opens the video export settings modal dialog."""
        self.pause()
        dlg = ExportDialog(self.project, self)
        dlg.exec()

    @pyqtSlot()
    def _on_playback_tick(self) -> None:
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
        self.timeline_view.set_playhead_time(self.current_playback_time)

        quant_time = int(round(self.current_playback_time * self.fps))
        if force or quant_time != self._last_rendered_quant_time:
            self._last_rendered_quant_time = quant_time

            status = self.preview_engine.get_playback_status(self.project, self.current_playback_time)
            self.player_view.update_status(status)

            frame = self.preview_engine.get_project_frame(self.project, self.current_playback_time)
            self.player_view.update_frame(frame)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

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
        elif key == Qt.Key.Key_V and not (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.timeline_view.set_active_tool("select")
            event.accept()
        elif key == Qt.Key.Key_C and not (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.timeline_view.set_active_tool("razor")
            event.accept()
        elif (modifiers & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_B:
            self._on_split_at_playhead()
            event.accept()
        elif (modifiers & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_E:
            self._open_export_dialog()
            event.accept()
        elif (modifiers & Qt.KeyboardModifier.ControlModifier) and key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.timeline_view.zoom_in()
            event.accept()
        elif (modifiers & Qt.KeyboardModifier.ControlModifier) and key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.timeline_view.zoom_out()
            event.accept()
        elif ((modifiers & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_0) or (key == Qt.Key.Key_Z and (modifiers & Qt.KeyboardModifier.ShiftModifier)):
            self.timeline_view.zoom_fit_to_screen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.playback_timer.stop()
        self._stop_audio()
        for worker in list(self._active_workers):
            if hasattr(worker, "cancel"):
                worker.cancel()
        self._active_workers.clear()
        self.thread_pool.waitForDone(500)
        self.preview_engine.close()
        super().closeEvent(event)