"""应用配置 - 使用 pydantic-settings"""

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """全局配置"""

    # 服务器
    server_port: int = Field(default=8765, description="服务端口")

    # 数据存储
    data_dir: str = Field(
        default=str(Path(__file__).resolve().parent.parent / "data"),
        description="数据存储根目录",
    )

    # DashScope API (阿里百炼)
    dashscope_api_key: str = Field(default="", description="DashScope API Key")

    # LLM 配置
    llm_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="LLM API 基础URL",
    )
    llm_model_fast: str = Field(default="qwen3.5-flash", description="快速LLM模型")
    llm_model_quality: str = Field(default="qwen3.5-plus", description="高质量LLM模型")
    auto_answer_model: str = Field(default="qwen3.5-flash", description="自动回答使用的模型 (fast/quality)")

    # ASR 提供商选择
    asr_provider: Literal["dashscope", "doubao", "qwen_omni"] = Field(
        default="dashscope", description="实时ASR提供商"
    )
    refinement_provider: Literal["dashscope", "doubao"] = Field(
        default="dashscope", description="精修ASR提供商"
    )

    # DashScope ASR 配置
    asr_model: str = Field(
        default="qwen3-asr-flash-realtime", description="DashScope实时ASR模型"
    )
    refined_asr_model: str = Field(
        default="qwen3-asr-flash-filetrans", description="DashScope精修ASR模型(文件转写)"
    )

    # 豆包(火山引擎)ASR 配置 (v3 大模型版)
    doubao_appid: str = Field(default="", description="豆包语音 AppID")
    doubao_access_token: str = Field(default="", description="豆包语音 Access Token")
    doubao_resource_id_streaming: str = Field(
        default="volc.seedasr.sauc.duration",
        description="豆包流式识别 Resource ID (2.0小时版)",
    )
    doubao_resource_id_offline: str = Field(
        default="volc.seedasr.auc",
        description="豆包录音文件识别 Resource ID (2.0版)",
    )
    # 阿里云 OSS（用于上传音频获取公网可访问URL）
    oss_access_key_id: str = Field(default="", description="阿里云 OSS Access Key ID")
    oss_access_key_secret: str = Field(default="", description="阿里云 OSS Access Key Secret")
    oss_bucket_name: str = Field(default="", description="OSS Bucket 名称")
    oss_endpoint: str = Field(default="", description="OSS Endpoint (如 oss-cn-beijing.aliyuncs.com)")
    oss_upload_prefix: str = Field(default="class_copilot", description="OSS 上传路径前缀")
    oss_url_expiry_seconds: int = Field(default=3600, description="OSS 签名URL有效期(秒)")

    # 音频配置
    sample_rate: int = Field(default=16000, description="采样率")
    channels: int = Field(default=1, description="声道数")

    # 功能开关
    language: Literal["zh", "en"] = Field(default="zh", description="授课语言")
    enable_brief_answer: bool = Field(default=True, description="启用简洁版答案")
    enable_detailed_answer: bool = Field(default=True, description="启用展开版答案")
    enable_translation: bool = Field(default=False, description="启用英文翻译")
    enable_bilingual: bool = Field(default=False, description="启用双语展示")

    # 精修 ASR 配置
    enable_refinement: bool = Field(default=False, description="启用高精度精修")
    refinement_strategy: Literal["post", "periodic", "manual"] = Field(
        default="post", description="精修触发策略"
    )
    refinement_interval_minutes: int = Field(
        default=5, description="课中定时精修间隔(分钟)"
    )
    refinement_max_minutes: int = Field(
        default=90, description="单次精修上限(分钟)"
    )
    enable_refinement_recheck: bool = Field(
        default=True, description="精修后问题二次检测"
    )
    enable_refinement_answer_update: bool = Field(
        default=True, description="精修后答案自动更新"
    )

    # 问题检测
    question_confidence_threshold: float = Field(
        default=0.7, description="问题检测置信度阈值"
    )
    question_cooldown_seconds: int = Field(
        default=15, description="问题检测最小冷却间隔(秒)"
    )
    question_similarity_threshold: float = Field(
        default=0.8, description="问题去重相似度阈值"
    )

    # LLM 输入过滤
    llm_filter_mode: Literal["teacher_only", "all"] = Field(
        default="all", description="LLM输入过滤模式"
    )

    # 加密密钥（用于加密存储 API Key）
    encryption_key: str = Field(default="", description="加密密钥（自动生成）")

    model_config = {
        "env_file": ".env",
        "env_prefix": "CC_",
    }


settings = Settings()

# 确保数据目录存在
Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
(Path(settings.data_dir) / "recordings").mkdir(parents=True, exist_ok=True)
(Path(settings.data_dir) / "logs").mkdir(parents=True, exist_ok=True)
