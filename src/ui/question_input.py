"""主动提问输入组件。"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.config.constants import QA_MODEL_CHOICES
from src.storage.models import ActiveQA


def _md_to_html(text: str) -> str:
    """简易 Markdown → HTML 转换（无需第三方库）。"""
    html = text

    # 代码块 ```...```
    html = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: f'<pre style="background:#2d2d2d;padding:8px;border-radius:4px;'
                  f'overflow-x:auto;font-family:Consolas,monospace;font-size:12px;'
                  f'color:#d4d4d4;"><code>{m.group(2).replace("<", "&lt;").replace(">", "&gt;")}</code></pre>',
        html,
        flags=re.DOTALL,
    )

    # 行内代码
    html = re.sub(r"`([^`]+)`", r'<code style="background:#2d2d2d;padding:1px 4px;border-radius:3px;font-family:Consolas,monospace;font-size:12px;">\1</code>', html)

    # 标题 h1-h3
    html = re.sub(r"^### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)

    # 加粗 / 斜体
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html)

    # 无序列表
    html = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

    # 有序列表
    html = re.sub(r"^\d+\. (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

    # 换行
    html = html.replace("\n", "<br>")

    # 清理连续 <br> 在 <li> 前后
    html = re.sub(r"<br>(<li>)", r"\1", html)
    html = re.sub(r"(</li>)<br>", r"\1", html)

    return html


class QuestionInput(QWidget):
    """主动提问输入区域。"""

    question_submitted = pyqtSignal(str)
    settings_changed = pyqtSignal(str, object)  # key, value

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._qa_history: list[ActiveQA] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 选项栏：模型选择 + 深度思考开关
        options_layout = QHBoxLayout()
        options_layout.setSpacing(8)

        model_label = QLabel("模型:")
        model_label.setFixedWidth(35)
        options_layout.addWidget(model_label)

        self._model_combo = QComboBox()
        for model_id, display_name in QA_MODEL_CHOICES.items():
            self._model_combo.addItem(display_name, model_id)
        self._model_combo.setToolTip("选择提问使用的模型")
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        options_layout.addWidget(self._model_combo)

        self._thinking_cb = QCheckBox("深度思考")
        self._thinking_cb.setToolTip("开启后模型会先推理再回答，更准确但更慢")
        self._thinking_cb.stateChanged.connect(self._on_thinking_changed)
        options_layout.addWidget(self._thinking_cb)

        layout.addLayout(options_layout)

        # 问答历史（使用 QTextBrowser 支持富文本渲染）
        self._history = QTextBrowser()
        self._history.setReadOnly(True)
        self._history.setOpenExternalLinks(False)
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
        """显示 AI 的回答（渲染 Markdown）。"""
        answer_html = _md_to_html(qa.answer)
        self._history.append(
            f'<p style="color:#4ec9b0;"><b>🤖 AI:</b> {answer_html}</p>'
        )
        self._history.append("<hr>")
        self._qa_history.append(qa)

    def _on_model_changed(self, index: int) -> None:
        model_id = self._model_combo.currentData()
        if model_id:
            self.settings_changed.emit("qa_model", model_id)

    def _on_thinking_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self.settings_changed.emit("qa_enable_thinking", enabled)

    def apply_settings(self, qa_model: str, qa_enable_thinking: bool) -> None:
        """从 settings 初始化控件状态。"""
        idx = self._model_combo.findData(qa_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._thinking_cb.setChecked(qa_enable_thinking)

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    def clear(self) -> None:
        self._history.clear()
        self._qa_history.clear()
