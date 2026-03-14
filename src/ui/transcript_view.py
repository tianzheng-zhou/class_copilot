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
        # 跟踪当前中间结果在文档中的起始位置，用于原地更新
        self._pending_block_start: int | None = None

    def set_bilingual(self, enabled: bool) -> None:
        self._bilingual = enabled

    @pyqtSlot(object)
    def add_segment(self, segment: TranscriptSegment) -> None:
        """添加或更新一个转写片段到显示区域。"""
        if not segment.is_final and self._pending_block_start is not None:
            # 中间结果：擦除上一次的中间内容后重写
            cursor = self._text_edit.textCursor()
            cursor.setPosition(self._pending_block_start)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            self._insert_segment_text(cursor, segment)
            self._text_edit.setTextCursor(cursor)
            self._text_edit.ensureCursorVisible()
            return

        # 新行（最终结果或首次中间结果）
        if self._pending_block_start is not None:
            # 之前有中间结果，先清除
            cursor = self._text_edit.textCursor()
            cursor.setPosition(self._pending_block_start)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            cursor = self._text_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

        self._insert_segment_text(cursor, segment)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.ensureCursorVisible()

        if segment.is_final:
            self._pending_block_start = None
        else:
            # 记录当前中间结果的起始位置，用于下次覆盖
            pass  # _insert_segment_text 已设置

    def _insert_segment_text(self, cursor: QTextCursor, segment: TranscriptSegment) -> None:
        """在光标位置插入转写内容。"""
        # 记录起始位置
        self._pending_block_start = cursor.position()

        # 说话人标签
        label_fmt = QTextCharFormat()
        if segment.speaker_role == SpeakerRole.TEACHER:
            label_fmt.setForeground(QColor("#4ec9b0"))
            label_text = "教师"
        else:
            label_fmt.setForeground(QColor("#569cd6"))
            label_text = segment.speaker_label or "未知"

        label_fmt.setFontWeight(700)
        cursor.insertText(f"\n{label_text}: ", label_fmt)

        # 转写文本
        text_fmt = QTextCharFormat()
        text_fmt.setForeground(QColor("#d4d4d4"))
        if not segment.is_final:
            text_fmt.setForeground(QColor("#808080"))  # 中间结果用灰色
        cursor.insertText(segment.text, text_fmt)

        # 翻译（双语模式，仅最终结果）
        if self._bilingual and segment.translation and segment.is_final:
            trans_fmt = QTextCharFormat()
            trans_fmt.setForeground(QColor("#808080"))
            trans_fmt.setFontItalic(True)
            cursor.insertText(f"\n  {segment.translation}", trans_fmt)

    def clear(self) -> None:
        self._text_edit.clear()
