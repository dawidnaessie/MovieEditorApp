"""Production Multi-Track Timeline Canvas and View conforming to Phase 2 guidelines.

Features:
- Integrated ToolbarView above the timeline (Select [V], Razor [C], Split at playhead [Ctrl+B], Delete [Del]).
- Active tool states ('select' vs 'razor') with dynamic cursor switching.
- Razor tool click-splitting on ClipWidget emitting exact cut timestamps.
- Interactive edge trimming (hovering within 8px of left/right clip edges with SizeHorCursor and dragging).
- Asynchronous thumbnail rendering and smooth playhead synchronization.
"""

import math
import os
from typing import List, Optional
import numpy as np
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal, pyqtSlot

from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .toolbar_view import ToolbarView

# Standard time-scaling constant: 25 pixels per second
PIXELS_PER_SECOND: float = 25.0
DEFAULT_CLIP_DURATION: float = 10.0


def time_to_pixel(seconds: float, header_width: int = 130, pixels_per_second: float = PIXELS_PER_SECOND) -> int:
    """Converts a timeline timestamp in seconds into a local canvas pixel X coordinate."""
    return int(header_width + (max(0.0, float(seconds)) * pixels_per_second))


def pixel_to_time(
    x: int,
    header_width: int = 130,
    pixels_per_second: float = PIXELS_PER_SECOND,
    max_duration: float = 0.0,
) -> float:
    """Converts a local canvas pixel X coordinate into timeline seconds clamped to [0.0, max_duration]."""
    raw_seconds = max(0.0, (float(x) - float(header_width)) / max(1.0, pixels_per_second))
    if max_duration > 0:
        return min(raw_seconds, float(max_duration))
    return raw_seconds


def calculate_clip_pixel_width(
    duration: float,
    pixels_per_second: float = PIXELS_PER_SECOND,
    min_width: int = 40,
) -> int:
    """Calculates the visual pixel width for a clip given its duration in seconds."""
    return max(min_width, int(max(0.0, float(duration)) * pixels_per_second))


