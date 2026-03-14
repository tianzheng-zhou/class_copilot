"""设置对话框。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from src.asr.audio_capture import AudioCapture
from src.config.settings import Settings


class SettingsDialog(QDialog):
    """设置对话框。"""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置")
        self.setMinimumWidth(450)
        self._init_ui()
        self._load_values()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_api_tab(), "API 密钥")
        tabs.addTab(self._create_audio_tab(), "音频")
        tabs.addTab(self._create_general_tab(), "通用")
        layout.addWidget(tabs)

        # 保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("secondary_btn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _create_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 讯飞 ASR
        asr_group = QGroupBox("科大讯飞 ASR")
        asr_layout = QFormLayout(asr_group)

        self._iflytek_app_id = QLineEdit()
        self._iflytek_app_id.setEchoMode(QLineEdit.EchoMode.Password)
        asr_layout.addRow("App ID:", self._iflytek_app_id)

        self._iflytek_key_id = QLineEdit()
        self._iflytek_key_id.setEchoMode(QLineEdit.EchoMode.Password)
        asr_layout.addRow("Access Key ID:", self._iflytek_key_id)

        self._iflytek_key_secret = QLineEdit()
        self._iflytek_key_secret.setEchoMode(QLineEdit.EchoMode.Password)
        asr_layout.addRow("Access Key Secret:", self._iflytek_key_secret)

        layout.addWidget(asr_group)

        # 阿里云 LLM
        llm_group = QGroupBox("阿里云百炼 LLM")
        llm_layout = QFormLayout(llm_group)

        self._dashscope_key = QLineEdit()
        self._dashscope_key.setEchoMode(QLineEdit.EchoMode.Password)
        llm_layout.addRow("API Key:", self._dashscope_key)

        layout.addWidget(llm_group)
        layout.addStretch()

        return widget

    def _create_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self._mic_combo = QComboBox()
        self._mic_combo.addItem("系统默认", -1)
        for dev in AudioCapture.list_devices():
            self._mic_combo.addItem(dev["name"], dev["index"])
        layout.addRow("麦克风:", self._mic_combo)

        return widget

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("中文", "zh")
        self._lang_combo.addItem("English", "en")
        form.addRow("授课语言:", self._lang_combo)

        self._concise_check = QCheckBox("启用简洁版答案")
        form.addRow(self._concise_check)

        self._detailed_check = QCheckBox("启用展开版答案")
        form.addRow(self._detailed_check)

        self._translate_check = QCheckBox("英文授课时翻译")
        form.addRow(self._translate_check)

        self._bilingual_check = QCheckBox("中英双语展示")
        form.addRow(self._bilingual_check)

        layout.addLayout(form)

        # 存储路径
        path_layout = QHBoxLayout()
        self._storage_path = QLineEdit()
        self._storage_path.setPlaceholderText("默认: ~/.class_copilot")
        path_layout.addWidget(self._storage_path)

        browse_btn = QPushButton("浏览")
        browse_btn.setObjectName("secondary_btn")
        browse_btn.clicked.connect(self._browse_path)
        path_layout.addWidget(browse_btn)

        layout.addWidget(QLabel("存储路径:"))
        layout.addLayout(path_layout)

        layout.addStretch()
        return widget

    def _load_values(self) -> None:
        # API Keys - 显示占位符
        if self.settings.has_api_key(Settings.IFLYTEK_APP_ID):
            self._iflytek_app_id.setPlaceholderText("已配置（留空保持不变）")
        if self.settings.has_api_key(Settings.IFLYTEK_ACCESS_KEY_ID):
            self._iflytek_key_id.setPlaceholderText("已配置（留空保持不变）")
        if self.settings.has_api_key(Settings.IFLYTEK_ACCESS_KEY_SECRET):
            self._iflytek_key_secret.setPlaceholderText("已配置（留空保持不变）")
        if self.settings.has_api_key(Settings.DASHSCOPE_API_KEY):
            self._dashscope_key.setPlaceholderText("已配置（留空保持不变）")

        # 麦克风
        mic_idx = self.settings.microphone_index
        for i in range(self._mic_combo.count()):
            if self._mic_combo.itemData(i) == mic_idx:
                self._mic_combo.setCurrentIndex(i)
                break

        # 语言
        lang = self.settings.language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == lang:
                self._lang_combo.setCurrentIndex(i)
                break

        self._concise_check.setChecked(self.settings.answer_mode_concise)
        self._detailed_check.setChecked(self.settings.answer_mode_detailed)
        self._translate_check.setChecked(self.settings.get("translation_enabled", True))
        self._bilingual_check.setChecked(self.settings.get("bilingual_display", True))
        self._storage_path.setText(self.settings.get("storage_path", ""))

    def _browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择存储路径")
        if path:
            self._storage_path.setText(path)

    def _save_and_close(self) -> None:
        # 保存 API Keys（仅当用户输入了新值时）
        if self._iflytek_app_id.text():
            self.settings.set_api_key(Settings.IFLYTEK_APP_ID, self._iflytek_app_id.text())
        if self._iflytek_key_id.text():
            self.settings.set_api_key(Settings.IFLYTEK_ACCESS_KEY_ID, self._iflytek_key_id.text())
        if self._iflytek_key_secret.text():
            self.settings.set_api_key(Settings.IFLYTEK_ACCESS_KEY_SECRET, self._iflytek_key_secret.text())
        if self._dashscope_key.text():
            self.settings.set_api_key(Settings.DASHSCOPE_API_KEY, self._dashscope_key.text())

        # 保存通用设置
        self.settings.set("microphone_index", self._mic_combo.currentData())
        self.settings.set("language", self._lang_combo.currentData())
        self.settings.set("answer_mode_concise", self._concise_check.isChecked())
        self.settings.set("answer_mode_detailed", self._detailed_check.isChecked())
        self.settings.set("translation_enabled", self._translate_check.isChecked())
        self.settings.set("bilingual_display", self._bilingual_check.isChecked())

        storage = self._storage_path.text().strip()
        if storage:
            self.settings.set("storage_path", storage)

        self.accept()
