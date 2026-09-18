# Class Copilot

面向 Ubuntu 的本机课堂助手。一个工作台查看持续转写、课堂问答和聊天，录音结束后仍可继续提问、生成答案和总结。

本仓库是 `refactor/next` 独立重构实现。新版使用 `backend/`、`web/` 和独立的 `data/next/`；不读取旧 Key，不迁移旧数据库，不修改旧录音。旧版仍留在 `main`。

## 运行

需要 Python 3.12、uv、Node.js 22.12+（建议 npm 10/11）、FFmpeg 和 PortAudio。Ubuntu 系统声音还需要 PulseAudio/PipeWire 的 monitor 来源及 `pulseaudio-utils`。

```bash
# Ubuntu 系统依赖（已安装的无需重复安装）
sudo apt install ffmpeg libportaudio2 pulseaudio-utils

# 仓库根目录
./scripts/setup.sh
./scripts/run.sh
```

浏览器打开 **http://127.0.0.1:29038**。首次启动为空库，在设置中填写百炼工作空间区域、兼容地址和 API Key。保存不会发起云端调用；“连接测试”会使用内置样本调用模型，可能产生费用。

音频及相关文本会发送到所配置的百炼服务。语音模型为用户指定的 `qwen3.8-omni-flash`；检测、回答、聊天和总结使用按角色保存的文本模型。

无需 Key 也可以管理课程、创建课堂、上传音频、查看已有内容和导出。录音由后端电脑采集，**关掉浏览器不会停止录音**，请使用“停止采集”。每个来源最长 4 小时。

可以显式设置独立数据目录：

```bash
CC_NEXT_DATA_DIR=/absolute/path/to/copilot-next ./scripts/run.sh
```

仅支持本机单进程、单 worker。不要把 `CC_NEXT_DATA_DIR` 指向旧版数据目录，也不要以多 worker 模式启动。

## 已实现的功能

- 课程管理、课堂创建/改名、按课程/名称/本地日期筛选和分页。
- 三栏工作台，可调整栏宽；窄窗口切换面板；中英文界面、浅色/深色/跟随系统。
- 指定麦克风或系统 monitor 录音、同流电平、5 秒音源测试、自动停止与短尾段保存。
- MP3/WAV/M4A/FLAC/OGG 上传，500 MiB/4 小时限制；上传与分析分开；重复文件提示、取消与补识别。
- 音频先落盘，分块调用指定语音模型；MP3 播放、定位、倍速、Range 下载和原文件下载。
- 自动问答、仅检测、仅转写三种模式；手动找问题、直接解释所选片段。
- 简要/详细答案、语言与模型选择、多版本生成、失败部分保存、取消和重试。
- 课中与课后聊天、快速/质量/思考选项、每课堂单回复约束、草稿保留。
- 总结版本、来源覆盖、缺口及过期提示，长课堂分段提炼后合并。
- 持久任务与 SSE 事件、快照和游标恢复、幂等命令、原子设置、版本冲突、加密凭据。
- 完整 Markdown 导出、活动删除保护、文件清理重试、进程中断恢复和轮转诊断日志。

## 开发与验证

```bash
# 后端开发
uv sync --project backend --python 3.12 --frozen
uv run --project backend python -m class_copilot

# 前端开发（另一个终端；通过 Vite 代理连接 29038）
npm ci --prefix web
npm run dev --prefix web

# 静态检查、后端/前端测试、契约生成和生产构建
./scripts/check.sh

# 浏览器验收：独立临时数据库 + 合成采集和模型替身
cd web
npx playwright install chromium
npm run test:e2e
cd ..

# 只读依赖诊断，不打开麦克风、不读取 Key
backend/.venv/bin/python scripts/doctor.py

# 可选：合成 4 小时音频的加速分块/编码检查（约 1 GiB 临时空间）
backend/.venv/bin/python scripts/audio_soak.py --seconds 14400
```

新版不使用根目录旧 `.venv` 或旧 `frontend/dist`。OpenAPI 由后端生成，前端 DTO 由 `openapi-typescript` 生成；CI 检查生成文件差异。`/docs` 是本机 API 文档入口。

自动化与设备/模型验收分开记录：当前已通过后端行为测试、前端单元测试、类型检查、构建、Chromium 主流程及合成 4 小时媒体链路。真实模型权限、识别质量、两个麦克风/系统输出的选择，以及 4 小时真实采集仍待实际配置后验证。详细结果和限制见 [实施与验收记录](docs/实施记录.md)。

## 文档

- [新版产品需求](docs/新版产品需求.md)：C-01～C-07、R-01～R-11、V-01～V-30。
- [新版技术设计](docs/新版技术设计.md)：架构、任务、音频、数据和恢复。
- [新版接口契约](docs/新版接口契约.md)：50 个 HTTP 业务操作和 SSE 协议。
- [实施与验收记录](docs/实施记录.md)：实际实现、检查结果、尚未验证项。
- [文档索引](docs/README.md)：新版与旧版基线的边界。

此分支与 `main` 没有共同祖先；发布和主线切换另行安排。本次实现不自动提交、发布或合并分支。
