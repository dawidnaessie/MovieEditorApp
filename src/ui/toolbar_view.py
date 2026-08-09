"""CapCut-inspired Editing Toolbar component for the timeline.

Provides tool selection modes (Selection [V], Razor/Blade [C]),
split at playhead action (Scissors [Ctrl+B]), and clip deletion [Del].
Conforms strictly to docs/ai_agents/ui_developer.md.
"""

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class ToolbarView(QWidget):
    """Toolbar above the timeline containing editing tools and action shortcuts.

    Layout Structure:
    - QHBoxLayout
      - Mode Button Group:
        - Selection Tool [V] (btn_select)
        - Razor/Blade Tool [C] (btn_razor)
      - Separator line
      - Action Buttons:
        - Split at Playhead [Ctrl+B] (btn_split)
        - Delete Selected [Del] (btn_delete)
    """

    tool_changed = pyqtSignal(str)  # "select" or "razor"
    split_at_playhead_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.active_tool = "select"
        self.setFixedHeight(38)

        self.setStyleSheet("""
            QWidget {
                background-color: #120e24;
                color: #f5f3ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton.tool-btn {
                background-color: #1a1436;
                color: #c4b5fd;
                border: 1px solid #36296b;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton.tool-btn:hover {
                background-color: #261e4d;
                color: #ffffff;
                border-color: #8b5cf6;
            }
            QPushButton.tool-btn:checked {
                background-color: #4c1d95;
                color: #f0abfc;
                border: 1px solid #c084fc;
            }
            QPushButton.action-btn {
                background-color: #1a1436;
                color: #c4b5fd;
                border: 1px solid #36296b;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton.action-btn:hover {
                background-color: #261e4d;
                color: #ffffff;
                border-color: #8b5cf6;
            }
            QPushButton.action-btn:pressed {
                background-color: #120e24;
            }
            QFrame.v-sep {
                background-color: #2e255e;
                max-width: 1px;
                margin: 4px 6px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(6)

        # 1. Mode Tool Buttons (Exclusive Checkable Group)
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_select = QPushButton("↖ Select (V)")
        self.btn_select.setProperty("class", "tool-btn")
        self.btn_select.setCheckable(True)
        self.btn_select.setChecked(True)
        self.btn_select.setToolTip("Pointer / Selection Tool (V)")
        self.btn_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_group.addButton(self.btn_select)
        layout.addWidget(self.btn_select)

        self.btn_razor = QPushButton("✂ Razor (C)")
        self.btn_razor.setProperty("class", "tool-btn")
        self.btn_razor.setCheckable(True)
        self.btn_razor.setToolTip("Razor / Blade Cutting Tool (C)")
        self.btn_razor.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_group.addButton(self.btn_razor)
        layout.addWidget(self.btn_razor)

        self.btn_select.clicked.connect(lambda: self._set_tool("select"))
        self.btn_razor.clicked.connect(lambda: self._set_tool("razor"))

        # Separator
        sep = QFrame()
        sep.setProperty("class", "v-sep")
        sep.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(sep)

        # 2. Quick Action Buttons
        self.btn_split = QPushButton("✂ Split at Playhead")
        self.btn_split.setProperty("class", "action-btn")
        self.btn_split.setToolTip("Split Active / Selected Clip at Playhead (Ctrl+B)")
        self.btn_split.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_split.clicked.connect(self.split_at_playhead_requested.emit)
        layout.addWidget(self.btn_split)

        self.btn_delete = QPushButton("🗑 Delete")
        self.btn_delete.setProperty("class", "action-btn")
        self.btn_delete.setToolTip("Delete Selected Clip (Del)")
        self.btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_requested.emit)
        layout.addWidget(self.btn_delete)

        layout.addStretch()

        # 3. Timeline Zoom Controls (Zoom Out, Slider, Zoom In, Fit)
        sep2 = QFrame()
        sep2.setProperty("class", "v-sep")
        sep2.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(sep2)

        self.btn_zoom_fit = QPushButton("⛶ Fit")
        self.btn_zoom_fit.setProperty("class", "action-btn")
        self.btn_zoom_fit.setToolTip("Fit Whole Timeline in Viewport (Shift+Z / Ctrl+0)")
        self.btn_zoom_fit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zoom_fit.clicked.connect(self.zoom_fit_requested.emit)
        layout.addWidget(self.btn_zoom_fit)

        self.btn_zoom_out = QPushButton("🔍 -")
        self.btn_zoom_out.setProperty("class", "action-btn")
        self.btn_zoom_out.setToolTip("Zoom Out Timeline (Ctrl + - / Ctrl+Scroll)")
        self.btn_zoom_out.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zoom_out.clicked.connect(self._on_zoom_out_clicked)
        layout.addWidget(self.btn_zoom_out)

        from PyQt6.QtWidgets import QSlider
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(2, 100)
        self.zoom_slider.setValue(25)
        self.zoom_slider.setFixedWidth(90)
        self.zoom_slider.setToolTip("Timeline Zoom: Ctrl+Wheel or drag slider")
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #1a1436;
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
        self.zoom_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.zoom_slider)

        self.btn_zoom_in = QPushButton("🔍 +")
        self.btn_zoom_in.setProperty("class", "action-btn")
        self.btn_zoom_in.setToolTip("Zoom In Timeline (Ctrl + + / Ctrl+Scroll)")
        self.btn_zoom_in.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zoom_in.clicked.connect(self._on_zoom_in_clicked)
        layout.addWidget(self.btn_zoom_in)

    zoom_changed = pyqtSignal(float)
    zoom_fit_requested = pyqtSignal()

    def _on_slider_changed(self, value: int) -> None:
        self.zoom_changed.emit(float(value))

    def _on_zoom_out_clicked(self) -> None:
        new_val = max(2, int(self.zoom_slider.value() * 0.75))
        self.zoom_slider.setValue(new_val)

    def _on_zoom_in_clicked(self) -> None:
        new_val = min(100, int(self.zoom_slider.value() * 1.35) + 1)
        self.zoom_slider.setValue(new_val)

    def set_zoom_value(self, pps: float) -> None:
        """Updates slider position without re-triggering feedback loop."""
        val = max(2, min(100, int(round(pps))))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(val)
        self.zoom_slider.blockSignals(False)

    def _set_tool(self, tool_name: str) -> None:
        """Updates the active tool mode and emits tool_changed signal."""
        if tool_name != self.active_tool:
            self.active_tool = tool_name
            if tool_name == "select":
                self.btn_select.setChecked(True)
            elif tool_name == "razor":
                self.btn_razor.setChecked(True)
            self.tool_changed.emit(tool_name)

    def set_active_tool(self, tool_name: str) -> None:
        """Programmatically switches the active tool (e.g. from keyboard shortcuts V or C)."""
        self._set_tool(tool_name)
