import math
import os
from PyQt6.QtCore import QPoint, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygon,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Standard time-scaling constant: 20 pixels per second
PIXELS_PER_SECOND: float = 20.0
DEFAULT_CLIP_DURATION: float = 10.0


class ClipWidget(QWidget):
    """A professional NLE clip block with rounded corners, solid background, and elided text."""

    def __init__(
        self,
        clip_name: str,
        file_path: str,
        duration: float = DEFAULT_CLIP_DURATION,
        pixels_per_second: float = PIXELS_PER_SECOND,
        parent: QWidget | None = None,
        x: int = 0,
        y: int = 2,
        height: int = 52,
    ):
        super().__init__(parent)
        self.clip_name = clip_name
        self.file_path = file_path
        self.duration = max(0.5, duration)
        self.pixels_per_second = pixels_per_second

        # Force Qt stylesheet rendering on custom QWidget
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ClipWidget")

        # Time-scaled width (e.g. 10s * 20px/s = 200px)
        width = max(50, int(self.duration * self.pixels_per_second))
        self.setGeometry(x, y, width, height)

        # Solid professional NLE clip styling
        self.setStyleSheet("""
            QWidget#ClipWidget {
                background-color: #2a5d84;
                border: 1px solid #4a90e2;
                border-radius: 4px;
                padding: 2px;
                color: white;
            }
            QLabel {
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)

        # Use QFontMetrics to cleanly elide text (add '...') if clip name exceeds width
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        available_width = max(20, width - 16)
        elided_title = metrics.elidedText(clip_name, Qt.TextElideMode.ElideRight, available_width)

        self.lbl_title = QLabel(elided_title)
        self.lbl_title.setFont(font)
        self.lbl_title.setToolTip(f"{clip_name}\nPath: {file_path}\nDuration: {self.duration:.1f}s")
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.lbl_title)
        self.show()


class TrackLaneWidget(QWidget):
    """The droppable canvas lane of a single track where clips are placed."""

    clip_dropped = pyqtSignal(str, int, float)

    def __init__(self, track_index: int, pixels_per_second: float = PIXELS_PER_SECOND):
        super().__init__()
        self.track_index = track_index
        self.pixels_per_second = pixels_per_second
        self.setAcceptDrops(True)
        self.clip_widgets: list[ClipWidget] = []
        self.setStyleSheet("""
            TrackLaneWidget {
                background-color: #242424;
                border-bottom: 1px solid #2d2d2d;
            }
        """)

    def add_clip(
        self,
        clip_name: str,
        file_path: str,
        timeline_position: float,
        duration: float,
    ) -> ClipWidget:
        """Adds a visual clip block to the track lane matching its exact duration and timeline position."""
        drop_x = int(timeline_position * self.pixels_per_second)
        clip_height = max(36, self.height() - 4) if self.height() > 8 else 52

        clip_widget = ClipWidget(
            clip_name=clip_name,
            file_path=file_path,
            duration=duration,
            pixels_per_second=self.pixels_per_second,
            parent=self,
            x=drop_x,
            y=2,
            height=clip_height,
        )
        self.clip_widgets.append(clip_widget)
        return clip_widget

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        file_path = event.mimeData().text()
        if not file_path and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()

        if file_path:
            # Calculate drop X-coordinate and timeline position
            drop_x = int(event.position().x())
            timeline_position = max(0.0, drop_x / self.pixels_per_second)

            # Emit custom PyQt signal so MainWindow can retrieve exact duration and place clip
            self.clip_dropped.emit(file_path, self.track_index, timeline_position)
            event.acceptProposedAction()


class TrackStripWidget(QWidget):
    """A single horizontal track strip containing the header and droppable lane."""

    clip_dropped = pyqtSignal(str, int, float)

    def __init__(
        self,
        track_name: str,
        track_index: int = 0,
        pixels_per_second: float = PIXELS_PER_SECOND,
        height: int = 56,
    ):
        super().__init__()
        self.track_name = track_name
        self.track_index = track_index
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Track Header (Left side title)
        self.header = QWidget()
        self.header.setFixedWidth(120)
        self.header.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-right: 1px solid #333333;
                border-bottom: 1px solid #2d2d2d;
            }
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 0, 8, 0)
        lbl_name = QLabel(track_name)
        lbl_name.setStyleSheet("color: #b0b0b0; font-size: 12px; font-weight: bold;")
        header_layout.addWidget(lbl_name)
        layout.addWidget(self.header)

        # Track Lane (Right side droppable area)
        self.lane = TrackLaneWidget(
            track_index=track_index,
            pixels_per_second=pixels_per_second,
        )
        self.lane.clip_dropped.connect(self.clip_dropped.emit)
        layout.addWidget(self.lane, stretch=1)


class PlayheadOverlay(QWidget):
    """Dedicated floating top-level overlay widget for the red playhead."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(16)
        self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        height = self.height()
        red_color = QColor("#ff3b30")

        # 1. Vertical Red Line down the exact center (x = 8)
        painter.setPen(QPen(red_color, 2))
        painter.drawLine(8, 0, 8, height)

        # 2. Playhead Pointer Head (inverted triangle / pentagon at top)
        head_width = 14
        head_height = 14
        head_poly = QPolygon([
            QPoint(8 - head_width // 2, 0),
            QPoint(8 + head_width // 2, 0),
            QPoint(8 + head_width // 2, head_height - 5),
            QPoint(8, head_height),
            QPoint(8 - head_width // 2, head_height - 5),
        ])
        painter.setBrush(QBrush(red_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(head_poly)


class TimelineCanvas(QWidget):
    """The interactive multi-track canvas with time ruler, clamped playhead, and dynamic width expansion."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)

    def __init__(self, pixels_per_second: float = PIXELS_PER_SECOND, header_width: int = 120):
        super().__init__()
        self.pixels_per_second = pixels_per_second
        self.header_width = header_width
        self.playhead_time = 0.0
        self.total_duration = 300.0  # Default 5 minutes
        self.is_scrubbing = False
        self.track_strips: list[TrackStripWidget] = []

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(int(self.header_width + self.total_duration * self.pixels_per_second))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Top Ruler
        self.ruler_height = 28
        self.ruler_spacer = QWidget()
        self.ruler_spacer.setFixedHeight(self.ruler_height)
        self.main_layout.addWidget(self.ruler_spacer)

        # 2. Container for dynamically added track strips
        self.tracks_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.tracks_container)
        self.tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_layout.setSpacing(2)
        self.main_layout.addWidget(self.tracks_container)
        self.main_layout.addStretch()

        # 3. Floating Overlay Playhead
        self.playhead = PlayheadOverlay(self)
        self._reposition_playhead()

    def ensure_width(self, required_width: int) -> None:
        """Dynamically expands canvas minimumWidth so QScrollArea horizontal scrollbar activates."""
        current_min = self.minimumWidth()
        if required_width > current_min:
            new_width = required_width + 400
            self.setMinimumWidth(new_width)
            self.updateGeometry()
            self.update()

    def add_track_strip(self, track_name: str) -> TrackStripWidget:
        """Dynamically instantiates and appends a track strip."""
        track_index = len(self.track_strips)
        strip = TrackStripWidget(
            track_name=track_name,
            track_index=track_index,
            pixels_per_second=self.pixels_per_second,
        )
        strip.clip_dropped.connect(self._on_track_clip_dropped)
        self.track_strips.append(strip)
        self.tracks_layout.addWidget(strip)
        self._reposition_playhead()
        return strip

    def add_clip_to_track(
        self,
        track_index: int,
        file_path: str,
        timeline_position: float,
        duration: float,
    ) -> ClipWidget | None:
        """Adds a time-scaled clip block to a specific track and expands canvas width."""
        if 0 <= track_index < len(self.track_strips):
            strip = self.track_strips[track_index]
            file_name = os.path.basename(file_path)
            clip_w = strip.lane.add_clip(
                clip_name=file_name,
                file_path=file_path,
                timeline_position=timeline_position,
                duration=duration,
            )
            drop_x = self.time_to_x(timeline_position)
            clip_pixel_w = int(duration * self.pixels_per_second)
            self.ensure_width(drop_x + clip_pixel_w + 100)
            return clip_w
        return None

    def _on_track_clip_dropped(self, file_path: str, track_index: int, timeline_pos: float) -> None:
        """Expands canvas width on drop and forwards signal."""
        drop_x = self.time_to_x(timeline_pos)
        self.ensure_width(drop_x + 300)
        self.clip_dropped.emit(file_path, track_index, timeline_pos)

    def time_to_x(self, seconds: float) -> int:
        """Converts timeline seconds into local pixel x coordinate."""
        return int(self.header_width + (seconds * self.pixels_per_second))

    def x_to_time(self, x: int) -> float:
        """Converts local pixel x coordinate into timeline seconds, strictly clamped >= 0."""
        clamped_x = max(self.header_width, min(x, self.width()))
        time_sec = (clamped_x - self.header_width) / self.pixels_per_second
        return max(0.0, time_sec)

    def set_playhead_time(self, seconds: float) -> None:
        """Updates playhead position and dynamically ensures scroll width."""
        self.playhead_time = max(0.0, seconds)
        playhead_x = self.time_to_x(self.playhead_time)
        self.ensure_width(playhead_x + 100)
        self._reposition_playhead()

    def _reposition_playhead(self) -> None:
        """Clamps playhead strictly between 0s (header_width) and max canvas width."""
        playhead_x = self.time_to_x(self.playhead_time)
        max_x = max(self.header_width, self.width())
        clamped_x = max(self.header_width, min(playhead_x, max_x))
        self.playhead.setFixedHeight(max(100, self.height()))
        self.playhead.move(clamped_x - 8, 0)
        self.playhead.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_playhead()

    def paintEvent(self, event) -> None:
        """Renders time ruler background and ticks."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()

        # 1. Draw Ruler Background
        painter.fillRect(0, 0, width, self.ruler_height, QColor("#181818"))
        painter.fillRect(0, 0, self.header_width, self.ruler_height, QColor("#121212"))
        painter.setPen(QPen(QColor("#333333"), 1))
        painter.drawLine(0, self.ruler_height - 1, width, self.ruler_height - 1)
        painter.drawLine(self.header_width, 0, self.header_width, height)

        # 2. Draw Ruler Ticks & Timecode Labels
        painter.setFont(QFont("Segoe UI", 8))
        major_interval = 5 if self.pixels_per_second >= 15 else 10
        total_secs = int(math.ceil((width - self.header_width) / self.pixels_per_second))

        for sec in range(0, total_secs + 1):
            x = self.time_to_x(sec)
            if x > width:
                break

            if sec % major_interval == 0:
                # Major tick
                painter.setPen(QPen(QColor("#666666"), 1))
                painter.drawLine(x, self.ruler_height - 10, x, self.ruler_height - 1)

                # Time label (MM:SS)
                mins = sec // 60
                secs = sec % 60
                time_str = f"{mins:02d}:{secs:02d}"
                painter.setPen(QColor("#999999"))
                painter.drawText(x + 4, self.ruler_height - 6, time_str)
            else:
                # Minor sub-second tick
                painter.setPen(QPen(QColor("#3a3a3a"), 1))
                painter.drawLine(x, self.ruler_height - 5, x, self.ruler_height - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_scrubbing = True
            self.scrub_started.emit()
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()
            self.seek_requested.emit(target_time)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.is_scrubbing:
            # Visually move playhead smoothly at 60+ FPS without triggering seek/render overhead
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_scrubbing:
            self.is_scrubbing = False
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()
            # Emit seek signal on release
            self.seek_requested.emit(target_time)


class TimelineView(QScrollArea):
    """The multi-track timeline container with scroll support, drag-and-drop, and playhead sync."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("""
            QScrollArea {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
            }
            QScrollBar:horizontal {
                background-color: #181818;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background-color: #3e3e42;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #555555;
            }
            QScrollBar:vertical {
                background-color: #181818;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background-color: #3e3e42;
                border-radius: 4px;
                min-height: 20px;
            }
        """)

        # Canvas inside scroll area
        self.canvas = TimelineCanvas(pixels_per_second=PIXELS_PER_SECOND)
        self.setWidget(self.canvas)

        # Forward signals from canvas
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.scrub_started.connect(self.scrub_started.emit)
        self.canvas.clip_dropped.connect(self.clip_dropped.emit)

        # Default track strips skeleton
        self.canvas.add_track_strip("Video 1")
        self.canvas.add_track_strip("Video 2")
        self.canvas.add_track_strip("Audio 1")

    def add_track(self, track_name: str) -> TrackStripWidget:
        """Adds a new track strip dynamically to the timeline."""
        return self.canvas.add_track_strip(track_name)

    def add_clip(
        self,
        track_index: int,
        file_path: str,
        timeline_position: float,
        duration: float,
    ) -> ClipWidget | None:
        """Places a clip widget on a specific track."""
        return self.canvas.add_clip_to_track(track_index, file_path, timeline_position, duration)

    @pyqtSlot(float)
    def set_playhead_time(self, seconds: float) -> None:
        """Moves the visual playhead to the given timestamp."""
        if not self.canvas.is_scrubbing:
            self.canvas.set_playhead_time(seconds)