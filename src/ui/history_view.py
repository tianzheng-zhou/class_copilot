"""历史课堂记录查看器。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.session_manager import SessionManager
from src.storage.models import ClassSession


class HistoryView(QDialog):
    """历史课堂记录查看器。"""

    def __init__(self, session_mgr: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_mgr = session_mgr
        self.setWindowTitle("历史课堂记录")
        self.setMinimumSize(700, 500)
        self._init_ui()
        self._load_sessions()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧列表
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_session_selected)
        splitter.addWidget(self._list)

        # 右侧详情
        right = QVBoxLayout()
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("选择一条课堂记录查看详情")

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._detail)

        export_layout = QHBoxLayout()
        export_layout.addStretch()

        export_btn = QPushButton("导出 Markdown")
        export_btn.clicked.connect(self._export)
        export_layout.addWidget(export_btn)

        right_layout.addLayout(export_layout)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def _load_sessions(self) -> None:
        sessions = self._session_mgr.get_history_sessions()
        self._list.clear()
        for session in sessions:
            item = QListWidgetItem(f"{session.date} - {session.course_name}")
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self._list.addItem(item)

    def _on_session_selected(self, current: QListWidgetItem | None, _) -> None:
        if not current:
            return
        session_id = current.data(Qt.ItemDataRole.UserRole)
        md = self._session_mgr.export_session_markdown(session_id)
        self._detail.setMarkdown(md)

    def _export(self) -> None:
        current = self._list.currentItem()
        if not current:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return

        session_id = current.data(Qt.ItemDataRole.UserRole)
        md = self._session_mgr.export_session_markdown(session_id)

        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Markdown", f"class_record_{session_id}.md", "Markdown (*.md);;Text (*.txt)"
        )
        if path:
            Path(path).write_text(md, encoding="utf-8")
            QMessageBox.information(self, "导出成功", f"已导出到: {path}")
