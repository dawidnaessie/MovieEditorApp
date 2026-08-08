import os
from PyQt6.QtCore import QMimeData, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DraggableMediaListWidget(QListWidget):
    """A QListWidget that supports dragging media files to the timeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Packages the selected media item's file path into QMimeData for dragging."""
        item = self.currentItem()
        if not item:
            return

        file_path = item.data(Qt.ItemDataRole.UserRole)
        if not file_path:
            return

        mime_data = QMimeData()
        mime_data.setText(file_path)
        mime_data.setUrls([QUrl.fromLocalFile(file_path)])

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)


class MediaPoolView(QWidget):
    """The media asset library / pool displaying imported media files."""

    # Signal emitted when one or more media files are successfully imported
    media_imported = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget {
                background-color: #252526;
                color: #cccccc;
            }
            QLabel {
                font-weight: bold;
                font-size: 13px;
                color: #e0e0e0;
                padding-bottom: 4px;
            }
            QPushButton {
                background-color: #0e639c;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #094771;
            }
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 3px;
            }
            QListWidget::item:hover {
                background-color: #2a2d2e;
            }
            QListWidget::item:selected {
                background-color: #094771;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header title
        title_label = QLabel("Media Pool")
        layout.addWidget(title_label)

        # Import Media Button
        self.btn_import = QPushButton("Import Media")
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.clicked.connect(self._open_import_dialog)
        layout.addWidget(self.btn_import)

        # Draggable Media List Widget
        self.list_widget = DraggableMediaListWidget()
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

    @pyqtSlot()
    def _open_import_dialog(self) -> None:
        """Opens standard QFileDialog to select video files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media Files",
            "",
            "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)",
        )

        for file_path in file_paths:
            if file_path:
                self.add_media_item(file_path)

    def add_media_item(self, file_path: str) -> None:
        """Adds a media file to the list widget and stores its full path."""
        file_name = os.path.basename(file_path)
        item = QListWidgetItem(file_name)
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        item.setToolTip(file_path)
        self.list_widget.addItem(item)
        self.media_imported.emit(file_path)
