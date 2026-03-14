"""主动提问输入组件。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.storage.models import ActiveQA


class QuestionInput(QWidget):
    """主动提问输入区域。"""

    question_submitted = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._qa_history: list[ActiveQA] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 问答历史
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setPlaceholderText("在这里向 AI 提问课堂相关问题...")
        self._history.setMinimumHeight(100)
        layout.addWidget(self._history)

        # 输入行
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入问题后按回车发送...")
        self._input.returnPressed.connect(self._submit)
        input_layout.addWidget(self._input)

        send_btn = QPushButton("发送")
        send_btn.setFixedWidth(60)
        send_btn.clicked.connect(self._submit)
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return

        self._input.clear()
        self._append_user_message(text)
        self.question_submitted.emit(text)

    def _append_user_message(self, text: str) -> None:
        self._history.append(f'<p style="color:#569cd6;"><b>🙋 你:</b> {text}</p>')

    @pyqtSlot(object)
    def add_answer(self, qa: ActiveQA) -> None:
        """显示 AI 的回答。"""
        self._history.append(f'<p style="color:#4ec9b0;"><b>🤖 AI:</b> {qa.answer}</p>')
        self._history.append("<hr>")
        self._qa_history.append(qa)

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    def clear(self) -> None:
        self._history.clear()
        self._qa_history.clear()
