"""Central light desktop theme."""

STYLESHEET = """
QWidget { font-family: sans-serif; font-size: 14px; color: #233044; }
QMainWindow, QStackedWidget, QWidget#desktopPage { background: #f4f6f9; }
QScrollArea { border: none; }
QLabel { background: transparent; }
QLabel[heading="true"] { font-size: 24px; font-weight: 600; margin-bottom: 12px; }
QGroupBox { background: white; border: 1px solid #d9e0e8; border-radius: 6px; margin-top: 18px; padding: 18px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; font-weight: 600; }
QPushButton { min-height: 20px; background: white; border: 1px solid #cbd5e1; border-radius: 5px; padding: 9px 15px; }
QPushButton:hover { background: #e8eef7; }
QPushButton:disabled { color: #8693a5; background: #edf0f4; }
QPushButton[primary="true"] { background: #275dab; color: white; border: none; }
QPushButton[primary="true"]:disabled { background: #839bbd; }
QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox { background: white; border: 1px solid #cbd5e1; border-radius: 4px; padding: 7px; }
QListWidget, QTableWidget { background: white; border: 1px solid #d9e0e8; gridline-color: #edf0f4; }
QListWidget::item { padding: 12px; }
QListWidget::item:selected { background: #e5edfa; color: #204f94; }
QHeaderView::section { background: #edf1f6; border: none; padding: 10px; font-weight: 600; }
QStatusBar { background: white; }
"""
