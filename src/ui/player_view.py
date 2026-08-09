from typing import Any, Dict
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class PlayerView(QWidget):
    """The video preview screen, status metadata badge bar, and playback & audio control toolbar.

    Layout Structure:
    - QVBoxLayout (Root Layout)
      - QFrame#PreviewScreenContainer (AspectRatio-preserving QLabel preview screen)
      - QFrame#InfoBar (Active video title, master frame counter, timecode, and FPS badge)
      - QHBoxLayout#ControlsBar (Rewind, Step Back, Play/Pause toggle, Step Forward, Volume Slider, Mute Button)

    Strictly event-driven: emits custom PyQt signals upon user interaction and does not perform video decoding.
    """

    play_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    toggle_play_requested = pyqtSignal()
    step_forward_requested = pyqtSignal()
    step_backward_requested = pyqtSignal()
    rewind_requested = pyqtSignal()
    volume_changed = pyqtSignal(float)  # 0.0 to 1.0
    mute_toggled = pyqtSignal(bool)     # True if muted

    def __init__(self):
        super().__init__()
        self._is_playing = False
        self._is_muted = False
        self._last_volume = 1.0
        self._last_raw_pixmap: QPixmap | None = None

        self.setStyleSheet("""
            QWidget {
                background-color: #120e24;
                color: #f5f3ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QFrame#PreviewScreenContainer {
                background-color: #080612;
                border: 1px solid #2d2159;
                border-radius: 6px;
            }
            QLabel#ScreenLabel {
                background-color: transparent;
                color: #7c6f9f;
                font-size: 16px;
            }
            QFrame#InfoBar {
                background-color: #1a1436;
                border: 1px solid #36296b;
                border-radius: 5px;
                padding: 4px 8px;
            }
            QLabel#VideoTitleLabel {
                color: #c084fc;
                font-size: 13px;
                font-weight: bold;
            }
            QLabel#FrameCounterBadge {
                background-color: #2b1f54;
                color: #a78bfa;
                font-size: 12px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid #6d28d9;
            }
            QLabel#TimecodeBadge {
                background-color: #16102e;
                color: #00f5ff;
                font-family: 'Consolas', monospace;
                font-size: 13px;
                font-weight: bold;
                padding: 2px 8px;
                border-radius: 3px;
                border: 1px solid #7c3aed;
            }
            QLabel#FormatBadge {
                color: #9d8ec2;
                font-size: 11px;
            }
            QPushButton.control-btn {
                background-color: #201842;
                color: #e9d5ff;
                border: 1px solid #3b2d70;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: bold;
                min-width: 32px;
            }
            QPushButton.control-btn:hover {
                background-color: #312361;
                border-color: #8b5cf6;
                color: #ffffff;
            }
            QPushButton.control-btn:pressed {
                background-color: #16102e;
            }
            QPushButton#BtnPlayToggle {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #9333ea);
                color: #ffffff;
                border: 1px solid #a855f7;
                padding: 5px 18px;
                font-weight: bold;
            }
            QPushButton#BtnPlayToggle:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #a855f7);
                border-color: #d946ef;
            }
            QPushButton#BtnPlayToggle:pressed {
                background-color: #581c87;
            }
            QSlider::groove:horizontal {
                background: #201842;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #8b5cf6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #c084fc;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #f0abfc;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 1. Main Video Screen Container
        self.screen_container = QFrame()
        self.screen_container.setObjectName("PreviewScreenContainer")
        self.screen_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        screen_layout = QVBoxLayout(self.screen_container)
        screen_layout.setContentsMargins(2, 2, 2, 2)

        self.screen = QLabel("AI Video Preview")
        self.screen.setObjectName("ScreenLabel")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        screen_layout.addWidget(self.screen)

        layout.addWidget(self.screen_container, stretch=1)

        # 2. Frame & Video Name Status Info Bar
        self.info_bar = QFrame()
        self.info_bar.setObjectName("InfoBar")
        info_layout = QHBoxLayout(self.info_bar)
        info_layout.setContentsMargins(6, 2, 6, 2)
        info_layout.setSpacing(10)

        # Playing Video Name
        self.lbl_video_name = QLabel("🎬 No Video Playing")
        self.lbl_video_name.setObjectName("VideoTitleLabel")
        info_layout.addWidget(self.lbl_video_name)

        info_layout.addStretch()

        # Frames Counter Badge (under video name)
        self.lbl_frame_counter = QLabel("Frame: 0 / 0")
        self.lbl_frame_counter.setObjectName("FrameCounterBadge")
        self.lbl_frame_counter.setToolTip("Current frame number / total clip frames")
        info_layout.addWidget(self.lbl_frame_counter)

        # SMPTE Timecode Badge
        self.lbl_timecode = QLabel("00:00:00:00")
        self.lbl_timecode.setObjectName("TimecodeBadge")
        self.lbl_timecode.setToolTip("Current master timecode (HH:MM:SS:FF)")
        info_layout.addWidget(self.lbl_timecode)

        # FPS & Resolution Badge
        self.lbl_format = QLabel("30.0 FPS • 1080p")
        self.lbl_format.setObjectName("FormatBadge")
        info_layout.addWidget(self.lbl_format)

        layout.addWidget(self.info_bar)

        # 3. Playback & Audio Controls Bar
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 2, 0, 0)
        controls_layout.setSpacing(6)

        # Rewind Button (Home)
        self.btn_rewind = QPushButton("⏮")
        self.btn_rewind.setProperty("class", "control-btn")
        self.btn_rewind.setToolTip("Rewind to Start (Home)")
        self.btn_rewind.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rewind.clicked.connect(self.rewind_requested.emit)

        # Step Back Button
        self.btn_step_back = QPushButton("◀")
        self.btn_step_back.setProperty("class", "control-btn")
        self.btn_step_back.setToolTip("Previous Frame (Left Arrow)")
        self.btn_step_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_step_back.clicked.connect(self.step_backward_requested.emit)

        # Play / Pause Toggle Button
        self.btn_play_toggle = QPushButton("▶ Play")
        self.btn_play_toggle.setObjectName("BtnPlayToggle")
        self.btn_play_toggle.setToolTip("Play / Pause (Space)")
        self.btn_play_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_toggle.clicked.connect(self._on_play_toggle_clicked)

        # Backwards compatibility handles for MainWindow
        self.btn_play = QPushButton("Play")
        self.btn_play.setVisible(False)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setVisible(False)

        # Step Forward Button
        self.btn_step_fwd = QPushButton("▶")
        self.btn_step_fwd.setProperty("class", "control-btn")
        self.btn_step_fwd.setToolTip("Next Frame (Right Arrow)")
        self.btn_step_fwd.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_step_fwd.clicked.connect(self.step_forward_requested.emit)

        # Volume / Mute Controls
        self.btn_volume = QPushButton("🔊")
        self.btn_volume.setProperty("class", "control-btn")
        self.btn_volume.setToolTip("Mute / Unmute")
        self.btn_volume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volume.clicked.connect(self._toggle_mute)

        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(100)
        self.slider_volume.setFixedWidth(80)
        self.slider_volume.setToolTip("Volume")
        self.slider_volume.valueChanged.connect(self._on_volume_changed)

        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_rewind)
        controls_layout.addWidget(self.btn_step_back)
        controls_layout.addWidget(self.btn_play_toggle)
        controls_layout.addWidget(self.btn_step_fwd)
        controls_layout.addSpacing(16)
        controls_layout.addWidget(self.btn_volume)
        controls_layout.addWidget(self.slider_volume)
        controls_layout.addStretch()

        layout.addLayout(controls_layout)

    def _toggle_mute(self) -> None:
        """Toggles mute state."""
        self._is_muted = not self._is_muted
        if self._is_muted:
            self.btn_volume.setText("🔇")
            self.mute_toggled.emit(True)
        else:
            self.btn_volume.setText("🔊")
            self.mute_toggled.emit(False)

    def _on_volume_changed(self, value: int) -> None:
        """Emits normalized volume float [0.0, 1.0]."""
        vol = max(0.0, min(1.0, value / 100.0))
        if self._is_muted and vol > 0:
            self._is_muted = False
            self.btn_volume.setText("🔊")
            self.mute_toggled.emit(False)
        self.volume_changed.emit(vol)


    def _on_play_toggle_clicked(self) -> None:
        """Emits toggle request signal."""
        self.toggle_play_requested.emit()

    def set_playing_state(self, is_playing: bool) -> None:
        """Updates the visual state of the Play/Pause button."""
        self._is_playing = is_playing
        if is_playing:
            self.btn_play_toggle.setText("⏸ Pause")
            self.btn_play_toggle.setStyleSheet("background-color: #d9383a; border-color: #f85149;")
        else:
            self.btn_play_toggle.setText("▶ Play")
            self.btn_play_toggle.setStyleSheet("")

    @pyqtSlot(dict)
    def update_status(self, status: Dict[str, Any]) -> None:
        """Updates the status badges displaying video name, frames, and timecode."""
        if not status:
            return

        curr_frame = status.get("current_frame", 1)
        tot_frames = status.get("total_frames", 1)
        self.lbl_frame_counter.setText(f"Frame: {curr_frame:04d} / {tot_frames:04d}")

        if status.get("has_active_clip", False):
            clip_name = status.get("clip_name", "Active Clip")
            track_name = status.get("track_name", "Track")
            clip_frame = status.get("clip_frame", 1)
            tot_clip = status.get("total_clip_frames", 1)
            self.lbl_video_name.setText(f"🎬 {clip_name} ({track_name})")
            self.lbl_video_name.setToolTip(f"File: {status.get('file_path', '')}\nClip Frame: {clip_frame} / {tot_clip}")
        else:
            self.lbl_video_name.setText("🎬 No Active Clip")
            self.lbl_video_name.setToolTip("Timeline gap - No clip active")

        timecode = status.get("timecode", "00:00:00:00")
        self.lbl_timecode.setText(timecode)

        fps = status.get("fps", 30.0)
        res = status.get("resolution", (1920, 1080))
        res_text = f"{res[1]}p" if len(res) >= 2 else "1080p"
        self.lbl_format.setText(f"{fps:.1f} FPS • {res_text}")

    @pyqtSlot(np.ndarray)
    def update_frame(self, frame_data: np.ndarray) -> None:
        """
        Renders a raw RGB numpy array onto the preview screen keeping aspect ratio.
        """
        if frame_data is None or frame_data.size == 0:
            return

        if not frame_data.flags["C_CONTIGUOUS"]:
            frame_data = np.ascontiguousarray(frame_data)

        height, width, channels = frame_data.shape
        bytes_per_line = channels * width

        q_image = QImage(
            frame_data.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )

        pixmap = QPixmap.fromImage(q_image)
        self._last_raw_pixmap = pixmap
        self._render_scaled_pixmap()

    def _render_scaled_pixmap(self) -> None:
        """Scales and centers pixmap in the screen widget."""
        if self._last_raw_pixmap is None or self._last_raw_pixmap.isNull():
            return

        screen_size = self.screen.size()
        if screen_size.width() > 10 and screen_size.height() > 10:
            scaled = self._last_raw_pixmap.scaled(
                screen_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.screen.setPixmap(scaled)
        else:
            self.screen.setPixmap(self._last_raw_pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_scaled_pixmap()