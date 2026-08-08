import numpy as np
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PlayerView(QWidget):
    """The video preview window and playback controls."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # The screen (Black rectangle placeholder)
        self.screen = QLabel("Video Preview")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setStyleSheet("background-color: black; color: white; font-size: 24px;")
        self.screen.setMinimumSize(640, 360)

        # Playback Controls
        controls_layout = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_play)
        controls_layout.addWidget(self.btn_pause)
        controls_layout.addStretch()

        layout.addWidget(self.screen)
        layout.addLayout(controls_layout)

    @pyqtSlot(np.ndarray)
    def update_frame(self, frame_data: np.ndarray) -> None:
        """
        Takes a raw RGB numpy array from the backend engine, converts it
        into a QImage and QPixmap, and renders it onto self.screen using
        Qt.AspectRatioMode.KeepAspectRatio and Qt.TransformationMode.SmoothTransformation.
        """
        if frame_data is None or frame_data.size == 0:
            return

        # Ensure memory buffer is C-contiguous
        if not frame_data.flags["C_CONTIGUOUS"]:
            frame_data = np.ascontiguousarray(frame_data)

        height, width, channels = frame_data.shape
        bytes_per_line = channels * width

        # Create QImage from raw RGB data
        q_image = QImage(
            frame_data.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )

        # Convert QImage to QPixmap
        pixmap = QPixmap.fromImage(q_image)

        # Scale to fit the preview screen while preserving crispness and original aspect ratio
        target_size = self.screen.size()
        if target_size.width() > 0 and target_size.height() > 0:
            scaled_pixmap = pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.screen.setPixmap(scaled_pixmap)
        else:
            self.screen.setPixmap(pixmap)