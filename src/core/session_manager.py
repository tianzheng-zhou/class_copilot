"""课堂会话管理器 - 核心业务协调层。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

from src.asr.audio_capture import AudioCapture
from src.asr.dashscope_asr import TranscriptResult, create_asr_client
from src.config.settings import Settings
from src.core.speaker_manager import SpeakerManager
from src.core.transcript import TranscriptManager
from src.llm.answer_generator import AnswerGenerator
from src.llm.question_detector import QuestionDetector
from src.llm.qwen_client import QwenClient
from src.llm.translator import Translator
from src.storage.audio_storage import AudioStorage
from src.storage.database import Database
from src.storage.models import (
    ActiveQA,
    ClassSession,
    DetectedQuestion,
    SessionStatus,
    SpeakerRole,
    TranscriptSegment,
)
from src.utils.notifier import notify_question_detected

logger = logging.getLogger(__name__)


class SessionManager:
    """课堂会话管理器，协调所有子系统。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # 初始化数据库
        self.db = Database(settings.db_path)
        self.db.initialize()

        # 初始化存储
        self.audio_storage = AudioStorage(settings.audio_dir)

        # 初始化管理器
        self.transcript_mgr = TranscriptManager(self.db)
        self.speaker_mgr = SpeakerManager(self.db, settings)

        # LLM 客户端（可能为空，需要 API Key）
        self._qwen: QwenClient | None = None
        self._question_detector: QuestionDetector | None = None
        self._answer_generator: AnswerGenerator | None = None
        self._translator: Translator | None = None
        self._init_llm()

        # ASR 客户端
        self._asr = None
        self._audio_capture: AudioCapture | None = None

        # 当前会话状态
        self._session: ClassSession | None = None
        self._is_listening = False

        # 回调
        self.on_transcript_update: Callable[[TranscriptSegment], None] | None = None
        self.on_question_detected: Callable[[DetectedQuestion], None] | None = None
        self.on_answer_ready: Callable[[DetectedQuestion], None] | None = None
        self.on_status_changed: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_active_qa_answer: Callable[[ActiveQA], None] | None = None

    def _init_llm(self) -> None:
        api_key = self.settings.get_api_key(Settings.DASHSCOPE_API_KEY)
        if api_key:
            self._qwen = QwenClient(api_key)
            self._question_detector = QuestionDetector(self._qwen)
            self._answer_generator = AnswerGenerator(self._qwen)
            self._translator = Translator(self._qwen)

    def refresh_llm(self) -> None:
        """API Key 更新后重新初始化 LLM。"""
        self._init_llm()

    # ── 会话生命周期 ──

    def start_session(self, course_name: str) -> bool:
        """开始新的课堂会话。"""
        if self._is_listening:
            return False

        date_str = datetime.now().strftime("%Y-%m-%d")
        self._session = ClassSession(
            course_name=course_name,
            date=date_str,
            status=SessionStatus.RECORDING,
            language=self.settings.language,
        )
        self._session.id = self.db.create_session(self._session)

        # 开始录音
        audio_path = self.audio_storage.start_recording(
            self._session.id, course_name, date_str
        )
        self.db.update_session_audio_path(self._session.id, audio_path)
        self._session.audio_path = audio_path

        # 设置转写管理器
        self.transcript_mgr.set_session(self._session.id)

        # 启动 ASR
        self._start_asr(course_name)

        # 启动音频采集
        self._audio_capture = AudioCapture(
            device_index=self.settings.microphone_index,
            on_audio_chunk=self._on_audio_chunk,
        )
        self._audio_capture.start()

        self._is_listening = True
        if self.on_status_changed:
            self.on_status_changed("正在监听")
        logger.info("课堂会话已开始: %s", course_name)
        return True

    def stop_session(self) -> None:
        """停止当前会话。"""
        if not self._is_listening:
            return

        self._is_listening = False

        # 停止音频采集
        if self._audio_capture:
            self._audio_capture.stop()
            self._audio_capture = None

        # 断开 ASR
        if self._asr:
            self._asr.disconnect()
            self._asr = None

        # 停止录音
        self.audio_storage.stop_recording()

        # 更新会话状态
        if self._session and self._session.id:
            self.db.update_session_status(self._session.id, SessionStatus.STOPPED)

        self.transcript_mgr.clear()
        self._session = None

        if self.on_status_changed:
            self.on_status_changed("已停止")
        logger.info("课堂会话已停止")

    def _start_asr(self, course_name: str) -> None:
        """启动 ASR 连接。"""
        api_key = self.settings.get_api_key(Settings.DASHSCOPE_API_KEY)
        if not api_key:
            if self.on_error:
                self.on_error("阿里云百炼 API Key 未配置")
            return

        self._asr = create_asr_client(
            model=self.settings.asr_model,
            api_key=api_key,
            on_result=self._on_asr_result,
            on_error=self._on_asr_error,
            on_connected=lambda: logger.info("ASR [%s] 已连接", self.settings.asr_model),
            on_disconnected=self._on_asr_disconnected,
        )
        self._asr.connect()

    def _on_audio_chunk(self, pcm_data: bytes) -> None:
        """音频数据回调。"""
        # 写入本地录音
        self.audio_storage.write_chunk(pcm_data)
        # 发送给 ASR
        if self._asr and self._asr.is_connected:
            self._asr.feed_audio(pcm_data)

    def _on_asr_result(self, result: TranscriptResult) -> None:
        """ASR 转写结果回调。"""
        segment = TranscriptSegment(
            speaker_label="",
            speaker_role=SpeakerRole.UNKNOWN,
            text=result.text,
            start_time_ms=result.start_ms,
            end_time_ms=result.end_ms,
            is_final=result.is_final,
        )

        # 英文翻译
        if (self.settings.language == "en" and self._translator
                and result.is_final and self.settings.get("translation_enabled", True)):
            segment.translation = self._translator.translate_to_chinese(result.text)

        segment = self.transcript_mgr.add_segment(segment)

        if self.on_transcript_update:
            self.on_transcript_update(segment)

        # 自动问题检测（仅处理最终结果）
        if result.is_final:
            self._auto_detect_question(segment)

    def _on_asr_error(self, error: str) -> None:
        logger.error("ASR 错误: %s", error)
        if self.on_error:
            self.on_error(f"语音识别错误: {error}")

    def _on_asr_disconnected(self) -> None:
        if self._is_listening:
            logger.warning("ASR 意外断开，尝试重连...")
            if self.on_status_changed:
                self.on_status_changed("正在重连...")
            if self._session:
                threading.Timer(2.0, lambda: self._start_asr(self._session.course_name)).start()

    # ── 问题检测 ──

    def _auto_detect_question(self, segment: TranscriptSegment) -> None:
        """自动检测问题（在后台线程中运行）。"""
        if not self._question_detector:
            return

        # 根据过滤模式决定是否检测
        if self.settings.llm_filter_teacher_only and segment.speaker_role != SpeakerRole.TEACHER:
            return

        def _detect():
            context = self.transcript_mgr.get_context_text(
                teacher_only=self.settings.llm_filter_teacher_only
            )
            result = self._question_detector.detect(segment.text, context)
            if result and result.get("is_question") and result.get("confidence", 0) >= 0.7:
                question_text = result.get("question_text", segment.text)
                self._handle_detected_question(question_text, source="auto")

        threading.Thread(target=_detect, daemon=True).start()

    def manual_detect_question(self) -> None:
        """手动触发问题检测。"""
        if not self._question_detector:
            return

        recent_text = self.transcript_mgr.get_recent_text(5)
        if not recent_text:
            return

        def _detect():
            context = self.transcript_mgr.get_context_text(teacher_only=False)
            result = self._question_detector.detect(recent_text, context)
            if result and result.get("is_question"):
                question_text = result.get("question_text", recent_text)
                self._handle_detected_question(question_text, source="manual")

        threading.Thread(target=_detect, daemon=True).start()

    def _handle_detected_question(self, question_text: str, source: str) -> None:
        """处理检测到的问题：通知 + 生成答案。"""
        if not self._session or not self._answer_generator:
            return

        question = DetectedQuestion(
            session_id=self._session.id,
            question_text=question_text,
            source=source,
        )
        question.id = self.db.add_question(question)

        # Windows 通知
        notify_question_detected(question_text)

        if self.on_question_detected:
            self.on_question_detected(question)

        # 生成答案
        def _generate():
            context = self.transcript_mgr.get_context_text(
                teacher_only=self.settings.llm_filter_teacher_only
            )
            concise, detailed = self._answer_generator.generate(
                question=question_text,
                context=context,
                course_name=self._session.course_name if self._session else "",
                language=self.settings.language,
            )
            question.concise_answer = concise
            question.detailed_answer = detailed
            self.db.update_question_answers(question.id, concise, detailed)

            if self.on_answer_ready:
                self.on_answer_ready(question)

        threading.Thread(target=_generate, daemon=True).start()

    # ── 主动问答 ──

    def ask_question(self, user_question: str) -> None:
        """用户主动提问。"""
        if not self._qwen or not self._session:
            return

        qa_model = self.settings.get("qa_model", "qwen3.5-plus")
        enable_thinking = self.settings.get("qa_enable_thinking", False)

        def _ask():
            context = self.transcript_mgr.get_context_text(teacher_only=False)
            system_prompt = (
                f"你是一个课堂学习助手。学生正在上「{self._session.course_name}」课程。"
                "请根据课堂内容回答学生的问题，帮助学生理解课堂知识。"
                "如果问题与课堂内容无关，也可以尽力回答。"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"课堂内容：\n{context[-3000:]}\n\n我的问题：{user_question}"},
            ]

            answer = self._qwen.chat(
                messages, model=qa_model, temperature=0.7,
                max_tokens=2048, enable_thinking=enable_thinking,
            )

            qa = ActiveQA(
                session_id=self._session.id,
                question=user_question,
                answer=answer,
            )
            qa.id = self.db.add_active_qa(qa)

            if self.on_active_qa_answer:
                self.on_active_qa_answer(qa)

        threading.Thread(target=_ask, daemon=True).start()

    # ── 声纹管理 ──

    def mark_current_speaker_as_teacher(self, speaker_label: str) -> None:
        self.speaker_mgr.mark_speaker_as_teacher(speaker_label)

    # ── 数据导出 ──

    def export_session_markdown(self, session_id: int) -> str:
        """导出会话为 Markdown。"""
        session = self.db.get_session(session_id)
        if not session:
            return ""

        segments = self.db.get_segments(session_id, final_only=True)
        questions = self.db.get_questions(session_id)
        qas = self.db.get_active_qas(session_id)

        lines = [
            f"# 课堂记录 - {session.course_name}",
            f"**日期**: {session.date}",
            f"**语言**: {session.language}",
            "",
            "## 转写记录",
            "",
        ]

        for seg in segments:
            role_label = "🎓教师" if seg.speaker_role == SpeakerRole.TEACHER else f"👤{seg.speaker_label}"
            lines.append(f"**{role_label}**: {seg.text}")
            if seg.translation:
                lines.append(f"  *翻译: {seg.translation}*")
            lines.append("")

        if questions:
            lines.append("## 课堂提问与答案")
            lines.append("")
            for q in questions:
                lines.append(f"### ❓ {q.question_text}")
                lines.append(f"**来源**: {'自动检测' if q.source == 'auto' else '手动标记'}")
                if q.concise_answer:
                    lines.append(f"\n**简洁版**: {q.concise_answer}")
                if q.detailed_answer:
                    lines.append(f"\n**展开版**: {q.detailed_answer}")
                lines.append("")

        if qas:
            lines.append("## 主动提问记录")
            lines.append("")
            for qa in qas:
                lines.append(f"**问**: {qa.question}")
                lines.append(f"**答**: {qa.answer}")
                lines.append("")

        return "\n".join(lines)

    # ── 状态查询 ──

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    @property
    def current_session(self) -> ClassSession | None:
        return self._session

    def get_history_sessions(self) -> list[ClassSession]:
        return self.db.list_sessions()

    def resume_session(self, session_id: int) -> bool:
        """续记：恢复一个已停止的历史会话。"""
        if self._is_listening:
            return False

        session = self.db.get_session(session_id)
        if not session:
            return False

        api_key = self.settings.get_api_key(Settings.DASHSCOPE_API_KEY)
        if not api_key:
            if self.on_error:
                self.on_error("阿里云百炼 API Key 未配置")
            return False

        # 恢复会话对象
        self._session = session
        self._session.status = SessionStatus.RECORDING
        self.db.update_session_status(session_id, SessionStatus.RECORDING)

        # 从数据库加载历史转写内容到内存，恢复 LLM 上下文
        self.transcript_mgr.load_from_db(session_id)

        # 续录：生成新的分段音频文件
        self.audio_storage.start_recording_continuation(
            session_id, session.course_name, session.date
        )

        # 启动 ASR
        self._start_asr(session.course_name)

        # 启动音频采集
        self._audio_capture = AudioCapture(
            device_index=self.settings.microphone_index,
            on_audio_chunk=self._on_audio_chunk,
        )
        self._audio_capture.start()

        self._is_listening = True
        if self.on_status_changed:
            self.on_status_changed("正在续记")
        logger.info("续记会话已开始: %s (id=%d)", session.course_name, session_id)
        return True

    def cleanup(self) -> None:
        """清理资源。"""
        self.stop_session()
        self.db.close()
