"""会话管理器 - 协调所有服务的中枢"""

import asyncio
import time
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from class_copilot.config import settings
from class_copilot.database import async_session
from class_copilot.models.models import (
    Course, Session, Recording, Transcription, Question, Answer,
)
from class_copilot.services.audio_service import AudioService
from class_copilot.services.asr_service import RealtimeASRService
from class_copilot.services.doubao_asr_service import DoubaoRealtimeASRService
from class_copilot.services.llm_service import LLMService
from class_copilot.services.question_detector import QuestionDetector
from class_copilot.services.refinement_service import RefinementService
from class_copilot.services.doubao_refinement_service import DoubaoRefinementService
from class_copilot.services.notification_service import NotificationService
from class_copilot.services.hotkey_service import HotkeyService
from class_copilot.services.tray_service import update_icon_recording, set_main_loop
from class_copilot.logger import asr_logger, llm_logger, refinement_logger


class SessionManager:
    """会话管理器 - 单例"""

    def __init__(self):
        self.audio_service = AudioService()
        self.asr_service = self._create_asr_service()
        self.llm_service = LLMService()
        self.question_detector = QuestionDetector(self.llm_service)
        self.refinement_service = self._create_refinement_service()
        self.notification_service = NotificationService()
        self.hotkey_service = HotkeyService()

        # 当前状态
        self.current_session_id: str | None = None
        self.current_course_name: str = ""
        self.current_recording_id: str | None = None
        self.is_listening = False
        self.status: str = "ready"  # ready / listening / stopped / reconnecting

        # WebSocket 广播队列
        self.ws_broadcast_queue: asyncio.Queue = asyncio.Queue()

        # ASR处理任务
        self._asr_feed_task: asyncio.Task | None = None
        self._asr_process_task: asyncio.Task | None = None
        self._detection_task: asyncio.Task | None = None

        # 转写序号
        self._transcription_seq = 0

        # 录音开始时的 epoch 时间（用于将相对时间转为绝对时间）
        self._recording_started_at: float = 0

    async def initialize(self):
        """初始化服务"""
        loop = asyncio.get_event_loop()
        set_main_loop(loop)
        self.hotkey_service.set_loop(loop)

        # 注册快捷键
        self.hotkey_service.register_hotkeys({
            "toggle_listening": self.toggle_listening,
            "manual_detect": self.manual_detect,
            "toggle_filter_mode": self.toggle_filter_mode,
            "manual_refine": self.manual_refine,
        })

        logger.info("会话管理器初始化完成")

    @staticmethod
    def _create_asr_service():
        """根据配置创建实时 ASR 服务"""
        if settings.asr_provider == "doubao":
            return DoubaoRealtimeASRService()
        return RealtimeASRService()

    @staticmethod
    def _create_refinement_service():
        """根据配置创建精修 ASR 服务"""
        if settings.refinement_provider == "doubao":
            return DoubaoRefinementService()
        return RefinementService()

    async def start_listening(self, course_name: str = ""):
        """开始监听（录音+ASR）"""
        if self.is_listening:
            logger.warning("已在监听中")
            return

        # 根据当前配置(重新)创建 ASR / 精修服务，允许用户在会话间切换提供商
        self.asr_service = self._create_asr_service()
        self.refinement_service = self._create_refinement_service()

        self.current_course_name = course_name
        self.status = "listening"
        self.is_listening = True
        self._transcription_seq = 0
        self._recording_started_at = time.time()

        # 获取或创建课程
        course_id = await self._get_or_create_course(course_name)

        # 创建会话
        async with async_session() as db:
            session = Session(
                course_id=course_id,
                date=datetime.now().strftime("%Y-%m-%d"),
                status="active",
                refinement_strategy=settings.refinement_strategy,
            )
            db.add(session)
            await db.commit()
            self.current_session_id = session.id

        # 获取热词
        hot_words = await self._get_hot_words(course_id)

        # 启动录音
        mp3_path = await self.audio_service.start_recording(self.current_session_id)

        # 记录录音
        async with async_session() as db:
            recording = Recording(
                session_id=self.current_session_id,
                file_path=mp3_path,
            )
            db.add(recording)
            await db.commit()
            self.current_recording_id = recording.id

        # 启动ASR
        try:
            await self.asr_service.start(hot_words=hot_words, language=settings.language)
        except Exception as e:
            logger.error("ASR 启动失败: {}", e)
            self.is_listening = False
            self.status = "error"
            await self.audio_service.stop_recording()
            await self._broadcast("error", {"message": f"ASR 启动失败: {e}"})
            await self._broadcast("status", {"status": "error", "session_id": self.current_session_id})
            return

        # 启动后台任务
        self._asr_feed_task = asyncio.create_task(self._feed_audio_to_asr())
        self._asr_process_task = asyncio.create_task(self._process_asr_results())
        self._detection_task = asyncio.create_task(self._auto_detect_loop())

        update_icon_recording(True)
        await self._broadcast("status", {"status": "listening", "session_id": self.current_session_id})
        logger.info("开始监听: session={}, course={}", self.current_session_id, course_name)

    async def stop_listening(self):
        """停止监听"""
        if not self.is_listening:
            return

        self.is_listening = False
        self.status = "stopped"

        # 取消后台任务
        for task in [self._asr_feed_task, self._asr_process_task, self._detection_task]:
            if task:
                task.cancel()

        # 停止ASR
        await self.asr_service.stop()

        # 停止录音
        recording_info = await self.audio_service.stop_recording()

        # 更新录音信息
        if recording_info and self.current_recording_id:
            async with async_session() as db:
                from sqlalchemy import update as sql_update
                await db.execute(
                    sql_update(Recording)
                    .where(Recording.id == self.current_recording_id)
                    .values(
                        duration_seconds=recording_info["duration_seconds"],
                        file_size_bytes=recording_info["file_size_bytes"],
                        ended_at=datetime.utcnow(),
                    )
                )
                # 更新会话状态
                await db.execute(
                    sql_update(Session)
                    .where(Session.id == self.current_session_id)
                    .values(status="stopped", ended_at=datetime.utcnow())
                )
                await db.commit()

        update_icon_recording(False)
        await self._broadcast("status", {"status": "stopped", "session_id": self.current_session_id})
        logger.info("停止监听: session={}", self.current_session_id)

        # 课后精修
        if settings.enable_refinement and settings.refinement_strategy == "post":
            asyncio.create_task(self._start_post_refinement())

    async def toggle_listening(self):
        """切换监听状态"""
        if self.is_listening:
            await self.stop_listening()
        else:
            await self.start_listening(self.current_course_name)

    # ──────────── 音频→ASR 流 ────────────

    async def _feed_audio_to_asr(self):
        """将录音数据发送到ASR，ASR断开时自动重连"""
        reconnect_attempts = 0
        max_reconnect_rounds = 3
        try:
            while self.is_listening:
                # 检测 ASR 是否断开
                if self.asr_service.is_disconnected:
                    # 不可恢复的错误（如 401 认证失败），直接停止
                    if self.asr_service.is_permanent_error:
                        asr_logger.error("ASR 认证失败 (API Key 无效)，停止监听")
                        await self._broadcast("notification", {
                            "type": "error",
                            "message": "ASR 认证失败，请检查 API Key 配置",
                        })
                        await self.stop_listening()
                        return

                    reconnect_attempts += 1
                    if reconnect_attempts > max_reconnect_rounds:
                        asr_logger.error("ASR 多次重连均失败，停止监听")
                        await self._broadcast("notification", {
                            "type": "error",
                            "message": "ASR 连接反复断开，已停止监听",
                        })
                        await self.stop_listening()
                        return

                    asr_logger.warning("检测到ASR断开，尝试重连 ({}/{})...",
                                       reconnect_attempts, max_reconnect_rounds)
                    success = await self._reconnect_asr()
                    if not success:
                        return
                    continue

                # 连接正常时重置计数
                reconnect_attempts = 0

                try:
                    audio_data = await asyncio.wait_for(
                        self.audio_service.audio_queue.get(), timeout=1.0
                    )
                    await self.asr_service.send_audio(audio_data)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            asr_logger.error("音频→ASR流异常: {}", e)

    async def _reconnect_asr(self, max_retries: int = 3) -> bool:
        """重连 ASR 服务，返回是否成功"""
        await self.asr_service.stop()

        # 清空积压的音频数据
        while not self.audio_service.audio_queue.empty():
            try:
                self.audio_service.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        course_id = await self._get_or_create_course(self.current_course_name)
        hot_words = await self._get_hot_words(course_id)

        for attempt in range(max_retries):
            try:
                await self.asr_service.start(hot_words=hot_words, language=settings.language)
                # 等待确认连接稳定（401等错误会在连接后立即异步到达）
                await asyncio.sleep(1.0)
                if self.asr_service.is_disconnected:
                    asr_logger.warning("ASR 重连后立即断开 ({}/{})", attempt + 1, max_retries)
                    await self.asr_service.stop()
                    continue

                asr_logger.info("ASR 重连成功 (第{}次尝试)", attempt + 1)
                await self._broadcast("notification", {"type": "info", "message": "ASR已自动重连"})
                return True
            except Exception as e:
                asr_logger.error("ASR 重连失败 ({}/{}): {}", attempt + 1, max_retries, e)
                await asyncio.sleep(2 ** attempt)

        asr_logger.error("ASR 重连全部失败，停止监听")
        await self._broadcast("notification", {"type": "error", "message": "ASR连接断开且重连失败，已停止监听"})
        await self.stop_listening()
        return False

    async def _process_asr_results(self):
        """处理ASR结果，保存并广播"""
        try:
            while self.is_listening:
                try:
                    result = await asyncio.wait_for(
                        self.asr_service.result_queue.get(), timeout=1.0
                    )
                    await self._handle_asr_result(result)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            asr_logger.error("处理ASR结果异常: {}", e)

    async def _handle_asr_result(self, result: dict):
        """处理单条ASR结果"""
        text = result.get("text", "")
        is_final = result.get("is_final", False)
        speaker_label = result.get("speaker_label", "UNKNOWN")

        # 判断是否是教师（仅在有有效说话人标签时查询）
        is_teacher = False
        if speaker_label != "UNKNOWN":
            is_teacher = await self._check_is_teacher(speaker_label)

        if is_final:
            self._transcription_seq += 1

            # 保存到数据库
            async with async_session() as db:
                trans = Transcription(
                    session_id=self.current_session_id,
                    recording_id=self.current_recording_id,
                    start_time=result.get("start_time", 0),
                    end_time=result.get("end_time", 0),
                    sequence=self._transcription_seq,
                    speaker_label=speaker_label,
                    speaker_role="teacher" if is_teacher else "unknown",
                    is_teacher=is_teacher,
                    realtime_text=text,
                    is_final=True,
                    language=settings.language,
                )
                db.add(trans)
                await db.commit()
                trans_id = trans.id

            # 添加到问题检测缓冲
            self.question_detector.add_transcription({
                "text": text,
                "is_teacher": is_teacher,
                "is_final": True,
                "speaker_label": speaker_label,
            })

        # 广播到前端（将相对时间转为绝对 epoch 时间）
        rel_start = result.get("start_time", 0)
        rel_end = result.get("end_time", 0)
        abs_start = (self._recording_started_at + rel_start) if self._recording_started_at and rel_start else 0
        abs_end = (self._recording_started_at + rel_end) if self._recording_started_at and rel_end else 0
        await self._broadcast("transcription", {
            "text": text,
            "is_final": is_final,
            "speaker_label": speaker_label,
            "is_teacher": is_teacher,
            "start_time": abs_start,
            "end_time": abs_end,
            "sentence_id": result.get("sentence_id", 0),
        })

    # ──────────── 问题检测 ────────────

    async def _auto_detect_loop(self):
        """自动问题检测循环"""
        try:
            while self.is_listening:
                await asyncio.sleep(3)  # 每3秒检测一次
                if not self.is_listening:
                    break

                result = await self.question_detector.detect(
                    course_name=self.current_course_name,
                    language=settings.language,
                    filter_mode=settings.llm_filter_mode,
                )

                if result:
                    await self._handle_detected_question(result, "auto")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            llm_logger.error("自动检测循环异常: {}", e)

    async def manual_detect(self):
        """手动触发问题检测"""
        result = await self.question_detector.detect(
            course_name=self.current_course_name,
            language=settings.language,
            filter_mode=settings.llm_filter_mode,
            force=True,
        )
        if result:
            await self._handle_detected_question(result, "manual")
        else:
            await self._broadcast("info", {"message": "未检测到问题"})

    async def _handle_detected_question(self, detection: dict, source: str):
        """处理检测到的问题：保存、通知、生成答案"""
        question_text = detection["question"]
        confidence = detection["confidence"]
        context = detection.get("context", "")

        # 保存问题
        async with async_session() as db:
            question = Question(
                session_id=self.current_session_id,
                question_text=question_text,
                source=source,
                confidence=confidence,
                context_text=context,
            )
            db.add(question)
            await db.commit()
            question_id = question.id

        # 广播问题
        await self._broadcast("question_detected", {
            "question_id": question_id,
            "question": question_text,
            "source": source,
            "confidence": confidence,
        })

        # 发送 Windows 通知
        asyncio.create_task(self.notification_service.notify_question(question_text))

        # 并行生成简洁版和展开版答案
        if settings.enable_brief_answer:
            asyncio.create_task(
                self._generate_and_save_answer(question_id, question_text, context, "brief")
            )
        if settings.enable_detailed_answer:
            asyncio.create_task(
                self._generate_and_save_answer(question_id, question_text, context, "detailed")
            )

    async def _generate_and_save_answer(
        self, question_id: str, question_text: str, context: str, answer_type: str
    ):
        """生成并保存答案"""
        # 通知前端开始生成
        await self._broadcast("answer_generating", {
            "question_id": question_id,
            "answer_type": answer_type,
            "model": settings.auto_answer_model,
        })

        # 流式生成
        full_answer = ""
        async for chunk in self.llm_service.generate_answer(
            question=question_text,
            context=context,
            course_name=self.current_course_name,
            answer_type=answer_type,
            language=settings.language,
        ):
            full_answer += chunk
            await self._broadcast("answer_chunk", {
                "question_id": question_id,
                "answer_type": answer_type,
                "chunk": chunk,
                "full_text": full_answer,
            })

        # 保存到数据库
        async with async_session() as db:
            answer = Answer(
                question_id=question_id,
                answer_type=answer_type,
                content=full_answer,
                language=settings.language,
            )
            db.add(answer)
            await db.commit()

        await self._broadcast("answer_complete", {
            "question_id": question_id,
            "answer_type": answer_type,
            "content": full_answer,
        })

    # ──────────── 主动提问 ────────────

    async def chat(self, user_question: str, model: str | None = None, think_mode: bool = False):
        """处理主动提问"""
        from class_copilot.models.models import ChatMessage

        if not self.current_session_id:
            await self._broadcast("error", {"message": "请先开始会话"})
            return

        # 保存用户消息
        async with async_session() as db:
            msg = ChatMessage(
                session_id=self.current_session_id,
                role="user",
                content=user_question,
            )
            db.add(msg)
            await db.commit()
            user_msg_id = msg.id

        # 获取课堂上下文（使用最优版本）
        context = await self._get_session_context()

        # 解析模型别名
        if model == "fast":
            use_model = settings.llm_model_fast
        elif model == "quality":
            use_model = settings.llm_model_quality
        else:
            use_model = model

        # 流式生成回答
        full_response = ""
        async for chunk in self.llm_service.chat(
            user_question=user_question,
            context=context,
            course_name=self.current_course_name,
            model=use_model,
            think_mode=think_mode,
        ):
            full_response += chunk
            await self._broadcast("chat_chunk", {
                "chunk": chunk,
                "full_text": full_response,
            })

        # 保存AI回答
        async with async_session() as db:
            msg = ChatMessage(
                session_id=self.current_session_id,
                role="assistant",
                content=full_response,
                model_used=use_model or settings.llm_model_quality,
                think_mode=think_mode,
            )
            db.add(msg)
            await db.commit()

        await self._broadcast("chat_complete", {"content": full_response})

    # ──────────── 精修 ────────────

    async def _start_post_refinement(self):
        """课后精修"""
        if not self.current_session_id:
            return

        session_id = self.current_session_id
        refinement_logger.info("开始课后精修: {}", session_id)
        await self._broadcast("refinement_status", {"status": "in_progress", "progress": 0, "session_id": session_id})

        async with async_session() as db:
            result = await db.execute(
                select(Recording).where(Recording.session_id == session_id)
            )
            recordings = result.scalars().all()

        paths = [r.file_path for r in recordings if Path(r.file_path).exists()]
        if not paths:
            refinement_logger.warning("无可用录音文件")
            return

        hot_words = ""
        async with async_session() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                result2 = await db.execute(
                    select(Course).where(Course.id == session.course_id)
                )
                course = result2.scalar_one_or_none()
                if course:
                    hot_words = course.hot_words or ""

        async def progress_callback(sid, progress, result, path):
            # 保存精修结果到数据库
            if result:
                await self._save_refined_results(sid, result)
            await self._broadcast("refinement_status", {
                "status": "in_progress",
                "progress": progress,
                "session_id": sid,
            })

        await self.refinement_service.start_post_session_refinement(
            session_id=session_id,
            recording_paths=paths,
            hot_words=hot_words,
            language=settings.language,
            progress_callback=progress_callback,
        )

        # 更新会话精修状态
        async with async_session() as db:
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.refinement_status = "completed"
                session.refinement_progress = 1.0
                await db.commit()

        await self._broadcast("refinement_status", {"status": "completed", "progress": 1.0, "session_id": session_id})

    async def _save_refined_results(self, session_id: str, refined_segments: list[dict]):
        """将精修结果保存到对应的 Transcription 记录"""
        if not refined_segments:
            return

        async with async_session() as db:
            result = await db.execute(
                select(Transcription)
                .where(Transcription.session_id == session_id, Transcription.is_final == True)
                .order_by(Transcription.start_time)
            )
            originals = result.scalars().all()

            if not originals:
                # 无原始记录 → 直接创建精修记录
                for i, seg in enumerate(refined_segments):
                    trans = Transcription(
                        session_id=session_id,
                        start_time=seg["start_time"],
                        end_time=seg["end_time"],
                        sequence=i + 1,
                        realtime_text="",
                        refined_text=seg["text"],
                        is_final=True,
                        refinement_status="refined",
                        refined_at=datetime.utcnow(),
                    )
                    db.add(trans)
                await db.commit()
                return

            # 贪心 1:1 匹配：每个精修片段只分配给重叠最大的一个原始记录
            # 构建所有 (overlap, seg_idx, orig) 候选对
            matches = []
            for seg_idx, seg in enumerate(refined_segments):
                for orig in originals:
                    overlap_start = max(seg["start_time"], orig.start_time)
                    overlap_end = min(seg["end_time"], orig.end_time)
                    overlap = max(0, overlap_end - overlap_start)
                    if overlap > 0:
                        matches.append((overlap, seg_idx, orig))

            # 按重叠量降序，贪心分配
            matches.sort(key=lambda x: x[0], reverse=True)
            used_seg_idxs: set[int] = set()
            used_orig_ids: set[str] = set()

            for overlap, seg_idx, orig in matches:
                if seg_idx in used_seg_idxs or orig.id in used_orig_ids:
                    continue
                orig.refined_text = refined_segments[seg_idx]["text"]
                orig.refinement_status = "refined"
                orig.refined_at = datetime.utcnow()
                used_seg_idxs.add(seg_idx)
                used_orig_ids.add(orig.id)

            # 未匹配到原始记录的精修片段 → 创建新记录
            max_seq = max(o.sequence for o in originals) if originals else 0
            for seg_idx, seg in enumerate(refined_segments):
                if seg_idx not in used_seg_idxs:
                    max_seq += 1
                    trans = Transcription(
                        session_id=session_id,
                        start_time=seg["start_time"],
                        end_time=seg["end_time"],
                        sequence=max_seq,
                        realtime_text="",
                        refined_text=seg["text"],
                        is_final=True,
                        refinement_status="refined",
                        refined_at=datetime.utcnow(),
                    )
                    db.add(trans)

            await db.commit()

        refinement_logger.debug("已保存精修结果: session={}, 精修片段数={}", session_id, len(refined_segments))

    async def manual_refine(self):
        """手动触发精修"""
        if self.current_session_id:
            asyncio.create_task(self._start_post_refinement())

    # ──────────── 辅助方法 ────────────

    async def toggle_filter_mode(self):
        """切换 LLM 输入过滤模式"""
        if settings.llm_filter_mode == "teacher_only":
            settings.llm_filter_mode = "all"
        else:
            settings.llm_filter_mode = "teacher_only"

        await self._broadcast("filter_mode", {"mode": settings.llm_filter_mode})
        logger.info("LLM 过滤模式切换为: {}", settings.llm_filter_mode)

    async def _get_or_create_course(self, name: str) -> str:
        """获取或创建课程"""
        effective_name = name or "未命名课程"
        async with async_session() as db:
            result = await db.execute(select(Course).where(Course.name == effective_name))
            course = result.scalar_one_or_none()
            if course:
                return course.id

            course = Course(name=effective_name, language=settings.language)
            db.add(course)
            await db.commit()
            return course.id

    async def _get_hot_words(self, course_id: str) -> str:
        """获取课程热词"""
        async with async_session() as db:
            result = await db.execute(select(Course).where(Course.id == course_id))
            course = result.scalar_one_or_none()
            return course.hot_words if course else ""

    async def _check_is_teacher(self, speaker_label: str) -> bool:
        """检查说话人是否是教师"""
        if not self.current_session_id:
            return False

        async with async_session() as db:
            from class_copilot.models.models import Voiceprint
            result = await db.execute(
                select(Voiceprint).where(Voiceprint.speaker_label == speaker_label)
            )
            vp = result.scalar_one_or_none()
            return vp is not None

    async def _get_session_context(self, max_chars: int = 6000) -> str:
        """获取当前会话的上下文文本（使用最优版本）"""
        if not self.current_session_id:
            return ""

        async with async_session() as db:
            result = await db.execute(
                select(Transcription)
                .where(Transcription.session_id == self.current_session_id)
                .where(Transcription.is_final == True)
                .order_by(Transcription.sequence)
            )
            transcriptions = result.scalars().all()

        lines = []
        total = 0
        for t in reversed(transcriptions):
            text = t.best_text
            label = t.speaker_label
            line = f"[{label}] {text}"
            if total + len(line) > max_chars:
                break
            lines.insert(0, line)
            total += len(line)

        return "\n".join(lines)

    async def _broadcast(self, msg_type: str, data: dict):
        """广播消息到 WebSocket"""
        await self.ws_broadcast_queue.put({"type": msg_type, "data": data})


# 全局单例
session_manager = SessionManager()
