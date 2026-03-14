"""应用常量定义。"""

APP_NAME = "听课助手"
APP_NAME_EN = "class_copilot"
APP_VERSION = "0.1.0"

# 音频采集参数
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH = 2  # 16bit = 2 bytes
AUDIO_CHUNK_BYTES = 1280  # 每 40ms 发送的字节数
AUDIO_CHUNK_DURATION_MS = 40
AUDIO_FORMAT_PCM = "pcm"

# DashScope ASR（阿里云百炼语音识别）
ASR_MODEL_DEFAULT = "fun-asr-realtime"
ASR_MODEL_CHOICES = {
    "fun-asr-realtime": "Fun-ASR（课堂/演讲优化，~1.19元/时）",
    "qwen3-asr-flash-realtime": "千问3-ASR（多语种高精度+情感识别，~1.19元/时）",
}

# LLM 模型
LLM_MODEL_FLASH = "qwen3.5-flash"
LLM_MODEL_PLUS = "qwen3.5-plus"
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 默认快捷键
DEFAULT_HOTKEYS = {
    "toggle_listen": "<ctrl>+<shift>+s",
    "manual_question": "<ctrl>+<shift>+q",
    "toggle_window": "<ctrl>+<shift>+h",
    "copy_answer": "<ctrl>+<shift>+c",
    "toggle_answer_mode": "<ctrl>+<shift>+t",
    "active_question": "<ctrl>+<shift>+a",
    "toggle_llm_filter": "<ctrl>+<shift>+f",
}

# UI 常量
WINDOW_DEFAULT_WIDTH = 400
WINDOW_DEFAULT_HEIGHT = 500
WINDOW_MIN_WIDTH = 300
WINDOW_MIN_HEIGHT = 400

# 数据库
DB_FILENAME = "class_copilot.db"

# 录音最大时长（秒）
MAX_RECORDING_DURATION = 8 * 3600  # 8 小时