class ClipWidget(QWidget):
    """A professional NLE clip block with title, filmstrip thumbnails, razor cutting, and edge trimming."""

    clip_selected = pyqtSignal(object)  # Emits self (ClipWidget)
    delete_requested = pyqtSignal(object)  # Emits self (ClipWidget)
    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    split_requested = pyqtSignal(str, float)  # (clip_id, global_split_time)
    trim_requested = pyqtSignal(object, float, bool)  # (self, new_val, is_left)

    def __init__(
        self,
        clip_name: str,
        file_path: str,
        timeline_position: float = 0.0,
        duration: float = DEFAULT_CLIP_DURATION,
        track_index: int = 0,
        pixels_per_second: float = PIXELS_PER_SECOND,
        clip_id: str = "",
        parent: QWidget | None = None,
        x: int = 0,
        y: int = 2,
        height: int = 58,
    ):
        super().__init__(parent)
        self.clip_name = clip_name
        self.file_path = file_path
        self.timeline_position = timeline_position
        self.duration = max(0.2, duration)
        self.track_index = track_index
        self.pixels_per_second = pixels_per_second
        self.clip_id = clip_id
        self.active_tool = "select"
        self._thumbnails: List[QPixmap] = []
        self.is_selected = False

        # Edge trimming state
        self._trim_mode: Optional[str] = None  # "left", "right", or None
        self._drag_start_x: float = 0.0
        self._orig_pos: float = 0.0
        self._orig_dur: float = 0.0
        self._orig_w: int = 0
        self._orig_x: int = 0

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setObjectName("ClipWidget")

        width = calculate_clip_pixel_width(self.duration, self.pixels_per_second)
        self.setGeometry(x, y, width, height)

        self._update_style()

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(1)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 1, 2, 1)
        header_layout.setSpacing(4)

        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        available_width = max(20, width - 40)
        elided_title = metrics.elidedText(clip_name, Qt.TextElideMode.ElideRight, available_width)

        self.lbl_title = QLabel(f"🎞️ {elided_title}")
        self.lbl_title.setFont(font)
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; background: transparent; border: none;")
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        self.lbl_dur = QLabel(f"{self.duration:.1f}s")
        self.lbl_dur.setFont(QFont("Segoe UI", 7))
        self.lbl_dur.setStyleSheet("color: #a5d6ff; background: rgba(0,0,0,0.3); border-radius: 2px; padding: 1px 3px;")
        self.lbl_dur.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(self.lbl_dur)

        layout.addLayout(header_layout)
        layout.addStretch(1)

        self.setToolTip(f"🎬 {clip_name}\nTrack: {track_index + 1}\nDuration: {self.duration:.2f}s\n[Click to select, Razor (C) to cut, Drag edge to trim]")
        self.show()

    def set_active_tool(self, tool_name: str) -> None:
        """Updates the active tool mode for this clip widget."""
        self.active_tool = tool_name
        if tool_name == "razor":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _update_style(self) -> None:
        """Updates CSS border based on selection state."""
        if self.is_selected:
            self.setStyleSheet("""
                QWidget#ClipWidget {
                    background-color: #264a78;
                    border: 2px solid #00e5ff;
                    border-radius: 5px;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget#ClipWidget {
                    background-color: #1e3a5f;
                    border: 1px solid #0284c7;
                    border-radius: 5px;
                }
            """)

    def set_selected(self, selected: bool) -> None:
        """Sets selected state and refreshes border style."""
        self.is_selected = selected
        self._update_style()

    def set_thumbnails(self, raw_thumbnails: List[np.ndarray]) -> None:
        """Loads and converts raw RGB numpy arrays into QPixmaps for the filmstrip."""
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
        except Exception:
            return

        self._thumbnails.clear()
        for thumb in raw_thumbnails:
            if thumb is None or thumb.size == 0:
                continue
            if not thumb.flags["C_CONTIGUOUS"]:
                thumb = np.ascontiguousarray(thumb)
            h, w, c = thumb.shape
            q_img = QImage(thumb.data, w, h, c * w, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(q_img)
            self._thumbnails.append(pix)
        try:
            self.update()
        except (RuntimeError, Exception):
            pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # 1. Razor Tool Split
            if self.active_tool == "razor":
                click_time = self.timeline_position + max(0.0, event.position().x() / self.pixels_per_second)
                self.split_requested.emit(self.clip_id, click_time)
                event.accept()
                return

            # 2. Edge Trimming Initiation
            x = event.position().x()
            if x <= 8:  # Left edge trim
                self._trim_mode = "left"
                self._drag_start_x = event.globalPosition().x()
                self._orig_x = self.x()
                self._orig_w = self.width()
                self._orig_pos = self.timeline_position
                self._orig_dur = self.duration
                self.set_selected(True)
                self.clip_selected.emit(self)
                event.accept()
                return
            elif x >= self.width() - 8:  # Right edge trim
                self._trim_mode = "right"
                self._drag_start_x = event.globalPosition().x()
                self._orig_w = self.width()
                self._orig_dur = self.duration
                self.set_selected(True)
                self.clip_selected.emit(self)
                event.accept()
                return

            # 3. Standard selection and scrub seek
            self.set_selected(True)
            self.clip_selected.emit(self)
            self.scrub_started.emit()
            click_time = self.timeline_position + max(0.0, event.position().x() / self.pixels_per_second)
            self.seek_requested.emit(click_time)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # 1. Active Edge Dragging
        if self._trim_mode == "right":
            dx = event.globalPosition().x() - self._drag_start_x
            new_w = max(25, int(self._orig_w + dx))
            new_dur = max(0.2, new_w / self.pixels_per_second)
            self.resize(new_w, self.height())
            self.lbl_dur.setText(f"{new_dur:.1f}s")
            event.accept()
            return
        elif self._trim_mode == "left":
            dx = event.globalPosition().x() - self._drag_start_x
            max_dx = self._orig_w - 25
            clamped_dx = max(-self._orig_x, min(dx, max_dx))
            new_x = int(self._orig_x + clamped_dx)
            new_w = int(self._orig_w - clamped_dx)
            new_dur = max(0.2, new_w / self.pixels_per_second)
            self.move(new_x, self.y())
            self.resize(new_w, self.height())
            self.lbl_dur.setText(f"{new_dur:.1f}s")
            event.accept()
            return

        # 2. Hover Cursor Updates
        if self.active_tool == "razor":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.active_tool == "select":
            x = event.position().x()
            if x <= 8 or x >= self.width() - 8:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        # 3. Scrub Seeking
        if event.buttons() & Qt.MouseButton.LeftButton and self._trim_mode is None and self.active_tool != "razor":
            current_time = self.timeline_position + (event.position().x() / self.pixels_per_second)
            self.seek_requested.emit(current_time)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._trim_mode == "right":
                dx = event.globalPosition().x() - self._drag_start_x
                new_dur = max(0.2, (self._orig_w + dx) / self.pixels_per_second)
                self.duration = new_dur
                self.trim_requested.emit(self, new_dur, False)
                self._trim_mode = None
                event.accept()
                return
            elif self._trim_mode == "left":
                dx = event.globalPosition().x() - self._drag_start_x
                new_pos = max(0.0, self._orig_pos + (dx / self.pixels_per_second))
                self.timeline_position = new_pos
                self.trim_requested.emit(self, new_pos, True)
                self._trim_mode = None
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Context menu with Delete and Split options."""
        self.set_selected(True)
        self.clip_selected.emit(self)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #222225;
                color: #e0e0e0;
                border: 1px solid #38383c;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
        """)
        action_split = QAction("✂️ Split Clip (C)", self)
        click_time = self.timeline_position + (event.pos().x() / self.pixels_per_second)
        action_split.triggered.connect(lambda: self.split_requested.emit(self.clip_id, click_time))
        menu.addAction(action_split)

        action_delete = QAction("🗑️ Delete Clip (Del)", self)
        action_delete.triggered.connect(lambda: self.delete_requested.emit(self))
        menu.addAction(action_delete)

        menu.exec(event.globalPos())

    def paintEvent(self, event) -> None:
        """Paints the background and the horizontal thumbnail filmstrip frames under the title."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()
        filmstrip_y = 20
        filmstrip_h = max(10, height - filmstrip_y - 2)

        filmstrip_rect = QRect(2, filmstrip_y, width - 4, filmstrip_h)
        painter.fillRect(filmstrip_rect, QColor("#121820"))

        if self._thumbnails:
            total_thumbs = len(self._thumbnails)
            thumb_w = max(24, int(filmstrip_h * (16 / 9)))
            needed_tiles = max(1, math.ceil((width - 4) / thumb_w))

            x_offset = 2
            for i in range(needed_tiles):
                thumb_idx = int((i / needed_tiles) * total_thumbs) % total_thumbs
                pix = self._thumbnails[thumb_idx]
                draw_w = min(thumb_w, (width - 2) - x_offset)
                if draw_w <= 0:
                    break
                painter.drawPixmap(
                    QRect(x_offset, filmstrip_y, draw_w, filmstrip_h),
                    pix,
                    QRect(0, 0, int(pix.width() * (draw_w / thumb_w)), pix.height()),
                )
                painter.setPen(QPen(QColor(0, 0, 0, 120), 1))
                painter.drawLine(x_offset + draw_w, filmstrip_y, x_offset + draw_w, filmstrip_y + filmstrip_h)
                x_offset += thumb_w
        else:
            painter.setPen(QPen(QColor("#2d3748"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(filmstrip_rect.adjusted(1, 1, -1, -1))
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor("#6e7681"))
            painter.drawText(filmstrip_rect, Qt.AlignmentFlag.AlignCenter, "Loading Frames...")


class TrackLaneWidget(QWidget):
    """The droppable canvas lane of a single track where clips are placed."""

    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)

    def __init__(self, track_index: int, pixels_per_second: float = PIXELS_PER_SECOND):
        super().__init__()
        self.track_index = track_index
        self.pixels_per_second = pixels_per_second
        self.active_tool = "select"
        self.setAcceptDrops(True)
        self.clip_widgets: list[ClipWidget] = []
        self.setStyleSheet("""
            TrackLaneWidget {
                background-color: #212124;
                border-bottom: 1px solid #2d2d30;
            }
        """)

    def set_active_tool(self, tool_name: str) -> None:
        """Updates active tool mode on all child clip widgets."""
        self.active_tool = tool_name
        for cw in self.clip_widgets:
            cw.set_active_tool(tool_name)

    def add_clip(
        self,
        clip_name: str,
        file_path: str,
        timeline_position: float,
        duration: float,
        clip_id: str = "",
    ) -> ClipWidget:
        """Adds a visual clip block to the track lane matching its duration and timeline position."""
        drop_x = int(timeline_position * self.pixels_per_second)
        clip_height = max(40, self.height() - 4) if self.height() > 8 else 58

        clip_widget = ClipWidget(
            clip_name=clip_name,
            file_path=file_path,
            timeline_position=timeline_position,
            duration=duration,
            track_index=self.track_index,
            pixels_per_second=self.pixels_per_second,
            clip_id=clip_id,
            parent=self,
            x=drop_x,
            y=2,
            height=clip_height,
        )
        clip_widget.set_active_tool(self.active_tool)
        clip_widget.clip_selected.connect(self.clip_selected.emit)
        clip_widget.delete_requested.connect(self.clip_delete_requested.emit)
        clip_widget.seek_requested.connect(self.seek_requested.emit)
        clip_widget.scrub_started.connect(self.scrub_started.emit)
        clip_widget.split_requested.connect(self.split_requested.emit)
        clip_widget.trim_requested.connect(self.trim_requested.emit)
        self.clip_widgets.append(clip_widget)
        return clip_widget

    def remove_clip(self, clip_widget: ClipWidget) -> None:
        """Removes a clip widget from this lane."""
        if clip_widget in self.clip_widgets:
            self.clip_widgets.remove(clip_widget)
        try:
            clip_widget.hide()
            clip_widget.deleteLater()
        except (RuntimeError, Exception):
            pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.scrub_started.emit()
            click_time = max(0.0, event.position().x() / self.pixels_per_second)
            self.seek_requested.emit(click_time)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            current_time = max(0.0, event.position().x() / self.pixels_per_second)
            self.seek_requested.emit(current_time)
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        file_path = ""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
        if not file_path and event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text.startswith("file:///"):
                from PyQt6.QtCore import QUrl
                file_path = QUrl(text).toLocalFile()
            else:
                file_path = text

        if file_path and os.path.exists(file_path):
            drop_x = int(event.position().x())
            timeline_position = max(0.0, drop_x / self.pixels_per_second)
            self.clip_dropped.emit(file_path, self.track_index, timeline_position)
            event.acceptProposedAction()


class TrackStripWidget(QWidget):
    """A single horizontal track strip containing the header and droppable lane."""

    clip_dropped = pyqtSignal(str, int, float)
    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)

    def __init__(
        self,
        track_name: str,
        track_index: int = 0,
        pixels_per_second: float = PIXELS_PER_SECOND,
        height: int = 64,
    ):
        super().__init__()
        self.track_name = track_name
        self.track_index = track_index
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Track Header
        self.header = QWidget()
        self.header.setFixedWidth(130)
        self.header.setStyleSheet("""
            QWidget {
                background-color: #1a1a1d;
                border-right: 1px solid #2d2d30;
                border-bottom: 1px solid #2d2d30;
            }
            QLabel {
                color: #e4e4e7;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(10, 0, 6, 0)
        h_layout.setSpacing(6)

        icon = "🔊" if "audio" in track_name.lower() else "🎬"
        self.lbl_title = QLabel(f"{icon} {track_name}")
        h_layout.addWidget(self.lbl_title)
        h_layout.addStretch()

        layout.addWidget(self.header)

        # Droppable Track Lane
        self.lane = TrackLaneWidget(track_index=track_index, pixels_per_second=pixels_per_second)
        self.lane.clip_dropped.connect(self.clip_dropped.emit)
        self.lane.clip_selected.connect(self.clip_selected.emit)
        self.lane.clip_delete_requested.connect(self.clip_delete_requested.emit)
        self.lane.seek_requested.connect(self.seek_requested.emit)
        self.lane.scrub_started.connect(self.scrub_started.emit)
        self.lane.split_requested.connect(self.split_requested.emit)
        self.lane.trim_requested.connect(self.trim_requested.emit)
        layout.addWidget(self.lane, stretch=1)


class PlayheadOverlay(QWidget):
    """Glowing red vertical needle playhead overlay."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(18)
        self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        height = self.height()
        red_color = QColor("#00e5ff")  # CapCut Cyan glowing playhead
        center_x = 9

        painter.setPen(QPen(QColor(0, 229, 255, 70), 4))
        painter.drawLine(center_x, 0, center_x, height)

        painter.setPen(QPen(red_color, 2))
        painter.drawLine(center_x, 0, center_x, height)

        head_width = 14
        head_height = 14
        head_poly = QPolygon([
            QPoint(center_x - head_width // 2, 0),
            QPoint(center_x + head_width // 2, 0),
            QPoint(center_x + head_width // 2, head_height - 5),
            QPoint(center_x, head_height),
            QPoint(center_x - head_width // 2, head_height - 5),
        ])
        painter.setBrush(QBrush(red_color))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawPolygon(head_poly)


class TimelineCanvas(QWidget):
    """The interactive multi-track canvas with time ruler, clamped playhead, and dynamic width expansion."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)

    def __init__(self, pixels_per_second: float = PIXELS_PER_SECOND, header_width: int = 130):
        super().__init__()
        self.pixels_per_second = pixels_per_second
        self.header_width = header_width
        self.playhead_time = 0.0
        self.max_duration = 0.0
        self.total_duration = 300.0
        self.is_scrubbing = False
        self.active_tool = "select"
        self.track_strips: list[TrackStripWidget] = []
        self._selected_widget: Optional[ClipWidget] = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(int(self.header_width + self.total_duration * self.pixels_per_second))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. Ruler
        self.ruler_height = 30
        self.ruler_spacer = QWidget()
        self.ruler_spacer.setFixedHeight(self.ruler_height)
        self.main_layout.addWidget(self.ruler_spacer)

        # 2. Tracks
        self.tracks_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.tracks_container)
        self.tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_layout.setSpacing(2)
        self.main_layout.addWidget(self.tracks_container)
        self.main_layout.addStretch()

        # 3. Playhead Overlay
        self.playhead = PlayheadOverlay(self)
        self._reposition_playhead()

    def set_active_tool(self, tool_name: str) -> None:
        """Updates the active tool on canvas and all lanes."""
        self.active_tool = tool_name
        for strip in self.track_strips:
            strip.lane.set_active_tool(tool_name)

    def set_max_duration(self, max_duration: float) -> None:
        """Sets the upper bound for the playhead based on the rightmost clip."""
        self.max_duration = max(0.0, max_duration)
        if self.playhead_time > self.max_duration:
            self.playhead_time = self.max_duration
        self._reposition_playhead()
        self.update()

    def deselect_all(self) -> None:
        """Deselects all clips across all tracks."""
        for strip in self.track_strips:
            for cw in strip.lane.clip_widgets:
                cw.set_selected(False)
        self._selected_widget = None

    def _on_clip_selected_internal(self, clip_widget: ClipWidget) -> None:
        for strip in self.track_strips:
            for cw in strip.lane.clip_widgets:
                if cw is not clip_widget:
                    cw.set_selected(False)
        self._selected_widget = clip_widget
        self.clip_selected.emit(clip_widget)

    def remove_clip_widget(self, clip_widget: ClipWidget) -> None:
        for strip in self.track_strips:
            if clip_widget in strip.lane.clip_widgets:
                strip.lane.remove_clip(clip_widget)
                break
        if self._selected_widget is clip_widget:
            self._selected_widget = None

    def ensure_width(self, required_width: int) -> None:
        current_min = self.minimumWidth()
        if required_width > current_min:
            new_width = required_width + 400
            self.setMinimumWidth(new_width)
            self.updateGeometry()
            self.update()

    def add_track_strip(self, track_name: str) -> TrackStripWidget:
        track_index = len(self.track_strips)
        strip = TrackStripWidget(
            track_name=track_name,
            track_index=track_index,
            pixels_per_second=self.pixels_per_second,
            height=64,
        )
        strip.clip_dropped.connect(self._on_track_clip_dropped)
        strip.clip_selected.connect(self._on_clip_selected_internal)
        strip.clip_delete_requested.connect(self.clip_delete_requested.emit)
        strip.seek_requested.connect(self._on_child_seek_requested)
        strip.scrub_started.connect(self.scrub_started.emit)
        strip.split_requested.connect(self.split_requested.emit)
        strip.trim_requested.connect(self.trim_requested.emit)
        strip.lane.set_active_tool(self.active_tool)

        self.track_strips.append(strip)
        self.tracks_layout.addWidget(strip)
        self._reposition_playhead()
        return strip

    def _on_child_seek_requested(self, target_time: float) -> None:
        if self.max_duration > 0:
            clamped_time = max(0.0, min(target_time, self.max_duration))
        else:
            clamped_time = 0.0
        self.playhead_time = clamped_time
        self._reposition_playhead()
        self.seek_requested.emit(clamped_time)

    def add_clip_to_track(
        self,
        track_index: int,
        file_path: str,
        timeline_position: float,
        duration: float,
        clip_id: str = "",
    ) -> ClipWidget | None:
        if 0 <= track_index < len(self.track_strips):
            strip = self.track_strips[track_index]
            file_name = os.path.basename(file_path)
            clip_w = strip.lane.add_clip(
                clip_name=file_name,
                file_path=file_path,
                timeline_position=timeline_position,
                duration=duration,
                clip_id=clip_id,
            )
            drop_x = self.time_to_x(timeline_position)
            clip_pixel_w = int(duration * self.pixels_per_second)
            self.ensure_width(drop_x + clip_pixel_w + 100)
            return clip_w
        return None

    def _on_track_clip_dropped(self, file_path: str, track_index: int, timeline_pos: float) -> None:
        drop_x = self.time_to_x(timeline_pos)
        self.ensure_width(drop_x + 300)
        self.clip_dropped.emit(file_path, track_index, timeline_pos)

    def time_to_x(self, seconds: float) -> int:
        return int(self.header_width + (seconds * self.pixels_per_second))

    def x_to_time(self, x: int) -> float:
        clamped_x = max(self.header_width, min(x, self.width()))
        raw_time = (clamped_x - self.header_width) / self.pixels_per_second
        if self.max_duration > 0:
            return max(0.0, min(raw_time, self.max_duration))
        return 0.0

    def set_playhead_time(self, seconds: float) -> None:
        if self.max_duration > 0:
            self.playhead_time = max(0.0, min(seconds, self.max_duration))
        else:
            self.playhead_time = 0.0
        playhead_x = self.time_to_x(self.playhead_time)
        self.ensure_width(playhead_x + 100)
        self._reposition_playhead()

    def _reposition_playhead(self) -> None:
        playhead_x = self.time_to_x(self.playhead_time)
        max_limit_x = self.time_to_x(self.max_duration) if self.max_duration > 0 else self.header_width
        clamped_x = max(self.header_width, min(playhead_x, max_limit_x))
        self.playhead.setFixedHeight(max(100, self.height()))
        self.playhead.move(clamped_x - 9, 0)
        self.playhead.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_playhead()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()

        painter.fillRect(0, 0, width, self.ruler_height, QColor("#141416"))
        painter.fillRect(0, 0, self.header_width, self.ruler_height, QColor("#0f0f11"))
        painter.setPen(QPen(QColor("#2d2d30"), 1))
        painter.drawLine(0, self.ruler_height - 1, width, self.ruler_height - 1)
        painter.drawLine(self.header_width, 0, self.header_width, height)

        painter.setFont(QFont("Segoe UI", 8))
        major_interval = 5 if self.pixels_per_second >= 15 else 10
        total_secs = int(math.ceil((width - self.header_width) / self.pixels_per_second))

        for sec in range(0, total_secs + 1):
            x = self.time_to_x(sec)
            if x > width:
                break

            if sec % major_interval == 0:
                painter.setPen(QPen(QColor("#71717a"), 1))
                painter.drawLine(x, self.ruler_height - 12, x, self.ruler_height - 1)

                mins = sec // 60
                secs = sec % 60
                time_str = f"{mins:02d}:{secs:02d}"
                painter.setPen(QColor("#00e5ff" if sec == 0 else "#a1a1aa"))
                painter.drawText(x + 4, self.ruler_height - 6, time_str)
            else:
                painter.setPen(QPen(QColor("#3f3f46"), 1))
                painter.drawLine(x, self.ruler_height - 6, x, self.ruler_height - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.deselect_all()
            self.is_scrubbing = True
            self.scrub_started.emit()
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()
            self.seek_requested.emit(target_time)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.is_scrubbing:
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()
            self.seek_requested.emit(target_time)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_scrubbing:
            self.is_scrubbing = False
            target_time = self.x_to_time(int(event.position().x()))
            self.playhead_time = target_time
            self._reposition_playhead()
            self.seek_requested.emit(target_time)


class TimelineView(QWidget):
    """The multi-track timeline container with embedded toolbar, scroll support, and CapCut aesthetics."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)  # (clip_id, global_time)
    trim_requested = pyqtSignal(object, float, bool)  # (clip_widget, new_val, is_left)
    split_at_playhead_requested = pyqtSignal()
    tool_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top Toolbar
        self.toolbar = ToolbarView(self)
        self.toolbar.tool_changed.connect(self._on_tool_changed)
        self.toolbar.split_at_playhead_requested.connect(self.split_at_playhead_requested.emit)
        self.toolbar.delete_requested.connect(self._on_toolbar_delete_requested)
        layout.addWidget(self.toolbar)

        # 2. Scroll Area containing Canvas
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #18181b;
                border: 1px solid #27272a;
            }
            QScrollBar:horizontal {
                background-color: #141416;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background-color: #3f3f46;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #0284c7;
            }
            QScrollBar:vertical {
                background-color: #141416;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background-color: #3f3f46;
                border-radius: 4px;
                min-height: 20px;
            }
        """)

        self.canvas = TimelineCanvas(pixels_per_second=PIXELS_PER_SECOND)
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, stretch=1)

        # Forward signals from canvas
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.scrub_started.connect(self.scrub_started.emit)
        self.canvas.clip_dropped.connect(self.clip_dropped.emit)
        self.canvas.clip_selected.connect(self.clip_selected.emit)
        self.canvas.clip_delete_requested.connect(self.clip_delete_requested.emit)
        self.canvas.split_requested.connect(self.split_requested.emit)
        self.canvas.trim_requested.connect(self.trim_requested.emit)

        # Default track strips
        self.canvas.add_track_strip("Video 1")
        self.canvas.add_track_strip("Video 2")
        self.canvas.add_track_strip("Audio 1")

    def _on_tool_changed(self, tool_name: str) -> None:
        self.canvas.set_active_tool(tool_name)
        self.tool_changed.emit(tool_name)

    def set_active_tool(self, tool_name: str) -> None:
        """Sets active tool and updates toolbar button state."""
        self.toolbar.set_active_tool(tool_name)

    def _on_toolbar_delete_requested(self) -> None:
        if self.canvas._selected_widget:
            self.clip_delete_requested.emit(self.canvas._selected_widget)

    def add_track(self, track_name: str) -> TrackStripWidget:
        return self.canvas.add_track_strip(track_name)

    def add_clip(
        self,
        track_index: int,
        file_path: str,
        timeline_position: float,
        duration: float,
        clip_id: str = "",
    ) -> ClipWidget | None:
        return self.canvas.add_clip_to_track(track_index, file_path, timeline_position, duration, clip_id=clip_id)

    def remove_clip_widget(self, clip_widget: ClipWidget) -> None:
        self.canvas.remove_clip_widget(clip_widget)

    def set_max_duration(self, max_duration: float) -> None:
        self.canvas.set_max_duration(max_duration)

    def deselect_all(self) -> None:
        self.canvas.deselect_all()

    @pyqtSlot(float)
    def set_playhead_time(self, seconds: float) -> None:
        if not self.canvas.is_scrubbing:
            self.canvas.set_playhead_time(seconds)
            self._ensure_playhead_visible()

    def _ensure_playhead_visible(self) -> None:
        playhead_x = self.canvas.time_to_x(self.canvas.playhead_time)
        hbar = self.scroll_area.horizontalScrollBar()
        if not hbar:
            return

        viewport_width = self.scroll_area.viewport().width()
        current_scroll = hbar.value()
        margin = 60

        if playhead_x > current_scroll + viewport_width - margin:
            hbar.setValue(playhead_x - viewport_width + margin + 150)
        elif playhead_x < current_scroll + self.canvas.header_width:
            hbar.setValue(max(0, playhead_x - self.canvas.header_width - margin))