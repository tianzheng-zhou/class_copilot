"""声纹管理对话框。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.speaker_manager import SpeakerManager


class SpeakerDialog(QDialog):
    """声纹管理对话框。"""

    def __init__(self, speaker_mgr: SpeakerManager, parent=None) -> None:
        super().__init__(parent)
        self._speaker_mgr = speaker_mgr
        self.setWindowTitle("声纹管理")
        self.setMinimumSize(500, 300)
        self._init_ui()
        self._load_speakers()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("已注册的教师声纹："))

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["课程", "教师", "声纹 ID", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(3, 80)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondary_btn")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _load_speakers(self) -> None:
        speakers = self._speaker_mgr.get_all_speakers()
        self._table.setRowCount(len(speakers))

        for row, speaker in enumerate(speakers):
            self._table.setItem(row, 0, QTableWidgetItem(speaker.course_name))
            self._table.setItem(row, 1, QTableWidgetItem(speaker.name))
            self._table.setItem(row, 2, QTableWidgetItem(speaker.feature_id or ""))

            del_btn = QPushButton("删除")
            del_btn.setObjectName("danger_btn")
            del_btn.clicked.connect(lambda _, s=speaker: self._delete_speaker(s))
            self._table.setCellWidget(row, 3, del_btn)

    def _delete_speaker(self, speaker) -> None:
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除「{speaker.course_name} - {speaker.name}」的声纹吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._speaker_mgr.delete_teacher(speaker.id, speaker.feature_id or "")
            self._load_speakers()
