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
                background-color: #18181b;
                color: #e4e4e7;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton.tool-btn {
                background-color: #212124;
                color: #d4d4d8;
                border: 1px solid #333338;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton.tool-btn:hover {
                background-color: #2a2a2f;
                color: #ffffff;
                border-color: #3f3f46;
            }
            QPushButton.tool-btn:checked {
                background-color: #0c4a6e;
                color: #38bdf8;
                border: 1px solid #0284c7;
            }
            QPushButton.action-btn {
                background-color: #212124;
                color: #d4d4d8;
                border: 1px solid #333338;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton.action-btn:hover {
                background-color: #27272a;
                color: #ffffff;
                border-color: #52525b;
            }
            QPushButton.action-btn:pressed {
                background-color: #18181b;
            }
            QFrame.v-sep {
                background-color: #2d2d32;
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
