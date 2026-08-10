"""Dialog components for the MovieEditor application.

Contains modal dialogs including SetTimeDialog for editing clip in/out points.
Strictly adheres to docs/ai_agents/ui_developer.md.
"""

from typing import Optional, Tuple
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SetTimeDialog(QDialog):
    """Modal dialog allowing the user to precisely set in-point and out-point timestamps for a clip.

    Layout:
        - Top header with dialog title and descriptive subtitle.
        - Form container featuring two QDoubleSpinBoxes for start and end times in seconds.
        - Live duration preview badge showing resulting clip duration (end - start).
        - Inline validation banner to alert the user if end time is not greater than start time.
        - Bottom action button bar with 'Save & Apply' (primary) and 'Cancel' (secondary) buttons.
    """

    def __init__(
        self,
        start_time: float = 0.0,
        end_time: float = 0.0,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initializes the SetTimeDialog with existing in/out timestamps.

        Args:
            start_time (float): Current source start time in seconds (in-point). Defaults to 0.0.
            end_time (float): Current source end time in seconds (out-point). Defaults to 0.0.
            parent (Optional[QWidget]): Parent Qt widget for hierarchy and modality. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle("Set Clip Play Time")
        self.setFixedSize(420, 310)
        self.setModal(True)

        self._init_ui(start_time, end_time)

    def _init_ui(self, initial_start: float, initial_end: float) -> None:
        """Constructs and styles the dialog layout and interactive controls.

        Args:
            initial_start (float): Initial in-point timestamp in seconds.
            initial_end (float): Initial out-point timestamp in seconds.
        """
        self.setStyleSheet("""
            QDialog {
                background-color: #120e24;
                color: #f5f3ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #e9d5ff;
                font-size: 12px;
            }
            QLabel#DialogTitle {
                font-size: 15px;
                font-weight: bold;
                color: #f5f3ff;
            }
            QLabel#Subtitle {
                font-size: 11px;
                color: #a78bfa;
            }
            QLabel#ErrorLabel {
                color: #f87171;
                font-size: 11px;
                font-weight: bold;
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid #ef4444;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QDoubleSpinBox {
                background-color: #1a1436;
                color: #f5f3ff;
                border: 1px solid #36296b;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 13px;
                font-weight: 500;
            }
            QDoubleSpinBox:hover, QDoubleSpinBox:focus {
                border-color: #a855f7;
                background-color: #211947;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background-color: #2a2057;
                border: none;
                width: 18px;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #7c3aed;
            }
            QPushButton.primary-btn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:0.5 #9333ea, stop:1 #d946ef);
                color: #ffffff;
                border: 1px solid #c084fc;
                border-radius: 5px;
                padding: 8px 18px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton.primary-btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:0.5 #a855f7, stop:1 #e879f9);
                border-color: #f0abfc;
            }
            QPushButton.primary-btn:pressed {
                background-color: #581c87;
            }
            QPushButton.secondary-btn {
                background-color: #1a1436;
                color: #c4b5fd;
                border: 1px solid #36296b;
                border-radius: 5px;
                padding: 8px 14px;
                font-size: 12px;
            }
            QPushButton.secondary-btn:hover {
                background-color: #281d52;
                border-color: #7c3aed;
                color: #f5f3ff;
            }
            QFrame.panel {
                background-color: #16112e;
                border: 1px solid #2d2159;
                border-radius: 6px;
                padding: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header Title
        lbl_title = QLabel("⏱️ Set Clip Play Time")
        lbl_title.setObjectName("DialogTitle")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel("Manually specify exact source in-point and out-point timestamps.")
        lbl_sub.setObjectName("Subtitle")
        layout.addWidget(lbl_sub)

        # Form Container Panel
        panel = QFrame()
        panel.setProperty("class", "panel")
        form_layout = QFormLayout(panel)
        form_layout.setContentsMargins(12, 10, 12, 10)
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        # 1. Start Time (seconds)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(0.0, 999999.0)
        self.spin_start.setDecimals(2)
        self.spin_start.setSingleStep(0.1)
        self.spin_start.setSuffix(" s")
        self.spin_start.setValue(max(0.0, float(initial_start)))
        self.spin_start.valueChanged.connect(self._on_values_changed)
        form_layout.addRow("Start Time (seconds):", self.spin_start)

        # 2. End Time (seconds)
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setRange(0.0, 999999.0)
        self.spin_end.setDecimals(2)
        self.spin_end.setSingleStep(0.1)
        self.spin_end.setSuffix(" s")
        self.spin_end.setValue(max(0.0, float(initial_end)))
        self.spin_end.valueChanged.connect(self._on_values_changed)
        form_layout.addRow("End Time (seconds):", self.spin_end)

        # 3. Duration info preview
        self.lbl_duration_info = QLabel("")
        self.lbl_duration_info.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        form_layout.addRow("Resulting Duration:", self.lbl_duration_info)

        layout.addWidget(panel)

        # Validation error banner (hidden by default)
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("ErrorLabel")
        self.lbl_error.setVisible(False)
        layout.addWidget(self.lbl_error)

        layout.addStretch()

        # Action Buttons (OK / Cancel)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setProperty("class", "secondary-btn")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        btn_layout.addStretch()

        self.btn_ok = QPushButton("Save & Apply")
        self.btn_ok.setProperty("class", "primary-btn")
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ok)

        layout.addLayout(btn_layout)

        self._update_duration_preview()

    def _on_values_changed(self) -> None:
        """Invoked when start or end spinbox values change."""
        self._update_duration_preview()
        if self.lbl_error.isVisible():
            self.lbl_error.setVisible(False)

    def _update_duration_preview(self) -> None:
        """Calculates and refreshes the resulting duration label."""
        start = self.spin_start.value()
        end = self.spin_end.value()
        diff = end - start
        if diff > 0:
            self.lbl_duration_info.setText(f"{diff:.2f} seconds")
            self.lbl_duration_info.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        else:
            self.lbl_duration_info.setText("Invalid range (End <= Start)")
            self.lbl_duration_info.setStyleSheet("color: #f87171; font-weight: 600; font-size: 11px;")

    def get_times(self) -> Tuple[float, float]:
        """Returns the configured start and end timestamps.

        Returns:
            Tuple[float, float]: A tuple of (start_time, end_time) in seconds.
        """
        return (float(self.spin_start.value()), float(self.spin_end.value()))

    @property
    def start_time(self) -> float:
        """float: The selected in-point start time in seconds."""
        return float(self.spin_start.value())

    @property
    def end_time(self) -> float:
        """float: The selected out-point end time in seconds."""
        return float(self.spin_end.value())

    def accept(self) -> None:
        """Validates timestamp inputs before closing the dialog.

        If end_time is not strictly greater than start_time, shows an error banner
        and halts dialog acceptance.
        """
        start, end = self.get_times()
        if start < 0.0 or end < 0.0:
            self.lbl_error.setText("⚠️ Start and end times cannot be negative.")
            self.lbl_error.setVisible(True)
            return

        if end <= start:
            self.lbl_error.setText(f"⚠️ End time ({end:.2f}s) must be strictly greater than start time ({start:.2f}s).")
            self.lbl_error.setVisible(True)
            return

        self.lbl_error.setVisible(False)
        super().accept()
