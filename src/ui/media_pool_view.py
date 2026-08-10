import os
from typing import Dict, List, Optional
from PyQt6.QtCore import QMimeData, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DraggableMediaListWidget(QListWidget):
    """A QListWidget that supports multi-selection and dragging media files to the timeline and receiving OS file drops."""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Packages the selected media item's file path into QMimeData for dragging."""
        items = self.selectedItems()
        if not items:
            cur = self.currentItem()
            if cur:
                items = [cur]
        if not items:
            return

        file_paths = [it.data(Qt.ItemDataRole.UserRole) for it in items if it.data(Qt.ItemDataRole.UserRole)]
        if not file_paths:
            return

        mime_data = QMimeData()
        mime_data.setText(file_paths[0])
        mime_data.setUrls([QUrl.fromLocalFile(fp) for fp in file_paths])

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
    """The media asset library / pool displaying imported media files and custom video length controls."""

    # Signal emitted when one or more media files are successfully imported
    media_imported = pyqtSignal(str)

    # Signal emitted when clip duration is set/modified for media files: (list of file paths, desired_duration)
    duration_changed = pyqtSignal(list, float)

    # Signal emitted to append selected media files onto timeline at the specified duration: (list of file paths, desired_duration)
    add_to_timeline_requested = pyqtSignal(list, float)

    def __init__(self):
        super().__init__()
        self.custom_durations: Dict[str, float] = {}

        self.setStyleSheet("""
            QWidget {
                background-color: #120e24;
                color: #f5f3ff;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel#PoolTitle {
                font-weight: bold;
                font-size: 13px;
                color: #f5f3ff;
                padding-bottom: 2px;
            }
            QPushButton#BtnImport {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
                color: #ffffff;
                border: 1px solid #a78bfa;
                border-radius: 5px;
                padding: 7px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#BtnImport:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #818cf8, stop:1 #a78bfa);
                border-color: #c4b5fd;
            }
            QPushButton#BtnImport:pressed {
                background-color: #4338ca;
            }
            QListWidget {
                background-color: #0d0a1a;
                border: 1px solid #2d2159;
                border-radius: 5px;
                padding: 4px;
                color: #f5f3ff;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
                margin-bottom: 2px;
                background-color: #1a1436;
                border: 1px solid #2d2159;
            }
            QListWidget::item:hover {
                background-color: #261e4d;
                border-color: #8b5cf6;
            }
            QListWidget::item:selected {
                background-color: #3b1d6b;
                border: 1px solid #d946ef;
                color: #ffffff;
            }
            QFrame#LengthControlFrame {
                background-color: #16112e;
                border: 1px solid #2d2159;
                border-radius: 6px;
                padding: 6px;
            }
            QLabel#LengthTitle {
                color: #c084fc;
                font-weight: bold;
                font-size: 11px;
                background: transparent;
                border: none;
            }
            QPushButton.preset-btn {
                background-color: #201842;
                color: #e9d5ff;
                border: 1px solid #3b2d70;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton.preset-btn:hover {
                background-color: #312366;
                border-color: #a855f7;
                color: #ffffff;
            }
            QPushButton.preset-btn:pressed {
                background-color: #4c1d95;
            }
            QDoubleSpinBox#SpinLength {
                background-color: #0d0a1a;
                color: #f5f3ff;
                border: 1px solid #3b2d70;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QDoubleSpinBox#SpinLength:focus {
                border-color: #a855f7;
            }
            QPushButton#BtnApplyLength {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #9333ea);
                color: #ffffff;
                border: 1px solid #c084fc;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#BtnApplyLength:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #a855f7);
                border-color: #f0abfc;
            }
            QPushButton#BtnApplyLength:pressed {
                background-color: #581c87;
            }
            QPushButton#BtnInsert {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #3b82f6);
                color: #ffffff;
                border: 1px solid #60a5fa;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#BtnInsert:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-color: #93c5fd;
            }
            QPushButton#BtnInsert:pressed {
                background-color: #1d4ed8;
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

        # Draggable Media List Widget (multi-select enabled)
        self.list_widget = DraggableMediaListWidget()
        self.list_widget.file_dropped.connect(self.add_media_item)
        layout.addWidget(self.list_widget, stretch=1)

        # Bottom Section: Independent Set Video Length (Trim/End) Function
        self.length_frame = QFrame()
        self.length_frame.setObjectName("LengthControlFrame")
        frame_layout = QVBoxLayout(self.length_frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)
        frame_layout.setSpacing(6)

        # Frame Title
        lbl_len_title = QLabel("⏱ Set Video Length (End Time)")
        lbl_len_title.setObjectName("LengthTitle")
        lbl_len_title.setToolTip("Shorten selected video(s) to end after a set period of seconds (1.0x normal speed, no stretching)")
        frame_layout.addWidget(lbl_len_title)

        # Quick Presets Row
        presets_layout = QHBoxLayout()
        presets_layout.setSpacing(4)
        for val, lbl in [(0.2, "0.2s"), (0.5, "0.5s"), (1.0, "1.0s"), (2.0, "2.0s")]:
            btn_p = QPushButton(lbl)
            btn_p.setProperty("class", "preset-btn")
            btn_p.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_p.clicked.connect(lambda checked=False, v=val: self._on_preset_clicked(v))
            presets_layout.addWidget(btn_p)

        btn_reset = QPushButton("Reset")
        btn_reset.setProperty("class", "preset-btn")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setToolTip("Reset to original video duration")
        btn_reset.clicked.connect(self._on_reset_clicked)
        presets_layout.addWidget(btn_reset)

        frame_layout.addLayout(presets_layout)

        # SpinBox Input Row
        spin_layout = QHBoxLayout()
        spin_layout.setSpacing(6)
        lbl_spin = QLabel("End at:")
        lbl_spin.setStyleSheet("color: #c4b5fd; font-size: 11px; font-weight: bold; background: transparent; border: none;")
        spin_layout.addWidget(lbl_spin)

        self.spin_length = QDoubleSpinBox()
        self.spin_length.setObjectName("SpinLength")
        self.spin_length.setRange(0.01, 9999.00)
        self.spin_length.setDecimals(2)
        self.spin_length.setSingleStep(0.10)
        self.spin_length.setValue(0.20)
        self.spin_length.setSuffix(" s")
        self.spin_length.setToolTip("Desired video duration in seconds (e.g. 0.20)")
        spin_layout.addWidget(self.spin_length, stretch=1)
        frame_layout.addLayout(spin_layout)

        # Action Buttons Row
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)

        self.btn_apply_length = QPushButton("✂️ Set Length")
        self.btn_apply_length.setObjectName("BtnApplyLength")
        self.btn_apply_length.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_length.setToolTip("Set desired length for selected video(s) in the list")
        self.btn_apply_length.clicked.connect(self._on_apply_length_clicked)
        actions_layout.addWidget(self.btn_apply_length, stretch=1)

        self.btn_insert = QPushButton("➕ To Timeline")
        self.btn_insert.setObjectName("BtnInsert")
        self.btn_insert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_insert.setToolTip("Insert selected video(s) onto timeline ending at specified length")
        self.btn_insert.clicked.connect(self._on_insert_clicked)
        actions_layout.addWidget(self.btn_insert, stretch=1)

        frame_layout.addLayout(actions_layout)
        layout.addWidget(self.length_frame)

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

    def get_custom_duration(self, file_path: str) -> Optional[float]:
        """Returns the custom duration in seconds configured for a media file, if any."""
        return self.custom_durations.get(file_path)

    def set_custom_duration(self, file_path: str, duration: float) -> None:
        """Stores custom end duration in seconds for a specific media file and refreshes its item label."""
        if not file_path:
            return
        self.custom_durations[file_path] = max(0.01, float(duration))
        self._refresh_item_label(file_path)

    def clear_custom_duration(self, file_path: str) -> None:
        """Clears custom duration for a media file, reverting to original media length."""
        self.custom_durations.pop(file_path, None)
        self._refresh_item_label(file_path)

    def get_selected_file_paths(self) -> List[str]:
        """Returns the list of absolute file paths for currently selected items in the media list."""
        selected = self.list_widget.selectedItems()
        if not selected and self.list_widget.currentItem():
            selected = [self.list_widget.currentItem()]
        paths = []
        for it in selected:
            p = it.data(Qt.ItemDataRole.UserRole)
            if p:
                paths.append(p)
        return paths

    def _refresh_item_label(self, file_path: str) -> None:
        """Updates the list item text and tooltip to reflect custom duration."""
        from models.clip import detect_media_type
        mtype = detect_media_type(file_path)
        icon = "🖼️" if mtype == "image" else ("🔊" if mtype == "audio" else "🎬")
        file_name = os.path.basename(file_path)
        cust_dur = self.custom_durations.get(file_path)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == file_path:
                if cust_dur is not None:
                    item.setText(f"{icon}  {file_name}  ⏱ {cust_dur:.2f}s")
                    item.setToolTip(
                        f"File: {file_path}\nType: {mtype.capitalize()}\n"
                        f"Set Length: {cust_dur:.2f}s (ends at {cust_dur:.2f}s, 1.0x normal speed)\n"
                        f"Drag or click 'To Timeline' to use"
                    )
                else:
                    item.setText(f"{icon}  {file_name}")
                    item.setToolTip(f"File: {file_path}\nType: {mtype.capitalize()}\nDrag onto timeline tracks to edit")
                break

    @pyqtSlot(float)
    def _on_preset_clicked(self, duration: float) -> None:
        """Applies preset duration to spinbox and immediately updates selected items if any."""
        self.spin_length.setValue(duration)
        paths = self.get_selected_file_paths()
        if paths:
            self._on_apply_length_clicked()

    @pyqtSlot()
    def _on_apply_length_clicked(self) -> None:
        """Applies spinbox duration to all selected media items (or all items if none selected)."""
        paths = self.get_selected_file_paths()
        if not paths:
            paths = [
                self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_widget.count())
                if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            ]
        if not paths:
            return

        dur = float(self.spin_length.value())
        for p in paths:
            self.custom_durations[p] = dur
            self._refresh_item_label(p)

        self.duration_changed.emit(paths, dur)

    @pyqtSlot()
    def _on_insert_clicked(self) -> None:
        """Emits signal to insert selected media files into timeline at the specified length."""
        paths = self.get_selected_file_paths()
        if not paths:
            paths = [
                self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_widget.count())
                if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            ]
        if not paths:
            return

        dur = float(self.spin_length.value())
        # Store custom duration for all inserted files
        for p in paths:
            self.custom_durations[p] = dur
            self._refresh_item_label(p)

        self.add_to_timeline_requested.emit(paths, dur)

    @pyqtSlot()
    def _on_reset_clicked(self) -> None:
        """Resets custom duration for selected items back to original media duration."""
        paths = self.get_selected_file_paths()
        if not paths:
            paths = [
                self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_widget.count())
                if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            ]
        for p in paths:
            self.custom_durations.pop(p, None)
            self._refresh_item_label(p)

