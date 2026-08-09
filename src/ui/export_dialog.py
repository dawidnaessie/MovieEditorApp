"""CapCut-styled Video Export Dialog for rendering master MP4 and WebM videos.

Provides resolution, framerate, and format presets, and runs the export
asynchronously in a background thread with real-time progress bar feedback.
Conforms strictly to docs/ai_agents/ui_developer.md.
"""

import os
from typing import Optional, Tuple
from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from engine.render_engine import RenderEngine, RenderWorker
from models.project import Project


class ExportDialog(QDialog):
    """Modern dark-themed export settings and rendering progress dialog."""

    export_finished = pyqtSignal(bool, str)

    def __init__(self, project: Project, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project = project
        self.render_engine = RenderEngine()
        self.render_worker: Optional[RenderWorker] = None
        self.thread_pool = QThreadPool.globalInstance()
        self.is_rendering = False

        self.setWindowTitle("Export Project")
        self.setFixedSize(520, 390)
        self.setModal(True)

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
                font-size: 16px;
                font-weight: bold;
                color: #f5f3ff;
            }
            QComboBox, QLineEdit {
                background-color: #1a1436;
                color: #f5f3ff;
                border: 1px solid #36296b;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QComboBox:hover, QLineEdit:hover {
                border-color: #8b5cf6;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QPushButton.primary-btn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:0.5 #9333ea, stop:1 #d946ef);
                color: #ffffff;
                border: 1px solid #c084fc;
                border-radius: 5px;
                padding: 8px 18px;
                font-weight: bold;
                font-size: 13px;
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
                background-color: #261e4d;
                border-color: #8b5cf6;
                color: #ffffff;
            }
            QProgressBar {
                background-color: #1a1436;
                border: 1px solid #36296b;
                border-radius: 5px;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 16px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #d946ef);
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title
        lbl_title = QLabel("🎬 Export Video")
        lbl_title.setObjectName("DialogTitle")
        layout.addWidget(lbl_title)

        # Form Layout
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        # 1. Export Format (MP4 / WebM)
        self.combo_format = QComboBox()
        self.combo_format.addItem("MP4 (H.264 / AAC) — Recommended", "mp4")
        self.combo_format.addItem("WebM (VP9 / Vorbis) — Web Optimized", "webm")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        form_layout.addRow("Format:", self.combo_format)

        # 2. Resolution Preset
        self.combo_res = QComboBox()
        self.combo_res.addItem("1080p Full HD (1920 × 1080)", (1920, 1080))
        self.combo_res.addItem("720p HD (1280 × 720)", (1280, 720))
        self.combo_res.addItem("4K Ultra HD (3840 × 2160)", (3840, 2160))
        proj_res = self.project.resolution if hasattr(self.project, "resolution") else (1920, 1080)
        self.combo_res.addItem(f"Project Default ({proj_res[0]} × {proj_res[1]})", proj_res)
        form_layout.addRow("Resolution:", self.combo_res)

        # 3. Framerate Preset
        self.combo_fps = QComboBox()
        self.combo_fps.addItem("30 FPS (Standard)", 30.0)
        self.combo_fps.addItem("60 FPS (Smooth)", 60.0)
        self.combo_fps.addItem("24 FPS (Cinematic)", 24.0)
        form_layout.addRow("Framerate:", self.combo_fps)

        # 4. Destination File Path
        path_layout = QHBoxLayout()
        default_dir = os.path.expanduser("~/Videos") if os.path.exists(os.path.expanduser("~/Videos")) else os.path.expanduser("~")
        default_filename = f"{self.project.name.lower().replace(' ', '_')}.mp4"
        default_full_path = os.path.join(default_dir, default_filename)

        self.txt_path = QLineEdit(default_full_path)
        btn_browse = QPushButton("Browse...")
        btn_browse.setProperty("class", "secondary-btn")
        btn_browse.clicked.connect(self._browse_destination)
        path_layout.addWidget(self.txt_path, stretch=1)
        path_layout.addWidget(btn_browse)
        form_layout.addRow("Save To:", path_layout)

        layout.addLayout(form_layout)

        # Progress Section
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready to export.")
        self.lbl_status.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_open_folder = QPushButton("📁 Open Folder")
        self.btn_open_folder.setProperty("class", "secondary-btn")
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        btn_layout.addWidget(self.btn_open_folder)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setProperty("class", "secondary-btn")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("🚀 Export Video")
        self.btn_export.setProperty("class", "primary-btn")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.clicked.connect(self.start_export)
        btn_layout.addWidget(self.btn_export)

        layout.addLayout(btn_layout)

    def _on_format_changed(self, index: int) -> None:
        """Updates file extension when export format changes."""
        fmt = self.combo_format.currentData()
        current_path = self.txt_path.text()
        base, _ = os.path.splitext(current_path)
        self.txt_path.setText(f"{base}.{fmt}")

    def _browse_destination(self) -> None:
        """Opens file dialog for choosing destination file path."""
        fmt = self.combo_format.currentData()
        filter_str = "MP4 Video (*.mp4)" if fmt == "mp4" else "WebM Video (*.webm)"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Rendered Video",
            self.txt_path.text(),
            f"{filter_str};;All Files (*.*)",
        )
        if file_path:
            self.txt_path.setText(file_path)

    def start_export(self) -> None:
        """Initiates the background export worker."""
        if self.is_rendering:
            return

        out_path = self.txt_path.text().strip()
        if not out_path:
            self.lbl_status.setText("Error: Destination path cannot be empty.")
            return

        fmt = self.combo_format.currentData()
        res = self.combo_res.currentData()
        fps = float(self.combo_fps.currentData())

        self.is_rendering = True
        self.btn_export.setEnabled(False)
        self.btn_open_folder.setVisible(False)
        self.combo_format.setEnabled(False)
        self.combo_res.setEnabled(False)
        self.combo_fps.setEnabled(False)
        self.txt_path.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Initializing render pipeline...")

        self.render_worker = RenderWorker(
            engine=self.render_engine,
            project=self.project,
            output_path=out_path,
            export_format=fmt,
            resolution=res,
            fps=fps,
        )
        self.render_worker.signals.progress_updated.connect(self._on_progress_updated)
        self.render_worker.signals.rendering_finished.connect(self._on_rendering_finished)

        self.thread_pool.start(self.render_worker)

    @pyqtSlot(float, str)
    def _on_progress_updated(self, percent: float, status_msg: str) -> None:
        """Updates progress bar and status label."""
        self.progress_bar.setValue(int(percent))
        self.lbl_status.setText(status_msg)

    @pyqtSlot(bool, str)
    def _on_rendering_finished(self, success: bool, message: str) -> None:
        """Handles completion of the background render process."""
        self.is_rendering = False
        self.btn_export.setEnabled(True)
        self.combo_format.setEnabled(True)
        self.combo_res.setEnabled(True)
        self.combo_fps.setEnabled(True)
        self.txt_path.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_status.setText("🎉 Video exported successfully!")
            self.btn_open_folder.setVisible(True)
            self.btn_cancel.setText("Close")
        else:
            self.lbl_status.setText(f"❌ {message}")

        self.export_finished.emit(success, message)

    def _open_output_folder(self) -> None:
        """Opens the exported video file location in OS Explorer."""
        path = self.txt_path.text()
        if os.path.exists(path):
            import subprocess
            folder = os.path.dirname(path)
            if os.name == "nt":
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            else:
                subprocess.Popen(["xdg-open", folder])

    def _on_cancel_clicked(self) -> None:
        """Cancels active rendering or closes dialog."""
        if self.is_rendering:
            if self.render_worker:
                self.render_worker.cancel()
            self.lbl_status.setText("Cancelling export...")
        else:
            self.reject()

    def closeEvent(self, event) -> None:
        if self.is_rendering and self.render_worker:
            self.render_worker.cancel()
        super().closeEvent(event)
