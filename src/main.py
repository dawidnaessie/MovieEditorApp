import os
import sys
import ctypes
from PyQt6.QtGui import QColor, QPalette, QIcon
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller bundle."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def main():
    # Set Windows AppUserModelID so the taskbar displays the custom icon rather than python.exe
    if sys.platform == "win32":
        try:
            myappid = "movieeditor.desktop.app.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    app = QApplication(sys.argv)
    
    # Configure application icon
    icon_path = get_resource_path(os.path.join("assets", "icon.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Configure modern dark Fusion theme
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0c0a17"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f3ff"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0d0a1a"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#120e24"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1f1740"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f5f3ff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f5f3ff"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1a1436"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f5f3ff"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#d946ef"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#7c3aed"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7c6f9f"))
    app.setPalette(palette)
    
    window = MainWindow()
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.showMaximized()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()