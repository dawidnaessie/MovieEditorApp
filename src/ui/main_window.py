import os
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import QListWidgetItem, QMainWindow, QSplitter, QVBoxLayout, QWidget

from engine.preview_engine import PreviewEngine
from models.clip import Clip
from models.project import Project
from .media_pool_view import MediaPoolView
from .player_view import PlayerView
from .timeline_view import TimelineView


class MainWindow(QMainWindow):
    """The master layout and coordinator of the application."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Movie Editor - Alpha")
        self.resize(1280, 720)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        # 1. Instantiate Engine and Project Data Model
        self.preview_engine = PreviewEngine()
        self.project = Project(name="AI Video Project", resolution=(1920, 1080), fps=30.0)

        # Setup standard tracks
        self.track_v1 = self.project.add_track("Video 1")
        self.track_v2 = self.project.add_track("Video 2")
        self.track_a1 = self.project.add_track("Audio 1")

        # Playback timing state
        self.current_playback_time: float = 0.0
        self.fps: float = 30.0
        self.frame_interval_ms: int = int(1000.0 / self.fps)  # ~33ms for 30 FPS
        self.time_step: float = 1.0 / self.fps

        # 2. Set up Multi-Pane Splitter Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Main horizontal splitter (Media Pool on Left, Player & Timeline on Right)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane: Media Pool
        self.media_pool_view = MediaPoolView()
        main_splitter.addWidget(self.media_pool_view)

        # Right pane: Vertical splitter (Player on Top, Timeline on Bottom)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.player_view = PlayerView()
        self.timeline_view = TimelineView()
        right_splitter.addWidget(self.player_view)
        right_splitter.addWidget(self.timeline_view)
        right_splitter.setSizes([460, 240])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([260, 1020])

        main_layout.addWidget(main_splitter)

        # 3. Setup QTimer for playback (30 times per second)
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(self.frame_interval_ms)
        self.playback_timer.timeout.connect(self._on_playback_tick)

        # 4. Connect PlayerView controls to MainWindow slots
        self.player_view.btn_play.clicked.connect(self.play)
        self.player_view.btn_pause.clicked.connect(self.pause)

        # 5. Connect MediaPool signals and list selection
        self.media_pool_view.media_imported.connect(self._on_media_imported)
        self.media_pool_view.list_widget.itemClicked.connect(self._on_media_item_selected)

        # 6. Connect Timeline seeking, scrubbing, and drag-and-drop signals
        self.timeline_view.scrub_started.connect(self.pause)
        self.timeline_view.seek_requested.connect(self._on_timeline_seek)
        self.timeline_view.clip_dropped.connect(self._on_clip_dropped)

        # Locate sample video and populate media pool
        video_candidates = [
            os.path.abspath("Getting hit by a lance..mp4"),
            r"C:\Users\rastisx\Desktop\Crystal Castles - Celestica.mp4",
            r"C:\Users\rastisx\Videos\2026-01-27 08-41-55.mp4",
        ]
        sample_path = next(
            (path for path in video_candidates if os.path.exists(path)),
            None,
        )

        if sample_path:
            self.media_pool_view.add_media_item(sample_path)
            # Add initial sample clip to timeline track 0
            sample_duration = self.preview_engine.get_media_duration(sample_path)
            initial_clip = Clip(
                file_path=sample_path,
                name=os.path.basename(sample_path),
                source_start=0.0,
                source_end=sample_duration,
                timeline_position=0.0,
            )
            self.track_v1.clips.append(initial_clip)
            self.timeline_view.add_clip(
                track_index=0,
                file_path=sample_path,
                timeline_position=0.0,
                duration=sample_duration,
            )

        # Render initial frame at 0.0s
        self._render_current_frame()

    def get_max_timeline_duration(self) -> float:
        """Calculates the maximum end timestamp across all clips on the timeline."""
        max_duration = 0.0
        for track in self.project.tracks:
            for clip in track.clips:
                end_time = clip.timeline_position + clip.duration
                if end_time > max_duration:
                    max_duration = end_time
        return max_duration

    @pyqtSlot(str, int, float)
    def _on_clip_dropped(self, file_path: str, track_index: int, timeline_pos: float) -> None:
        """Invoked when a media file is dragged and dropped onto a timeline track."""
        if not (0 <= track_index < len(self.project.tracks)):
            return

        # Query actual media duration from engine
        real_duration = self.preview_engine.get_media_duration(file_path)

        new_clip = Clip(
            file_path=file_path,
            name=os.path.basename(file_path),
            source_start=0.0,
            source_end=real_duration,
            timeline_position=timeline_pos,
        )
        self.project.tracks[track_index].clips.append(new_clip)

        # Place visual ClipWidget with exact time-scaled width
        self.timeline_view.add_clip(
            track_index=track_index,
            file_path=file_path,
            timeline_position=timeline_pos,
            duration=real_duration,
        )

        self.current_playback_time = timeline_pos
        self._render_current_frame()

    @pyqtSlot(float)
    def _on_timeline_seek(self, time_sec: float) -> None:
        """Invoked when user clicks/scrubs on the timeline."""
        self.current_playback_time = time_sec
        self._render_current_frame()

    @pyqtSlot(str)
    def _on_media_imported(self, file_path: str) -> None:
        """Invoked when a new media file is imported."""
        pass

    @pyqtSlot(QListWidgetItem)
    def _on_media_item_selected(self, item: QListWidgetItem) -> None:
        """Invoked when a user clicks an item in the Media Pool."""
        pass

    @pyqtSlot()
    def play(self) -> None:
        """Starts 30 FPS playback timer if clips exist."""
        max_duration = self.get_max_timeline_duration()
        if max_duration <= 0.0:
            return

        # If at or past the end, rewind to start
        if self.current_playback_time >= max_duration:
            self.current_playback_time = 0.0

        if not self.playback_timer.isActive():
            self.playback_timer.start()

    @pyqtSlot()
    def pause(self) -> None:
        """Pauses playback timer."""
        if self.playback_timer.isActive():
            self.playback_timer.stop()

    @pyqtSlot()
    def _on_playback_tick(self) -> None:
        """Fired 30 times a second; auto-stops at the end of the timeline."""
        max_duration = self.get_max_timeline_duration()

        # Auto-pause at the end of all video clips
        if max_duration > 0.0 and self.current_playback_time >= max_duration:
            self.current_playback_time = max_duration
            self._render_current_frame()
            self.pause()
            return

        self._render_current_frame()
        self.current_playback_time += self.time_step

    def _render_current_frame(self) -> None:
        """Requests composite project frame from PreviewEngine and updates PlayerView & Timeline."""
        frame = self.preview_engine.get_project_frame(
            self.project,
            global_time=self.current_playback_time,
        )
        self.player_view.update_frame(frame)
        self.timeline_view.set_playhead_time(self.current_playback_time)

    def closeEvent(self, event) -> None:
        """Clean up timer and media handles on window close."""
        self.playback_timer.stop()
        self.preview_engine.close()
        super().closeEvent(event)