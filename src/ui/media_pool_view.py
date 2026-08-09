import os
from PyQt6.QtCore import QMimeData, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon
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
    """A QListWidget that supports dragging media files to the timeline and receiving OS file drops."""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        handled = False
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path and os.path.exists(local_path):
                    self.file_dropped.emit(local_path)
                    handled = True
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text.startswith("file:///"):
                from PyQt6.QtCore import QUrl
                local_path = QUrl(text).toLocalFile()
            else:
                local_path = text
            if local_path and os.path.exists(local_path):
                self.file_dropped.emit(local_path)
                handled = True

        if handled:
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MediaPoolView(QWidget):
    """The media asset library / pool displaying imported media files."""

    # Signal emitted when one or more media files are successfully imported
    media_imported = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget {
                background-color: #1c1c1f;
                color: #e4e4e7;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel#PoolTitle {
                font-weight: bold;
                font-size: 13px;
                color: #f4f4f5;
                padding-bottom: 2px;
            }
            QPushButton#BtnImport {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 7px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#BtnImport:hover {
                background-color: #3b82f6;
            }
            QPushButton#BtnImport:pressed {
                background-color: #1d4ed8;
            }
            QListWidget {
                background-color: #141416;
                border: 1px solid #27272a;
                border-radius: 5px;
                padding: 4px;
                color: #f4f4f5;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
                margin-bottom: 2px;
                background-color: #1f1f23;
                border: 1px solid #27272a;
            }
            QListWidget::item:hover {
                background-color: #27272a;
                border-color: #388bfd;
            }
            QListWidget::item:selected {
                background-color: #1e3a5f;
                border-color: #58a6ff;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header title
        title_label = QLabel("📁 Media Pool")
        title_label.setObjectName("PoolTitle")
        layout.addWidget(title_label)

        # Import Media Button
        self.btn_import = QPushButton("➕ Import Media Files")
        self.btn_import.setObjectName("BtnImport")
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setToolTip("Click to browse or drag video files directly into this panel")
        self.btn_import.clicked.connect(self._open_import_dialog)
        layout.addWidget(self.btn_import)

        # Draggable Media List Widget
        self.list_widget = DraggableMediaListWidget()
        self.list_widget.file_dropped.connect(self.add_media_item)
        layout.addWidget(self.list_widget)

    @pyqtSlot()
    def _open_import_dialog(self) -> None:
        """Opens standard QFileDialog to select video and image media files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media Files",
            "",
            "Media Files (*.mp4 *.mov *.avi *.mkv *.webm *.png *.jpg *.jpeg *.webp *.bmp *.mp3 *.wav);;"
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;"
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;"
            "Audio Files (*.mp3 *.wav *.aac *.flac *.m4a *.ogg);;"
            "All Files (*)",
        )

        for file_path in file_paths:
            if file_path:
                self.add_media_item(file_path)

    def add_media_item(self, file_path: str) -> None:
        """Adds a media file to the list widget and stores its full path."""
        if not file_path or not os.path.exists(file_path):
            return

        # Check if already added
        for i in range(self.list_widget.count()):
            existing_item = self.list_widget.item(i)
            if existing_item and existing_item.data(Qt.ItemDataRole.UserRole) == file_path:
                return

        from models.clip import detect_media_type
        mtype = detect_media_type(file_path)
        icon = "🖼️" if mtype == "image" else ("🔊" if mtype == "audio" else "🎬")

        file_name = os.path.basename(file_path)
        item = QListWidgetItem(f"{icon}  {file_name}")
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        item.setToolTip(f"File: {file_path}\nType: {mtype.capitalize()}\nDrag onto timeline tracks to edit")
        self.list_widget.addItem(item)
        self.media_imported.emit(file_path)

