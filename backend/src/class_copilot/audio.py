from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from .domain import Fault, digest

RATE = 16000
MAX_BYTES = 500 * 1024 * 1024
MAX_MS = 4 * 3600 * 1000
FORMATS = {".mp3": "mp3", ".wav": "wav", ".m4a": "mov", ".flac": "flac", ".ogg": "ogg"}


def run_media(args, timeout=180):
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise Fault("audio_unavailable", "请安装 ffmpeg 和 ffprobe", 503) from None
    except subprocess.TimeoutExpired:
        raise Fault("audio_timeout", "音频转换超时", 422) from None
    if result.returncode:
        raise Fault("invalid_audio", "音频无法解码或写入，请检查文件和磁盘空间", 422)
    return result.stdout


def storage_check(root, required=64 * 1024 * 1024):
    if shutil.disk_usage(root).free < required:
        raise Fault("storage_unavailable", "磁盘空间不足，请释放空间", 503)


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_audio(path: Path, suffix: str, output: Path):
    if suffix not in FORMATS:
        raise Fault("unsupported_audio", "支持 MP3、WAV、M4A、FLAC、OGG", 415)
    flags = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mp3,wav,mov,flac,ogg"]
    info = json.loads(
        run_media(
            [
                "ffprobe",
                "-v",
                "error",
                *flags,
                "-f",
                FORMATS[suffix],
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            30,
        )
    )
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise Fault("invalid_audio", "文件中没有音轨", 422)
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError):
        raise Fault("invalid_audio", "无法确定音频时长", 422) from None
    if not 0 < duration <= MAX_MS / 1000:
        raise Fault("duration_exceeded", "单个音源必须大于零且不超过 4 小时", 422)
    storage_check(output.parent, int(duration * RATE * 2) + 64 * 1024 * 1024)
    run_media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-y",
            *flags,
            "-f",
            FORMATS[suffix],
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-c:a",
            "pcm_s16le",
            "-t",
            str(MAX_MS / 1000 + 1),
            str(output),
        ],
        300,
    )
    with wave.open(str(output)) as f:
        duration_ms = round(f.getnframes() * 1000 / f.getframerate())
    if duration_ms > MAX_MS:
        raise Fault("duration_exceeded", "解码音频超过 4 小时", 422)
    return duration_ms


class Segmenter:
    def __init__(self, max_seconds=12, silence_ms=600):
        self.maximum = max_seconds * RATE * 2
        self.silence_limit = silence_ms * RATE * 2 // 1000
        self.buffer = bytearray()
        self.silence = 0

    def feed(self, pcm):
        self.buffer.extend(pcm)
        values = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        rms = float(np.sqrt(np.mean(values**2))) if len(values) else 0
        self.silence = self.silence + len(pcm) if rms < 350 else 0
        if len(self.buffer) >= self.maximum or (
            len(self.buffer) >= RATE * 4 and self.silence >= self.silence_limit
        ):
            return self.flush()
        return None

    def flush(self):
        if not self.buffer:
            return None
        result = bytes(self.buffer)
        self.buffer.clear()
        self.silence = 0
        return result


def save_chunk(directory, ordinal, start_sample, pcm):
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{ordinal:06d}.wav"
    part = directory / (filename + ".part")
    with wave.open(str(part), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)
    with part.open("rb") as f:
        os.fsync(f.fileno())
    final = directory / filename
    part.replace(final)
    record = dict(
        ordinal=ordinal,
        start_ms=start_sample * 1000 // RATE,
        end_ms=(start_sample + len(pcm) // 2) * 1000 // RATE,
        checksum=file_hash(final),
        filename=filename,
    )
    manifest = directory / (filename + ".json.part")
    manifest.write_text(json.dumps(record))
    manifest.replace(directory / (filename + ".json"))
    return record


def split_file(path, directory, settings):
    segmenter = Segmenter(settings["max_chunk_seconds"], settings["silence_ms"])
    records, sample, ordinal = [], 0, 1
    with wave.open(str(path)) as f:
        while pcm := f.readframes(1600):
            if chunk := segmenter.feed(pcm):
                records.append(save_chunk(directory, ordinal, sample, chunk))
                sample += len(chunk) // 2
                ordinal += 1
        if tail := segmenter.flush():
            records.append(save_chunk(directory, ordinal, sample, tail))
    return records


def encode_mp3(chunks, output):
    if not chunks:
        raise Fault("audio_missing", "没有可恢复的音频块", 404)
    # Stream chunks through a bounded pipe; never concatenate a four-hour recording in memory.
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".part.mp3")
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "s16le",
            "-ar",
            str(RATE),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(temp),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for path in chunks:
            with wave.open(str(path)) as f:
                while block := f.readframes(RATE):
                    process.stdin.write(block)
        process.stdin.close()
        if process.wait(timeout=120):
            raise Fault("audio_encoding_failed", "MP3 封装失败，原始块已保留", 503)
        temp.replace(output)
    except BaseException:
        process.kill()
        process.wait()
        raise


