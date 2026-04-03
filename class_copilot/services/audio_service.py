"""音频采集服务 - 使用 sounddevice 采集并编码为 MP3，支持系统音频回环采集"""

import asyncio
import threading
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import sounddevice as sd
import lameenc

from loguru import logger

from class_copilot.config import settings
from class_copilot.logger import asr_logger

# soundcard 仅在 Windows 上用于系统音频回环采集
try:
    import soundcard as sc
    _HAS_SOUNDCARD = True
except ImportError:
    _HAS_SOUNDCARD = False


class AudioService:
    """音频采集与录音管理"""

    def __init__(self):
        self.is_recording = False
        self.sample_rate = settings.sample_rate
        self.channels = settings.channels
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self.mp3_encoder = None
        self.mp3_file = None
        self.mp3_path: str | None = None
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._start_time: float = 0
        self._device_index: int | None = None

        # 系统音频回环 (loopback)
        self._loopback_mode: bool = False
        self._loopback_device_id: str | None = None  # soundcard speaker id
        self._loopback_thread: threading.Thread | None = None

        # 麦克风监控
        self._monitor_stream = None
        self._monitor_loop: asyncio.AbstractEventLoop | None = None
        self._monitor_callback = None
        self._monitor_loopback_thread: threading.Thread | None = None
        self.is_monitoring = False

    def list_devices(self) -> dict:
        """列出所有可用的音频输入设备（Windows 上只返回 WASAPI 设备以避免重复）"""
        import platform
        devices = sd.query_devices()
        input_devices = []

        # Windows 上只保留 WASAPI 主机 API 的设备，避免同一物理设备重复出现
        wasapi_device_indices = None
        if platform.system() == "Windows":
            try:
                hostapis = sd.query_hostapis()
                for api in hostapis:
                    if "WASAPI" in api["name"]:
                        wasapi_device_indices = set(api["devices"])
                        break
            except Exception:
                pass

        for i, d in enumerate(devices):
            if d["max_input_channels"] <= 0:
                continue
            if wasapi_device_indices is not None and i not in wasapi_device_indices:
                continue
            input_devices.append({
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "sample_rate": d["default_samplerate"],
                "is_default": i == sd.default.device[0],
            })

        return {"devices": input_devices, "current_device": self._device_index}

    def list_loopback_devices(self) -> dict:
        """列出可用的系统音频输出设备（用于回环采集）"""
        if not _HAS_SOUNDCARD:
            return {"devices": [], "current_device": None, "available": False}

        loopback_devices = []
        try:
            default_speaker = sc.default_speaker()
            default_id = default_speaker.id if default_speaker else None
            for speaker in sc.all_speakers():
                loopback_devices.append({
                    "id": speaker.id,
                    "name": speaker.name,
                    "is_default": speaker.id == default_id,
                })
        except Exception as e:
            logger.warning("列出回环设备失败: {}", e)

        return {
            "devices": loopback_devices,
            "current_device": self._loopback_device_id,
            "available": True,
        }

    @property
    def loopback_mode(self) -> bool:
        return self._loopback_mode

    def set_audio_source(self, source: str, device_id: str | int | None = None):
        """设置音频源类型和设备。

        Args:
            source: "microphone" 或 "loopback"
            device_id: 麦克风为 int 设备索引，回环为 str 设备 ID
        """
        if source == "loopback":
            self._loopback_mode = True
            self._loopback_device_id = str(device_id) if device_id is not None else None
            self._device_index = None
            logger.info("音频源: 系统声音回环, 设备={}", self._loopback_device_id)
        else:
            self._loopback_mode = False
            self._loopback_device_id = None
            self._device_index = int(device_id) if device_id is not None else None
            logger.info("音频源: 麦克风, 设备={}", self._device_index)

    def set_device(self, device_index: int | None):
        """设置音频输入设备"""
        self._device_index = device_index
        logger.info("设置音频设备: {}", device_index)

    def _get_monitor_stream_config(self) -> dict:
        """根据当前设备生成更稳妥的监控流配置。"""
        sample_rate = self.sample_rate
        channels = self.channels

        try:
            device_index = self._device_index
            if device_index is None:
                default_device = sd.default.device[0]
                if default_device is not None and default_device >= 0:
                    device_index = int(default_device)

            if device_index is not None:
                device_info = sd.query_devices(device_index, "input")
                if device_info["max_input_channels"] <= 0:
                    raise ValueError("所选设备不支持音频输入")

                channels = min(self.channels, int(device_info["max_input_channels"]))
                sample_rate = int(device_info.get("default_samplerate") or self.sample_rate)
        except Exception as e:
            logger.warning("读取麦克风监控设备配置失败，回退到默认参数: {}", e)

        return {
            "samplerate": sample_rate,
            "channels": channels,
            "dtype": "int16",
            "blocksize": int(sample_rate * 0.05),
            "device": self._device_index,
            "callback": self._monitor_audio_callback,
        }

    async def start_recording(self, session_id: str, sequence: int = 1) -> str:
        """开始录音，返回 MP3 文件路径"""
        if self.is_recording:
            logger.warning("已在录音中，忽略重复启动")
            return self.mp3_path

        self._loop = asyncio.get_event_loop()

        # 创建 MP3 文件
        recordings_dir = Path(settings.data_dir) / "recordings"
        recordings_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.mp3_path = str(recordings_dir / f"{session_id}_{date_str}_{sequence}.mp3")

        # 初始化 MP3 编码器
        self.mp3_encoder = lameenc.Encoder()
        self.mp3_encoder.set_bit_rate(128)
        self.mp3_encoder.set_in_sample_rate(self.sample_rate)
        self.mp3_encoder.set_channels(self.channels)
        self.mp3_encoder.set_quality(2)
        self.mp3_file = open(self.mp3_path, "wb")

        self._start_time = time.time()
        self.is_recording = True

        if self._loopback_mode:
            # 系统音频回环采集（使用 soundcard）
            self._start_loopback_stream()
        else:
            # 麦克风采集（使用 sounddevice）
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=int(self.sample_rate * 0.1),  # 100ms 块
                device=self._device_index,
                callback=self._audio_callback,
            )
            self._stream.start()
        asr_logger.info("录音开始 ({}): {}", "回环" if self._loopback_mode else "麦克风", self.mp3_path)
        return self.mp3_path

    # ── 系统声音回环采集 ──

    def _get_loopback_speaker(self):
        """获取回环录音对象（loopback microphone）

        soundcard 中 Speaker 对象没有 recorder 方法，需要通过
        get_microphone(include_loopback=True) 获取对应的回环麦克风。
        返回的对象具有 recorder() 和 name 属性。
        """
        if not _HAS_SOUNDCARD:
            raise RuntimeError("soundcard 库未安装，无法采集系统声音")
        if self._loopback_device_id:
            speaker = sc.get_speaker(self._loopback_device_id)
        else:
            speaker = sc.default_speaker()
        return sc.get_microphone(id=speaker.id, include_loopback=True)

    def _start_loopback_stream(self):
        """启动系统音频回环采集线程"""
        speaker = self._get_loopback_speaker()
        self._loopback_thread = threading.Thread(
            target=self._loopback_record_loop,
            args=(speaker,),
            daemon=True,
            name="loopback-recorder",
        )
        self._loopback_thread.start()

    def _loopback_record_loop(self, speaker):
        """回环录音线程主循环"""
        blocksize = int(self.sample_rate * 0.1)  # 100ms
        try:
            with speaker.recorder(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=blocksize,
            ) as rec:
                asr_logger.info("回环录音线程已启动: {}", speaker.name)
                while self.is_recording:
                    # soundcard 返回 float32 [-1, 1]
                    data = rec.record(numframes=blocksize)
                    if not self.is_recording:
                        break
                    # 转换为 int16
                    audio_int16 = np.clip(data * 32767, -32768, 32767).astype(np.int16)
                    # 只取第一个声道（如果录到的是多声道）
                    if audio_int16.ndim > 1 and self.channels == 1:
                        audio_int16 = audio_int16[:, 0:1]
                    audio_bytes = audio_int16.tobytes()

                    # 写入 MP3
                    if self.mp3_encoder and self.mp3_file:
                        mp3_data = self.mp3_encoder.encode(audio_bytes)
                        if mp3_data:
                            self.mp3_file.write(mp3_data)
                            self.mp3_file.flush()

                    # 推送到 ASR 队列
                    if self._loop and self.is_recording:
                        try:
                            self._loop.call_soon_threadsafe(
                                self.audio_queue.put_nowait, audio_bytes
                            )
                        except asyncio.QueueFull:
                            pass
        except Exception as e:
            asr_logger.error("回环录音线程异常: {}", e)
        finally:
            asr_logger.info("回环录音线程已退出")

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """音频流回调（在音频线程中运行）"""
        if status:
            asr_logger.warning("音频流状态: {}", status)

        audio_bytes = indata.tobytes()

        # 写入 MP3（同步，在音频线程中执行）
        if self.mp3_encoder and self.mp3_file:
            mp3_data = self.mp3_encoder.encode(audio_bytes)
            if mp3_data:
                self.mp3_file.write(mp3_data)
                self.mp3_file.flush()

        # 将音频数据推送到队列供 ASR 使用
        if self._loop and self.is_recording:
            try:
                self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, audio_bytes)
            except asyncio.QueueFull:
                pass  # 队列满时丢弃

    async def stop_recording(self) -> dict:
        """停止录音，返回录音信息"""
        if not self.is_recording:
            return {}

        self.is_recording = False

        # 停止音频流
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # 停止回环线程
        if self._loopback_thread and self._loopback_thread.is_alive():
            self._loopback_thread.join(timeout=2)
            self._loopback_thread = None

        # 刷新 MP3 编码器
        if self.mp3_encoder and self.mp3_file:
            remaining = self.mp3_encoder.flush()
            if remaining:
                self.mp3_file.write(remaining)
            self.mp3_file.close()
            self.mp3_file = None

        duration = time.time() - self._start_time
        file_size = Path(self.mp3_path).stat().st_size if self.mp3_path else 0

        asr_logger.info("录音停止: 时长={:.1f}s 大小={:.1f}MB", duration, file_size / 1024 / 1024)

        return {
            "file_path": self.mp3_path,
            "duration_seconds": duration,
            "file_size_bytes": file_size,
        }

    @property
    def elapsed_seconds(self) -> float:
        """录音已进行的时间"""
        if self.is_recording:
            return time.time() - self._start_time
        return 0

    def start_mic_monitor(self, callback):
        """开始音量监控，callback(db, peak, clipping) 将在每个音频块上被调用"""
        if self.is_monitoring:
            return
        self._monitor_loop = asyncio.get_event_loop()
        self._monitor_callback = callback
        self.is_monitoring = True

        try:
            if self._loopback_mode:
                # 回环模式：使用 soundcard 在后台线程中采集
                speaker = self._get_loopback_speaker()
                self._monitor_loopback_thread = threading.Thread(
                    target=self._loopback_monitor_loop,
                    args=(speaker,),
                    daemon=True,
                    name="loopback-monitor",
                )
                self._monitor_loopback_thread.start()
                logger.info("回环音量监控已启动: {}", speaker.name)
            else:
                stream_config = self._get_monitor_stream_config()
                self._monitor_stream = sd.InputStream(**stream_config)
                self._monitor_stream.start()
                logger.info(
                    "麦克风监控已启动: device={}, samplerate={}, channels={}",
                    self._device_index,
                    stream_config["samplerate"],
                    stream_config["channels"],
                )
        except Exception:
            self.is_monitoring = False
            self._monitor_stream = None
            self._monitor_loopback_thread = None
            self._monitor_callback = None
            raise

    def _loopback_monitor_loop(self, speaker):
        """回环音量监控线程"""
        blocksize = int(self.sample_rate * 0.05)
        try:
            with speaker.recorder(
                samplerate=self.sample_rate, channels=1, blocksize=blocksize
            ) as rec:
                while self.is_monitoring:
                    data = rec.record(numframes=blocksize)
                    if not self.is_monitoring:
                        break
                    samples = data[:, 0].astype(np.float64)
                    # soundcard 返回 [-1, 1] 范围，映射到 int16 范围计算
                    samples_i16 = samples * 32768.0
                    rms = np.sqrt(np.mean(samples_i16 ** 2))
                    peak = np.max(np.abs(samples_i16))
                    db = 20 * np.log10(max(rms, 1) / 32768.0)
                    clipping = bool(peak >= 32000)
                    if self._monitor_loop and self._monitor_callback:
                        self._monitor_loop.call_soon_threadsafe(
                            self._monitor_callback, db, peak, clipping
                        )
        except Exception as e:
            logger.error("回环监控线程异常: {}", e)

    def _monitor_audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """监控音频流回调"""
        if status:
            logger.warning("监控音频流状态: {}", status)

        samples = indata[:, 0].astype(np.float64)
        rms = np.sqrt(np.mean(samples ** 2))
        peak = np.max(np.abs(samples))
        # dBFS（相对满幅 32768）
        db = 20 * np.log10(max(rms, 1) / 32768.0)
        # 峰值接近满幅视为削波（>= 32000，约 -0.2 dBFS）
        clipping = bool(peak >= 32000)

        if self._monitor_loop and self._monitor_callback:
            self._monitor_loop.call_soon_threadsafe(
                self._monitor_callback, db, peak, clipping
            )

    def stop_mic_monitor(self):
        """停止音量监控"""
        if not self.is_monitoring:
            return
        self.is_monitoring = False
        if self._monitor_stream:
            self._monitor_stream.stop()
            self._monitor_stream.close()
            self._monitor_stream = None
        if self._monitor_loopback_thread and self._monitor_loopback_thread.is_alive():
            self._monitor_loopback_thread.join(timeout=2)
            self._monitor_loopback_thread = None
        self._monitor_callback = None
        logger.info("音量监控已停止")
