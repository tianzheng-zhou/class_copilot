"""实时转写显示组件。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from src.storage.models import SpeakerRole, TranscriptSegment


class TranscriptView(QWidget):
    """实时转写文本显示区域。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText("等待转写...")
        layout.addWidget(self._text_edit)

        self._bilingual = True

    def set_bilingual(self, enabled: bool) -> None:
        self._bilingual = enabled

    @pyqtSlot(object)
    def add_segment(self, segment: TranscriptSegment) -> None:
        """添加一个转写片段到显示区域。"""
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 说话人标签
        label_fmt = QTextCharFormat()
        if segment.speaker_role == SpeakerRole.TEACHER:
            label_fmt.setForeground(QColor("#4ec9b0"))
            label_text = "🎓 教师"
        else:
            label_fmt.setForeground(QColor("#569cd6"))
            label_text = f"👤 {segment.speaker_label or '未知'}"

        label_fmt.setFontWeight(700)
        cursor.insertText(f"\n{label_text}: ", label_fmt)

        # 转写文本
        text_fmt = QTextCharFormat()
        text_fmt.setForeground(QColor("#d4d4d4"))
        cursor.insertText(segment.text, text_fmt)

        # 翻译（双语模式）
        if self._bilingual and segment.translation:
            trans_fmt = QTextCharFormat()
            trans_fmt.setForeground(QColor("#808080"))
            trans_fmt.setFontItalic(True)
            cursor.insertText(f"\n  📝 {segment.translation}", trans_fmt)

        # 自动滚动到底部
        self._text_edit.setTextCursor(cursor)
        self._text_edit.ensureCursorVisible()

    def clear(self) -> None:
        self._text_edit.clear()