class AudioHardware:
    def devices(self, kind):
        if kind == "loopback":
            try:
                raw = subprocess.run(
                    ["pactl", "-f", "json", "list", "sources"], capture_output=True, timeout=5, check=True
                )
                devices = [
                    dict(id="pulse:" + s["name"], label=s.get("description") or s["name"], kind=kind)
                    for s in json.loads(raw.stdout)
                    if s.get("monitor_of_sink") not in (None, 4294967295, "4294967295")
                    or s["name"].endswith(".monitor")
                ]
                return dict(
                    devices=devices, unavailable_reason=None if devices else "未找到系统声音 monitor 来源"
                )
            except (FileNotFoundError, subprocess.SubprocessError, ValueError):
                return dict(
                    devices=[],
                    unavailable_reason="请安装 pulseaudio-utils，并确认 PipeWire/PulseAudio 服务正在运行",
                )
        try:
            import sounddevice as sd

            devices = []
            for index, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    devices.append(
                        dict(
                            id=f"portaudio:{index}:{digest([d['name'], d['hostapi']])[:12]}",
                            label=d["name"],
                            kind=kind,
                            is_default=index == sd.default.device[0],
                        )
                    )
            return dict(devices=devices, unavailable_reason=None if devices else "未找到麦克风输入设备")
        except Exception:
            return dict(devices=[], unavailable_reason="PortAudio 不可用，请检查 libportaudio2 和音频服务")

    def resolve(self, kind, device_id):
        devices = self.devices(kind)
        found = next((d for d in devices["devices"] if d["id"] == device_id), None)
        if not found:
            raise Fault(
                "audio_unavailable", devices["unavailable_reason"] or "所选音源已不可用，请重新选择", 503
            )
        return found

    async def open(self, kind, device_id):
        await asyncio.to_thread(self.resolve, kind, device_id)
        if kind == "loopback":
            process = await asyncio.create_subprocess_exec(
                "parec",
                "--device=" + device_id.removeprefix("pulse:"),
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--raw",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return PulseStream(process)
        import sounddevice as sd

        frames = queue.Queue(maxsize=100)
        errors = []

        def callback(data, count, timing, status):
            if status:
                errors.append("capture_overflow")
                raise sd.CallbackAbort
            try:
                frames.put_nowait(bytes(data))
            except queue.Full:
                errors.append("capture_overflow")
                raise sd.CallbackAbort

        stream = sd.RawInputStream(
            device=int(device_id.split(":")[1]),
            samplerate=RATE,
            channels=1,
            dtype="int16",
            blocksize=1600,
            callback=callback,
        )
        try:
            await asyncio.to_thread(stream.start)
        except Exception:
            await asyncio.to_thread(stream.close)
            raise Fault("audio_unavailable", "无法打开所选音源，请检查设备权限和采样率", 503) from None
        return MicrophoneStream(stream, frames, errors)


class MicrophoneStream:
    def __init__(self, stream, frames, errors):
        self.stream, self.frames, self.errors = stream, frames, errors

    async def read(self):
        if self.errors:
            raise Fault("capture_overflow", "采集缓冲溢出，已停止；可能丢失的区间已标记", 503)
        try:
            return await asyncio.to_thread(self.frames.get, True, 0.2)
        except queue.Empty:
            if not self.stream.active:
                raise Fault("audio_disconnected", "音频设备已断开", 503)
            return b""

    async def close(self):
        await asyncio.to_thread(self.stream.stop)
        await asyncio.to_thread(self.stream.close)


class PulseStream:
    def __init__(self, process):
        self.process = process

    async def read(self):
        try:
            data = await asyncio.wait_for(self.process.stdout.read(3200), 0.3)
        except TimeoutError:
            return b""
        if not data:
            raise Fault("audio_disconnected", "系统音频来源已断开", 503)
        return data

    async def close(self):
        if self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()
