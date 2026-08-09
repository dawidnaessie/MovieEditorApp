"""Production Multi-Track Timeline Canvas and View with Dynamic Zoom and Interactive Multi-Track Clip Moving.

Features:
- Track headers rendered on solid QFrames with explicit badges, preventing text clipping.
- Click-and-drag clip repositioning both horizontally (time) and vertically between tracks (e.g. Video 1 <-> Video 2).
- Playhead indicator scrubbing strictly restricted to the top ruler arrowhead bar.
- Dynamic timeline zooming (Ctrl + Wheel / Touchpad pinch, toolbar slider, zoom in/out, fit to screen).
- Adaptive ruler tick intervals based on zoom level (seconds, minutes, or frame divisions).
- Razor scissors cutting tool and interactive edge trimming.
- Non-blocking filmstrip thumbnail caching and 60 FPS playhead synchronization.
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
    QWheelEvent,
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

# Standard timeline constants
TRACK_HEADER_WIDTH: int = 130
DEFAULT_PIXELS_PER_SECOND: float = 25.0
MIN_PIXELS_PER_SECOND: float = 2.0
MAX_PIXELS_PER_SECOND: float = 150.0
PIXELS_PER_SECOND: float = DEFAULT_PIXELS_PER_SECOND
DEFAULT_CLIP_DURATION: float = 10.0


def time_to_pixel(
    seconds: float,
    header_width: int = TRACK_HEADER_WIDTH,
    pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
) -> int:
    """Converts a timeline timestamp in seconds into a local canvas pixel X coordinate."""
    return int(header_width + (max(0.0, float(seconds)) * pixels_per_second))


def pixel_to_time(
    x: int,
    header_width: int = TRACK_HEADER_WIDTH,
    pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
    max_duration: float = 0.0,
) -> float:
    """Converts a local canvas pixel X coordinate into timeline seconds clamped to [0.0, max_duration]."""
    raw_seconds = max(0.0, (float(x) - float(header_width)) / max(0.1, pixels_per_second))
    if max_duration > 0:
        return min(raw_seconds, float(max_duration))
    return raw_seconds


def calculate_clip_pixel_width(
    duration: float,
    pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
    min_width: int = 20,
) -> int:
    """Calculates the visual pixel width for a clip given its duration in seconds."""
    return max(min_width, int(max(0.0, float(duration)) * pixels_per_second))


class ClipWidget(QWidget):
    """A professional NLE clip block with title, filmstrip thumbnails, cross-track moving, razor cutting, and edge trimming."""

    clip_selected = pyqtSignal(object)  # Emits self (ClipWidget)
    delete_requested = pyqtSignal(object)  # Emits self (ClipWidget)
    split_requested = pyqtSignal(str, float)  # (clip_id, global_split_time)
    trim_requested = pyqtSignal(object, float, bool)  # (self, new_val, is_left)
    clip_moved = pyqtSignal(object, float, int)  # (self, new_timeline_position, target_track_index)

    def __init__(
        self,
        clip_name: str,
        file_path: str,
        timeline_position: float = 0.0,
        duration: float = DEFAULT_CLIP_DURATION,
        track_index: int = 0,
        pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
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

        # Drag-to-move state
        self._is_moving: bool = False
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0
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

        # Main Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(1)

        # Header Bar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 1, 2, 1)
        header_layout.setSpacing(4)

        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        available_width = max(20, width - 40)
        elided_title = metrics.elidedText(clip_name, Qt.TextElideMode.ElideRight, available_width)

        self.lbl_title = QLabel(f"🎞️ {elided_title}")
        self.lbl_title.setFont(font)
        self.lbl_title.setStyleSheet("color: #f5f3ff; font-weight: bold; background: transparent; border: none;")
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        self.lbl_dur = QLabel(f"{self.duration:.1f}s")
        self.lbl_dur.setFont(QFont("Segoe UI", 7))
        self.lbl_dur.setStyleSheet("color: #e9d5ff; background: rgba(18, 14, 36, 0.6); border: 1px solid #6d28d9; border-radius: 2px; padding: 1px 3px;")
        self.lbl_dur.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(self.lbl_dur)

        layout.addLayout(header_layout)
        layout.addStretch(1)

        self.setToolTip(f"🎬 {clip_name}\nTrack: {track_index + 1}\nDuration: {self.duration:.2f}s\n[Drag across time or tracks, Drag edge to trim, Razor (C) to cut]")
        self.show()

    def _find_timeline_canvas(self) -> Optional["TimelineCanvas"]:
        """Finds the parent TimelineCanvas widget in the hierarchy."""
        parent = self.parent()
        while parent:
            if isinstance(parent, TimelineCanvas) or parent.__class__.__name__ == "TimelineCanvas":
                return parent
            parent = parent.parent()
        win = self.window()
        if win and hasattr(win, "timeline_view") and hasattr(win.timeline_view, "canvas"):
            return win.timeline_view.canvas
        return None

    def update_zoom(self, pixels_per_second: float) -> None:
        """Recalculates X position and pixel width when timeline zoom level changes."""
        self.pixels_per_second = max(MIN_PIXELS_PER_SECOND, pixels_per_second)
        new_x = int(self.timeline_position * self.pixels_per_second)
        new_w = calculate_clip_pixel_width(self.duration, self.pixels_per_second)
        self.setGeometry(new_x, self.y(), new_w, self.height())

        # Update elided title text
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        available_width = max(10, new_w - 40)
        elided_title = metrics.elidedText(self.clip_name, Qt.TextElideMode.ElideRight, available_width)
        self.lbl_title.setText(f"🎞️ {elided_title}" if new_w > 50 else elided_title)
        self.lbl_dur.setVisible(new_w > 45)
        self.update()

    def set_active_tool(self, tool_name: str) -> None:
        """Updates the active tool mode for this clip widget."""
        self.active_tool = tool_name
        if tool_name == "razor":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _update_style(self) -> None:
        """Updates CSS border based on selection state."""
        if self.is_selected:
            self.setStyleSheet("""
                QWidget#ClipWidget {
                    background-color: #3d216d;
                    border: 2px solid #d946ef;
                    border-radius: 5px;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget#ClipWidget {
                    background-color: #281d52;
                    border: 1px solid #7c3aed;
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

            # 3. Drag-to-Move Initiation (Body click)
            self._is_moving = True
            self._drag_start_x = event.globalPosition().x()
            self._drag_start_y = event.globalPosition().y()
            self._orig_x = self.x()
            self._orig_pos = self.timeline_position
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.set_selected(True)
            self.clip_selected.emit(self)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # 1. Drag-to-Move in Progress
        if self._is_moving:
            dx = event.globalPosition().x() - self._drag_start_x
            new_x = max(0, int(self._orig_x + dx))
            new_pos = max(0.0, self._orig_pos + (dx / self.pixels_per_second))
            self.move(new_x, self.y())

            # Identify target track name based on vertical cursor position
            target_track_name = f"Track {self.track_index + 1}"
            canvas = self._find_timeline_canvas()
            if canvas:
                target_idx = canvas.get_track_index_at_global_y(int(event.globalPosition().y()))
                if target_idx is not None and 0 <= target_idx < len(canvas.track_strips):
                    target_track_name = canvas.track_strips[target_idx].track_name

            self.setToolTip(f"🎬 {self.clip_name}\nTarget: {target_track_name}\nPosition: {new_pos:.2f}s (Duration: {self.duration:.2f}s)")
            event.accept()
            return

        # 2. Edge Trimming in Progress
        if self._trim_mode == "right":
            dx = event.globalPosition().x() - self._drag_start_x
            new_w = max(15, int(self._orig_w + dx))
            new_dur = max(0.2, new_w / self.pixels_per_second)
            self.resize(new_w, self.height())
            speed = (self._orig_dur / new_dur) if (new_dur > 0 and self._orig_dur > 0) else 1.0
            if abs(speed - 1.0) >= 0.05:
                self.lbl_dur.setText(f"{new_dur:.1f}s ({speed:.2f}x)")
            else:
                self.lbl_dur.setText(f"{new_dur:.1f}s")
            event.accept()
            return
        elif self._trim_mode == "left":
            dx = event.globalPosition().x() - self._drag_start_x
            max_dx = self._orig_w - 15
            clamped_dx = max(-self._orig_x, min(dx, max_dx))
            new_x = int(self._orig_x + clamped_dx)
            new_w = int(self._orig_w - clamped_dx)
            new_dur = max(0.2, new_w / self.pixels_per_second)
            self.move(new_x, self.y())
            self.resize(new_w, self.height())
            self.lbl_dur.setText(f"{new_dur:.1f}s")
            event.accept()
            return

        # 3. Hover Cursor Updates
        if self.active_tool == "razor":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.active_tool == "select":
            x = event.position().x()
            if x <= 8 or x >= self.width() - 8:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # 1. Complete Drag-to-Move
            if self._is_moving:
                dx = event.globalPosition().x() - self._drag_start_x
                new_pos = max(0.0, self._orig_pos + (dx / self.pixels_per_second))
                self.timeline_position = new_pos
                new_x = int(new_pos * self.pixels_per_second)
                self.move(new_x, self.y())

                # Find destination track index
                target_track_index = self.track_index
                canvas = self._find_timeline_canvas()
                if canvas:
                    target_idx = canvas.get_track_index_at_global_y(int(event.globalPosition().y()))
                    if target_idx is not None and 0 <= target_idx < len(canvas.track_strips):
                        target_track_index = target_idx

                self._is_moving = False
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.clip_moved.emit(self, new_pos, target_track_index)
                event.accept()
                return

            # 2. Complete Trimming
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
                background-color: #1a1436;
                color: #f5f3ff;
                border: 1px solid #3b2d70;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #7c3aed;
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
        """Paints the background and horizontal thumbnail filmstrip frames."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()
        filmstrip_y = 20
        filmstrip_h = max(10, height - filmstrip_y - 2)

        filmstrip_rect = QRect(2, filmstrip_y, width - 4, filmstrip_h)
        painter.fillRect(filmstrip_rect, QColor("#0f0b21"))

        if self._thumbnails and width > 30:
            total_thumbs = len(self._thumbnails)
            thumb_w = max(20, int(filmstrip_h * (16 / 9)))
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
            painter.setPen(QPen(QColor("#3b2d70"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(filmstrip_rect.adjusted(1, 1, -1, -1))
            if width > 60:
                painter.setFont(QFont("Segoe UI", 7))
                painter.setPen(QColor("#a78bfa"))
                painter.drawText(filmstrip_rect, Qt.AlignmentFlag.AlignCenter, "Loading Frames...")


class TrackLaneWidget(QWidget):
    """The droppable canvas lane of a single track where clips are placed."""

    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)
    clip_moved = pyqtSignal(object, float, int)

    def __init__(self, track_index: int, pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND):
        super().__init__()
        self.track_index = track_index
        self.pixels_per_second = pixels_per_second
        self.active_tool = "select"
        self.setAcceptDrops(True)
        self.clip_widgets: list[ClipWidget] = []
        self.setStyleSheet("""
            TrackLaneWidget {
                background-color: #191433;
                border-bottom: 1px solid #271f4d;
            }
        """)

    def set_zoom(self, pixels_per_second: float) -> None:
        """Updates zoom level on this lane and all contained clip widgets."""
        self.pixels_per_second = pixels_per_second
        for cw in self.clip_widgets:
            cw.update_zoom(pixels_per_second)

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
        clip_widget.split_requested.connect(self.split_requested.emit)
        clip_widget.trim_requested.connect(self.trim_requested.emit)
        clip_widget.clip_moved.connect(self.clip_moved.emit)
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


class TrackHeaderWidget(QFrame):
    """Solid, non-transparent track header frame preventing any clipping or background bleeding."""

    def __init__(self, track_name: str, track_index: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedWidth(TRACK_HEADER_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("TrackHeaderWidget")

        is_audio = "audio" in track_name.lower()
        badge_bg = "#26164d" if not is_audio else "#35143a"
        badge_color = "#c084fc" if not is_audio else "#f472b6"
        badge_border = "#6d28d9" if not is_audio else "#9d174d"
        icon = "🔊" if is_audio else "🎬"

        self.setStyleSheet(f"""
            QFrame#TrackHeaderWidget {{
                background-color: #140f29;
                border-right: 2px solid #3b2d70;
                border-bottom: 1px solid #271f4d;
            }}
            QFrame.badge-pill {{
                background-color: {badge_bg};
                border: 1px solid {badge_border};
                border-radius: 4px;
                padding: 3px 6px;
            }}
            QLabel.track-title {{
                color: #f5f3ff;
                font-weight: bold;
                font-size: 11px;
            }}
            QLabel.track-tag {{
                color: {badge_color};
                font-size: 9px;
                font-weight: 600;
            }}
        """)

        h_layout = QHBoxLayout(self)
        h_layout.setContentsMargins(8, 6, 8, 6)
        h_layout.setSpacing(6)

        # Track badge container
        badge = QFrame()
        badge.setProperty("class", "badge-pill")
        b_layout = QHBoxLayout(badge)
        b_layout.setContentsMargins(4, 2, 4, 2)
        b_layout.setSpacing(4)

        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 12px; background: transparent;")
        b_layout.addWidget(lbl_icon)

        lbl_name = QLabel(track_name)
        lbl_name.setProperty("class", "track-title")
        lbl_name.setStyleSheet("background: transparent;")
        b_layout.addWidget(lbl_name)

        h_layout.addWidget(badge)
        h_layout.addStretch()


class TrackStripWidget(QWidget):
    """A single horizontal track strip containing the solid header and droppable lane."""

    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)
    clip_moved = pyqtSignal(object, float, int)

    def __init__(
        self,
        track_name: str,
        track_index: int = 0,
        pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
        height: int = 64,
    ):
        super().__init__()
        self.track_name = track_name
        self.track_index = track_index
        self.pixels_per_second = pixels_per_second
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Solid Track Header (prevents any clipping or transparency issues)
        self.header = TrackHeaderWidget(track_name=track_name, track_index=track_index, parent=self)
        layout.addWidget(self.header)

        # 2. Droppable Track Lane
        self.lane = TrackLaneWidget(track_index=track_index, pixels_per_second=pixels_per_second)
        self.lane.clip_dropped.connect(self.clip_dropped.emit)
        self.lane.clip_selected.connect(self.clip_selected.emit)
        self.lane.clip_delete_requested.connect(self.clip_delete_requested.emit)
        self.lane.split_requested.connect(self.split_requested.emit)
        self.lane.trim_requested.connect(self.trim_requested.emit)
        self.lane.clip_moved.connect(self.clip_moved.emit)
        layout.addWidget(self.lane, stretch=1)

    def set_zoom(self, pixels_per_second: float) -> None:
        """Updates zoom level on child lane."""
        self.pixels_per_second = pixels_per_second
        self.lane.set_zoom(pixels_per_second)


class PlayheadOverlay(QWidget):
    """Glowing neon magenta/violet vertical needle playhead overlay."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(18)
        self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        height = self.height()
        needle_color = QColor("#d946ef")
        glow_color = QColor(217, 70, 239, 80)
        center_x = 9

        painter.setPen(QPen(glow_color, 4))
        painter.drawLine(center_x, 0, center_x, height)

        painter.setPen(QPen(needle_color, 2))
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
        painter.setBrush(QBrush(needle_color))
        painter.setPen(QPen(QColor("#f0abfc"), 1))
        painter.drawPolygon(head_poly)


