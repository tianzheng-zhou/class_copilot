"""问题与答案显示组件。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.storage.models import AnswerMode, DetectedQuestion


class QuestionCard(QFrame):
    """单个问题卡片。"""

    copy_requested = pyqtSignal(str)

    def __init__(self, question: DetectedQuestion, parent=None) -> None:
        super().__init__(parent)
        self.question = question
        self._show_concise = True
        self._init_ui()

    def _init_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QuestionCard {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                padding: 8px;
                margin: 4px 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 问题标题
        source_icons = {"auto": "🔍", "manual": "✋", "force": "💬"}
        icon = source_icons.get(self.question.source, "❓")
        q_label = QLabel(f"{icon} {self.question.question_text}")
        q_label.setObjectName("question_label")
        q_label.setWordWrap(True)
        layout.addWidget(q_label)

        # 答案区域
        self._answer_label = QLabel()
        self._answer_label.setWordWrap(True)
        self._answer_label.setTextFormat(Qt.TextFormat.PlainText)
        self._answer_label.setSizePolicy(
            self._answer_label.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Minimum,
        )
        self._answer_label.setMinimumHeight(20)
        self._answer_label.setStyleSheet("color: #d4d4d4; padding: 4px;")
        layout.addWidget(self._answer_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._toggle_btn = QPushButton("展开版")
        self._toggle_btn.setObjectName("secondary_btn")
        self._toggle_btn.setFixedHeight(24)
        self._toggle_btn.clicked.connect(self._toggle_answer)
        btn_layout.addWidget(self._toggle_btn)

        copy_btn = QPushButton("复制")
        copy_btn.setObjectName("secondary_btn")
        copy_btn.setFixedHeight(24)
        copy_btn.clicked.connect(self._copy_answer)
        btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._update_answer()

    def update_answers(self, concise: str, detailed: str) -> None:
        self.question.concise_answer = concise
        self.question.detailed_answer = detailed
        self._update_answer()

    def _update_answer(self) -> None:
        if self._show_concise:
            text = self.question.concise_answer or "正在生成答案..."
            self._toggle_btn.setText("展开版")
        else:
            text = self.question.detailed_answer or "正在生成答案..."
            self._toggle_btn.setText("简洁版")
        self._answer_label.setText(text)

    def _toggle_answer(self) -> None:
        self._show_concise = not self._show_concise
        self._update_answer()

    def _copy_answer(self) -> None:
        text = self.question.concise_answer if self._show_concise else self.question.detailed_answer
        self.copy_requested.emit(text)

    def get_current_answer(self) -> str:
        if self._show_concise:
            return self.question.concise_answer
        return self.question.detailed_answer


class AnswerView(QWidget):
    """答案展示区域。"""

    copy_to_clipboard = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[QuestionCard] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── 问题卡片列表 ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._container_layout.setSpacing(8)

        self._placeholder = QLabel("暂无检测到的问题\n\n自动检测：开始监听后，系统会实时检测转写中的问题\n强制回答：点击右下角「回答」或按 Ctrl+Shift+Q\n手动提问：切换到「提问」标签页")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #808080; padding: 20px;")
        self._container_layout.addWidget(self._placeholder)

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

    @pyqtSlot(object)
    def add_question(self, question: DetectedQuestion) -> None:
        """添加新的问题卡片。"""
        if self._placeholder.isVisible():
            self._placeholder.hide()

        card = QuestionCard(question)
        card.copy_requested.connect(self.copy_to_clipboard)
        self._cards.append(card)
        self._container_layout.insertWidget(0, card)  # 最新的在最上面

    @pyqtSlot(object)
    def update_answer(self, question: DetectedQuestion) -> None:
        """更新问题的答案。"""
        for card in self._cards:
            if card.question.id == question.id:
                card.update_answers(question.concise_answer, question.detailed_answer)
                break

    def get_latest_answer(self) -> str:
        if self._cards:
            return self._cards[0].get_current_answer()
        return ""

    def toggle_latest_answer_mode(self) -> None:
        if self._cards:
            self._cards[0]._toggle_answer()

    def clear(self) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._placeholder.show()
