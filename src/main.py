import sys
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    
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
    window.showMaximized()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()