class TimelineCanvas(QWidget):
    """The interactive multi-track canvas with time ruler, clamped playhead, and dynamic zooming."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)
    clip_moved = pyqtSignal(object, float, int)
    zoom_changed = pyqtSignal(float)

    def __init__(
        self,
        pixels_per_second: float = DEFAULT_PIXELS_PER_SECOND,
        header_width: int = TRACK_HEADER_WIDTH,
    ):
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

        # 2. Tracks Container
        self.tracks_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.tracks_container)
        self.tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_layout.setSpacing(2)
        self.main_layout.addWidget(self.tracks_container)
        self.main_layout.addStretch()

        # 3. Playhead Overlay
        self.playhead = PlayheadOverlay(self)
        self._reposition_playhead()

    def get_track_index_at_global_y(self, global_y: int) -> Optional[int]:
        """Calculates which track strip is located at the given global Y coordinate."""
        for idx, strip in enumerate(self.track_strips):
            top_y = strip.mapToGlobal(QPoint(0, 0)).y()
            bottom_y = top_y + strip.height()
            if top_y <= global_y <= bottom_y:
                return idx
        if self.track_strips:
            first_top = self.track_strips[0].mapToGlobal(QPoint(0, 0)).y()
            last_bottom = self.track_strips[-1].mapToGlobal(QPoint(0, 0)).y() + self.track_strips[-1].height()
            if global_y < first_top:
                return 0
            if global_y > last_bottom:
                return len(self.track_strips) - 1
        return None

    def set_zoom_level(self, pixels_per_second: float) -> None:
        """Dynamically scales timeline zoom level and rescales all track clips."""
        clamped_pps = max(MIN_PIXELS_PER_SECOND, min(MAX_PIXELS_PER_SECOND, float(pixels_per_second)))
        if abs(clamped_pps - self.pixels_per_second) < 0.01:
            return

        self.pixels_per_second = clamped_pps

        for strip in self.track_strips:
            strip.set_zoom(self.pixels_per_second)

        # Recalculate minimum canvas width
        required_w = int(self.header_width + max(self.max_duration, 60.0) * self.pixels_per_second + 300)
        self.setMinimumWidth(max(800, required_w))
        self.updateGeometry()

        self._reposition_playhead()
        self.update()
        self.zoom_changed.emit(self.pixels_per_second)

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
        required_w = int(self.header_width + max(self.max_duration, 60.0) * self.pixels_per_second + 300)
        self.setMinimumWidth(max(800, required_w))
        self.updateGeometry()
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
        strip.split_requested.connect(self.split_requested.emit)
        strip.trim_requested.connect(self.trim_requested.emit)
        strip.clip_moved.connect(self.clip_moved.emit)
        strip.lane.set_active_tool(self.active_tool)

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
        raw_time = (clamped_x - self.header_width) / max(0.1, self.pixels_per_second)
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
        """Renders time ruler background and adaptive ticks matching the zoom level."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = self.width()
        height = self.height()

        # 1. Ruler Background (Deep Midnight Violet)
        painter.fillRect(0, 0, width, self.ruler_height, QColor("#100d22"))
        painter.fillRect(0, 0, self.header_width, self.ruler_height, QColor("#140f29"))
        painter.setPen(QPen(QColor("#2e255e"), 1))
        painter.drawLine(0, self.ruler_height - 1, width, self.ruler_height - 1)
        painter.drawLine(self.header_width, 0, self.header_width, height)

        # 2. Adaptive Tick Interval based on zoom level (pixels_per_second)
        pps = self.pixels_per_second
        if pps <= 3.0:
            major_interval = 120  # 2 mins
            minor_interval = 30
        elif pps <= 8.0:
            major_interval = 60   # 1 min
            minor_interval = 15
        elif pps <= 18.0:
            major_interval = 15
            minor_interval = 5
        elif pps <= 40.0:
            major_interval = 5
            minor_interval = 1
        elif pps <= 80.0:
            major_interval = 2
            minor_interval = 1
        else:
            major_interval = 1
            minor_interval = 1

        painter.setFont(QFont("Segoe UI", 8))
        total_secs = int(math.ceil((width - self.header_width) / max(0.1, pps)))

        for sec in range(0, total_secs + 1):
            if sec % minor_interval != 0 and sec % major_interval != 0:
                continue

            x = self.time_to_x(sec)
            if x > width:
                break

            if sec % major_interval == 0:
                painter.setPen(QPen(QColor("#7c6f9f"), 1))
                painter.drawLine(x, self.ruler_height - 12, x, self.ruler_height - 1)

                mins = sec // 60
                secs = sec % 60
                time_str = f"{mins:02d}:{secs:02d}"
                painter.setPen(QColor("#00f5ff" if sec == 0 else "#c084fc"))
                painter.drawText(x + 4, self.ruler_height - 6, time_str)
            else:
                painter.setPen(QPen(QColor("#3b2d70"), 1))
                painter.drawLine(x, self.ruler_height - 6, x, self.ruler_height - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # ONLY allow playhead scrubbing if clicking in the top ruler / arrowhead bar
            if event.position().y() <= self.ruler_height:
                self.deselect_all()
                self.is_scrubbing = True
                self.scrub_started.emit()
                target_time = self.x_to_time(int(event.position().x()))
                self.playhead_time = target_time
                self._reposition_playhead()
                self.seek_requested.emit(target_time)
            else:
                self.deselect_all()

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
    """The multi-track timeline container with embedded toolbar, dynamic zoom, and scroll area."""

    seek_requested = pyqtSignal(float)
    scrub_started = pyqtSignal()
    clip_dropped = pyqtSignal(str, int, float)
    clip_selected = pyqtSignal(object)
    clip_delete_requested = pyqtSignal(object)
    split_requested = pyqtSignal(str, float)
    trim_requested = pyqtSignal(object, float, bool)
    clip_moved = pyqtSignal(object, float, int)
    split_at_playhead_requested = pyqtSignal()
    tool_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top Toolbar with Editing Tools & Zoom Controls
        self.toolbar = ToolbarView(self)
        self.toolbar.tool_changed.connect(self._on_tool_changed)
        self.toolbar.split_at_playhead_requested.connect(self.split_at_playhead_requested.emit)
        self.toolbar.delete_requested.connect(self._on_toolbar_delete_requested)
        self.toolbar.zoom_changed.connect(self.set_zoom_level)
        self.toolbar.zoom_fit_requested.connect(self.zoom_fit_to_screen)
        layout.addWidget(self.toolbar)

        # 2. Scroll Area containing Canvas
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #0c0a17;
                border: 1px solid #2d2159;
            }
            QScrollBar:horizontal {
                background-color: #0c0a17;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background-color: #312361;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #7c3aed;
            }
            QScrollBar:vertical {
                background-color: #0c0a17;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background-color: #312361;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #7c3aed;
            }
        """)

        self.canvas = TimelineCanvas(pixels_per_second=DEFAULT_PIXELS_PER_SECOND)
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
        self.canvas.clip_moved.connect(self.clip_moved.emit)
        self.canvas.zoom_changed.connect(self.toolbar.set_zoom_value)

        # Default track strips
        self.canvas.add_track_strip("Video 1")
        self.canvas.add_track_strip("Video 2")
        self.canvas.add_track_strip("Audio 1")

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handles Ctrl + Wheel or touchpad pinch to zoom the timeline smoothly."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                zoom_factor = 1.15 if delta > 0 else (1.0 / 1.15)
                current_pps = self.canvas.pixels_per_second
                new_pps = current_pps * zoom_factor
                self.set_zoom_level(new_pps)
                event.accept()
                return
        super().wheelEvent(event)

    def set_zoom_level(self, pixels_per_second: float) -> None:
        """Sets zoom level and keeps playhead in viewport."""
        self.canvas.set_zoom_level(pixels_per_second)
        self._ensure_playhead_visible()

    def zoom_in(self) -> None:
        """Zooms in timeline by one step."""
        self.set_zoom_level(self.canvas.pixels_per_second * 1.25)

    def zoom_out(self) -> None:
        """Zooms out timeline by one step."""
        self.set_zoom_level(self.canvas.pixels_per_second * 0.8)

    def zoom_fit_to_screen(self) -> None:
        """Automatically scales timeline zoom so the entire video project fits on screen."""
        max_dur = self.canvas.max_duration
        if max_dur > 0.5:
            viewport_w = self.scroll_area.viewport().width()
            available_w = max(200, viewport_w - self.canvas.header_width - 80)
            fit_pps = max(MIN_PIXELS_PER_SECOND, min(MAX_PIXELS_PER_SECOND, available_w / max_dur))
            self.set_zoom_level(fit_pps)

    def _on_tool_changed(self, tool_name: str) -> None:
        self.canvas.set_active_tool(tool_name)
        self.tool_changed.emit(tool_name)

    def set_active_tool(self, tool_name: str) -> None:
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