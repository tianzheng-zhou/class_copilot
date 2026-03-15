"""深色主题样式。"""

DARK_THEME = """
* {
    outline: none;
}

QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #1e1e1e;
}

/* 标签 */
QLabel {
    color: #d4d4d4;
    background: transparent;
}

QLabel#teacher_label {
    color: #4ec9b0;
    font-weight: bold;
}

QLabel#question_label {
    color: #dcdcaa;
    font-weight: bold;
    font-size: 14px;
}

QLabel#status_label {
    color: #808080;
    font-size: 11px;
}

/* 按钮 */
QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    padding: 4px 10px;
    border-radius: 3px;
    min-height: 24px;
}

QPushButton:hover {
    background-color: #1177bb;
}

QPushButton:pressed {
    background-color: #094771;
}

QPushButton:disabled {
    background-color: #3c3c3c;
    color: #808080;
}

QPushButton#danger_btn {
    background-color: #a1260d;
}

QPushButton#danger_btn:hover {
    background-color: #c4200e;
}

QPushButton#secondary_btn {
    background-color: #3c3c3c;
    color: #d4d4d4;
}

QPushButton#secondary_btn:hover {
    background-color: #505050;
}

QPushButton#secondary_btn:checked {
    background-color: #0e639c;
    color: white;
}

/* 输入框 */
QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 4px 8px;
    selection-background-color: #264f78;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus {
    border-color: #0e639c;
}

/* 下拉框 */
QComboBox {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 24px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #d4d4d4;
    selection-background-color: #094771;
    border: 1px solid #3c3c3c;
}

/* 滚动区域 */
QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background-color: #1e1e1e;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #424242;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4f4f4f;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* 标签页 */
QTabWidget::pane {
    border: 1px solid #3c3c3c;
    background-color: #1e1e1e;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #808080;
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:selected {
    color: #d4d4d4;
    border-bottom: 2px solid #0e639c;
}

QTabBar::tab:hover {
    color: #d4d4d4;
}

/* 列表 */
QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    outline: none;
}

QListWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #2d2d2d;
}

QListWidget::item:selected {
    background-color: #094771;
}

QListWidget::item:hover {
    background-color: #2d2d2d;
}

/* 分组框 */
QGroupBox {
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    margin-top: 8px;
    padding-top: 16px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    padding: 0 6px;
    color: #4ec9b0;
}

/* 复选框 */
QCheckBox {
    spacing: 8px;
    color: #d4d4d4;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    background-color: #2d2d2d;
}

QCheckBox::indicator:checked {
    background-color: #0e639c;
    border-color: #0e639c;
}

/* 菜单 */
QMenu {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 3px;
}

QMenu::item:selected {
    background-color: #094771;
}

/* 工具提示 */
QToolTip {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    padding: 4px;
}

/* 分隔线 */
QFrame[frameShape="4"] {
    color: #3c3c3c;
    max-height: 1px;
}
"""
