"""主窗口 - 悬浮窗形态。"""

from __future__ import annotations

import ctypes
import logging

from PyQt6.QtCore import QPoint, QSettings, QSize, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.config.constants import WINDOW_DEFAULT_HEIGHT, WINDOW_DEFAULT_WIDTH
from src.core.session_manager import SessionManager
from src.storage.models import ActiveQA, DetectedQuestion, TranscriptSegment
from src.ui.answer_view import AnswerView
from src.ui.history_view import HistoryView
from src.ui.question_input import QuestionInput
from src.ui.settings_dialog import SettingsDialog
from src.ui.speaker_dialog import SpeakerDialog
from src.ui.system_tray import SystemTray
from src.ui.transcript_view import TranscriptView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """主悬浮窗。"""

    # 跨线程信号
    sig_transcript = pyqtSignal(object)
    sig_question = pyqtSignal(object)
    sig_answer = pyqtSignal(object)
    sig_status = pyqtSignal(str)
    sig_error = pyqtSignal(str)
    sig_active_qa = pyqtSignal(object)
    _sig_hotkey = pyqtSignal(str)

    def __init__(self, session_mgr: SessionManager) -> None:
        super().__init__()
        self._session_mgr = session_mgr
        self._init_ui()
        self._init_tray()
        self._connect_signals()
        self._connect_session_callbacks()
        self._load_course_history()
        self._restore_geometry()

    def _init_ui(self) -> None:
        self.setWindowTitle("听课助手")
        self._stay_on_top = True
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 400)
        self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)

        # 定位到屏幕右下角
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.right() - WINDOW_DEFAULT_WIDTH - 20,
                geo.bottom() - WINDOW_DEFAULT_HEIGHT - 20,
            )

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 顶部控制栏 ──
        top_bar = QHBoxLayout()

        self._course_combo = QComboBox()
        self._course_combo.setEditable(True)
        self._course_combo.setPlaceholderText("输入课程名称")
        self._course_combo.setMinimumWidth(120)
        top_bar.addWidget(self._course_combo)

        self._listen_btn = QPushButton("开始")
        self._listen_btn.setFixedWidth(70)
        self._listen_btn.clicked.connect(self._toggle_listen)
        top_bar.addWidget(self._listen_btn)

        self._pin_btn = QPushButton("置顶")
        self._pin_btn.setObjectName("secondary_btn")
        self._pin_btn.setFixedWidth(60)
        self._pin_btn.setToolTip("切换窗口是否始终置顶")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(True)
        self._pin_btn.clicked.connect(self._toggle_stay_on_top)
        top_bar.addWidget(self._pin_btn)

        layout.addLayout(top_bar)

        # ── 状态栏 ──
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("status_label")
        layout.addWidget(self._status_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # ── 标签页 ──
        self._tabs = QTabWidget()

        # 转写 Tab
        self._transcript_view = TranscriptView()
        self._tabs.addTab(self._transcript_view, "转写")

        # 答案 Tab
        self._answer_view = AnswerView()
        self._tabs.addTab(self._answer_view, "答案")

        # 提问 Tab
        self._question_input = QuestionInput()
        self._tabs.addTab(self._question_input, "提问")

        layout.addWidget(self._tabs)

        # ── 底部菜单栏 ──
        bottom_bar = QHBoxLayout()

        menu_btn = QPushButton("菜单")
        menu_btn.setObjectName("secondary_btn")
        menu_btn.setFixedSize(60, 32)
        menu_btn.clicked.connect(self._show_menu)
        bottom_bar.addWidget(menu_btn)

        bottom_bar.addStretch()

        self._copy_btn = QPushButton("复制答案")
        self._copy_btn.setObjectName("secondary_btn")
        self._copy_btn.clicked.connect(self._copy_latest_answer)
        bottom_bar.addWidget(self._copy_btn)

        layout.addLayout(bottom_bar)

    def _init_tray(self) -> None:
        self._tray = SystemTray(self)
        self._tray.show_action.triggered.connect(self._toggle_visibility)
        self._tray.start_action.triggered.connect(self._toggle_listen)
        self._tray.stop_action.triggered.connect(self._toggle_listen)
        self._tray.quit_action.triggered.connect(self._quit)
        self._tray.show()

    def _connect_signals(self) -> None:
        self.sig_transcript.connect(self._transcript_view.add_segment)
        self.sig_question.connect(self._answer_view.add_question)
        self.sig_answer.connect(self._answer_view.update_answer)
        self.sig_status.connect(self._on_status_changed)
        self.sig_error.connect(self._on_error)
        self.sig_active_qa.connect(self._question_input.add_answer)
        self._question_input.question_submitted.connect(self._on_user_question)
        self._question_input.settings_changed.connect(self._on_qa_settings_changed)
        self._answer_view.copy_to_clipboard.connect(self._copy_text)
        self._answer_view.manual_detect_requested.connect(self._on_manual_detect)
        self._answer_view.manual_question_submitted.connect(self._on_manual_question)
        self._answer_view.force_answer_requested.connect(self._on_force_answer)
        self._sig_hotkey.connect(self._handle_hotkey)

    def _connect_session_callbacks(self) -> None:
        sm = self._session_mgr
        sm.on_transcript_update = lambda seg: self.sig_transcript.emit(seg)
        sm.on_question_detected = lambda q: self.sig_question.emit(q)
        sm.on_answer_ready = lambda q: self.sig_answer.emit(q)
        sm.on_status_changed = lambda s: self.sig_status.emit(s)
        sm.on_error = lambda e: self.sig_error.emit(e)
        sm.on_active_qa_answer = lambda qa: self.sig_active_qa.emit(qa)

        # 初始化提问面板的控件状态
        self._question_input.apply_settings(
            qa_model=self._session_mgr.settings.get("qa_model", "qwen3.5-plus"),
            qa_enable_thinking=self._session_mgr.settings.get("qa_enable_thinking", False),
        )

    def _on_qa_settings_changed(self, key: str, value: object) -> None:
        """提问面板设置变更。"""
        self._session_mgr.settings.set(key, value)

    # ── 控制操作 ──

    def _load_course_history(self) -> None:
        """从历史会话中加载课程名并填充到 ComboBox。"""
        self._course_combo.clear()
        sessions = self._session_mgr.get_history_sessions()
        courses = list(dict.fromkeys(s.course_name for s in sessions if s.course_name))
        self._course_combo.addItems(courses)

    def _toggle_listen(self) -> None:
        if self._session_mgr.is_listening:
            self._session_mgr.stop_session()
            self._listen_btn.setText("开始")
            self._tray.set_listening(False)
        else:
            course = self._course_combo.currentText().strip()
            if not course:
                course, ok = QInputDialog.getText(self, "课程名称", "请输入课程名称:")
                if not ok or not course.strip():
                    return
                self._course_combo.setCurrentText(course)

            # 检查 API Key
            if not self._session_mgr.settings.has_api_key("dashscope_api_key"):
                self._on_error("请先在设置中配置阿里云百炼 API Key")
                self._show_settings()
                return

            success = self._session_mgr.start_session(course)
            if success:
                self._listen_btn.setText("停止")
                self._tray.set_listening(True)

    def _toggle_stay_on_top(self) -> None:
        self._stay_on_top = not self._stay_on_top
        self._pin_btn.setChecked(self._stay_on_top)
        # 使用 Windows API 直接设置 TOPMOST 标志，避免重建窗口导致闪烁
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        hwnd = int(self.winId())
        flag = HWND_TOPMOST if self._stay_on_top else HWND_NOTOPMOST
        ctypes.windll.user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def _copy_latest_answer(self) -> None:
        text = self._answer_view.get_latest_answer()
        if text:
            self._copy_text(text)

    def _copy_text(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self._status_label.setText("已复制到剪贴板")

    def _on_user_question(self, question: str) -> None:
        self._session_mgr.ask_question(question)

    def _on_manual_detect(self) -> None:
        """手动检测问题。"""
        if not self._session_mgr.is_listening:
            self._on_error("请先开始监听后再检测问题")
            return
        self._session_mgr.manual_detect_question()

    def _on_manual_question(self, question: str) -> None:
        """手动输入问题并生成答案。"""
        if not self._session_mgr.is_listening:
            self._on_error("请先开始监听后再提交问题")
            return
        self._session_mgr.submit_question(question)

    def _on_force_answer(self) -> None:
        """强制回答（不管最近内容是否为提问）。"""
        if not self._session_mgr.is_listening:
            self._on_error("请先开始监听后再使用强制回答")
            return
        self._session_mgr.force_answer()

    def _show_menu(self) -> None:
        menu = QMenu(self)

        settings_action = menu.addAction("设置")
        settings_action.triggered.connect(self._show_settings)

        history_action = menu.addAction("历史记录")
        history_action.triggered.connect(self._show_history)

        menu.addSeparator()

        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit)

        menu.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._session_mgr.settings, self)
        if dialog.exec():
            self._session_mgr.refresh_llm()
            self._transcript_view.set_bilingual(
                self._session_mgr.settings.get("bilingual_display", True)
            )

    def _show_speaker_dialog(self) -> None:
        dialog = SpeakerDialog(self._session_mgr.speaker_mgr, self)
        dialog.exec()

    def _show_history(self) -> None:
        dialog = HistoryView(self._session_mgr, self)
        dialog.exec()
        if dialog.resume_session_id is not None:
            self._resume_session(dialog.resume_session_id)

    def _resume_session(self, session_id: int) -> None:
        """续记一个历史会话。"""
        if self._session_mgr.is_listening:
            self._on_error("请先停止当前会话再续记")
            return
        if not self._session_mgr.settings.has_api_key("dashscope_api_key"):
            self._on_error("请先在设置中配置阿里云百炼 API Key")
            self._show_settings()
            return

        # 先把历史片段加载进转写视图
        segments = self._session_mgr.db.get_segments(session_id, final_only=True)
        self._transcript_view.load_history(segments)

        success = self._session_mgr.resume_session(session_id)
        if success:
            session = self._session_mgr.current_session
            if session:
                self._course_combo.setCurrentText(session.course_name)
            self._listen_btn.setText("停止")
            self._tray.set_listening(True)
            # 切到转写 Tab
            self._tabs.setCurrentIndex(0)

    def _mark_teacher(self) -> None:
        # 简化：弹窗让用户输入说话人标签号
        label, ok = QInputDialog.getText(
            self, "标记教师", "输入说话人标签（ASR 返回的编号）:"
        )
        if ok and label.strip():
            self._session_mgr.mark_current_speaker_as_teacher(label.strip())
            self._status_label.setText(f"已将说话人 {label} 标记为教师")

    # ── 快捷键操作（通过 Qt 信号中转到主线程）──

    @pyqtSlot(str)
    def _handle_hotkey(self, action: str) -> None:
        """在主线程中处理快捷键动作。"""
        dispatch = {
            "toggle_listen": self._toggle_listen,
            "manual_question": lambda: self._session_mgr.manual_detect_question(),
            "toggle_window": self._toggle_visibility,
            "copy_answer": self._copy_latest_answer,
            "toggle_answer_mode": lambda: self._answer_view.toggle_latest_answer_mode(),
            "active_question": self._hotkey_focus_question,
            "toggle_llm_filter": self._toggle_llm_filter,
        }
        handler = dispatch.get(action)
        if handler:
            handler()

    def _hotkey_focus_question(self) -> None:
        self.show()
        self.activateWindow()
        self._tabs.setCurrentIndex(2)
        self._question_input.focus_input()

    def _toggle_llm_filter(self) -> None:
        """切换 LLM 过滤模式（只教师 / 全部）。"""
        current = self._session_mgr.settings.llm_filter_teacher_only
        self._session_mgr.settings.set("llm_filter_teacher_only", not current)
        mode = "只教师" if not current else "全部"
        self._status_label.setText(f"LLM 过滤模式: {mode}")

    def hotkey_toggle_listen(self) -> None:
        self._sig_hotkey.emit("toggle_listen")

    def hotkey_manual_question(self) -> None:
        self._sig_hotkey.emit("manual_question")

    def hotkey_toggle_window(self) -> None:
        self._sig_hotkey.emit("toggle_window")

    def hotkey_copy_answer(self) -> None:
        self._sig_hotkey.emit("copy_answer")

    def hotkey_toggle_answer_mode(self) -> None:
        self._sig_hotkey.emit("toggle_answer_mode")

    def hotkey_active_question(self) -> None:
        self._sig_hotkey.emit("active_question")

    def hotkey_toggle_filter(self) -> None:
        self._sig_hotkey.emit("toggle_llm_filter")

    # ── 状态回调 ──

    @pyqtSlot(str)
    def _on_status_changed(self, status: str) -> None:
        self._status_label.setText(status)

    @pyqtSlot(str)
    def _on_error(self, error: str) -> None:
        self._status_label.setText(f"⚠ {error}")
        logger.error(error)

    # ── 窗口事件 ──

    def _restore_geometry(self) -> None:
        """恢复上次关闭时的窗口位置和大小。"""
        settings = QSettings("class_copilot", "main_window")
        geo = settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def closeEvent(self, event: QCloseEvent) -> None:
        # 保存窗口位置大小
        settings = QSettings("class_copilot", "main_window")
        settings.setValue("geometry", self.saveGeometry())
        # 关闭时最小化到托盘而不是退出
        event.ignore()
        self.hide()

    def _quit(self) -> None:
        # 保存窗口位置大小
        settings = QSettings("class_copilot", "main_window")
        settings.setValue("geometry", self.saveGeometry())
        self._session_mgr.cleanup()
        self._tray.hide()
        QApplication.quit()
