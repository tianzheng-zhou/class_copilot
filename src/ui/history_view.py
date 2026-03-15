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
from src.storage.models import ClassSession, SessionStatus


class HistoryView(QDialog):
    """历史课堂记录查看器。"""

    def __init__(self, session_mgr: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_mgr = session_mgr
        self._resume_session_id: int | None = None   # 用户点击续记后保存
        self.setWindowTitle("历史课堂记录")
        self.setMinimumSize(700, 500)
        self._init_ui()
        self._load_sessions()

    @property
    def resume_session_id(self) -> int | None:
        """若用户点击了"续记"，返回对应的 session_id，否则为 None。"""
        return self._resume_session_id

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧列表
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_session_selected)
        splitter.addWidget(self._list)

        # 右侧详情
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("选择一条课堂记录查看详情")
        right_layout.addWidget(self._detail)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._resume_btn = QPushButton("▶ 续记")
        self._resume_btn.setToolTip("在此会话上继续录制新内容（历史转写上下文保留）")
        self._resume_btn.setEnabled(False)
        self._resume_btn.clicked.connect(self._on_resume)
        btn_layout.addWidget(self._resume_btn)

        export_btn = QPushButton("导出 Markdown")
        export_btn.clicked.connect(self._export)
        btn_layout.addWidget(export_btn)

        right_layout.addLayout(btn_layout)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def _load_sessions(self) -> None:
        sessions = self._session_mgr.get_history_sessions()
        self._list.clear()
        for session in sessions:
            status_mark = " 🔴" if session.status == SessionStatus.RECORDING else ""
            item = QListWidgetItem(f"{session.date} - {session.course_name}{status_mark}")
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self._list.addItem(item)

    def _on_session_selected(self, current: QListWidgetItem | None, _) -> None:
        if not current:
            self._resume_btn.setEnabled(False)
            return
        session_id = current.data(Qt.ItemDataRole.UserRole)
        md = self._session_mgr.export_session_markdown(session_id)
        self._detail.setMarkdown(md)
        self._resume_btn.setEnabled(True)

    def _on_resume(self) -> None:
        current = self._list.currentItem()
        if not current:
            return
        if self._session_mgr.is_listening:
            QMessageBox.warning(self, "无法续记", "请先停止当前正在进行的会话。")
            return
        self._resume_session_id = current.data(Qt.ItemDataRole.UserRole)
        self.accept()  # 关闭对话框，main_window 读取 resume_session_id

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
