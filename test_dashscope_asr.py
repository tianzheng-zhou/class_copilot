"""测试 DashScope 文件转写 API 的真实返回格式"""
import sys
import json
import time
import glob

# 加载项目配置
sys.path.insert(0, ".")
from class_copilot.config import settings

# 需要先从数据库加载 API Key，这里手动设置
import dashscope
import asyncio

async def load_api_key():
    """从数据库加载 API Key"""
    from class_copilot.database import init_db, async_session
    from sqlalchemy import select
    from class_copilot.models.models import SettingItem
    from class_copilot.services.encryption_service import decrypt_value
    await init_db()
    async with async_session() as db:
        result = await db.execute(select(SettingItem).where(SettingItem.key == "dashscope_api_key"))
        item = result.scalar_one_or_none()
        if item:
            settings.dashscope_api_key = decrypt_value(item.value) if item.is_encrypted else item.value
            print(f"[OK] API Key 已加载 (长度: {len(settings.dashscope_api_key)})")
        else:
            print("[ERROR] 数据库中没有 API Key")
            sys.exit(1)

asyncio.run(load_api_key())
dashscope.api_key = settings.dashscope_api_key

# 查找一个测试用的录音文件
recordings = glob.glob("data/recordings/*.mp3")
if not recordings:
    print("[ERROR] data/recordings/ 下没有 MP3 文件")
    sys.exit(1)

test_file = recordings[0]
print(f"\n[TEST] 使用测试文件: {test_file}")
print(f"       文件大小: {__import__('os').path.getsize(test_file)} bytes")

# ──────── 步骤1: 上传文件 ────────
print("\n" + "="*60)
print("步骤1: dashscope.Files.upload()")
print("="*60)

upload_resp = dashscope.Files.upload(
    file_path=test_file,
    purpose="file-extract",
    api_key=settings.dashscope_api_key,
)
print(f"  status_code: {upload_resp.status_code}")
print(f"  type(output): {type(upload_resp.output)}")
print(f"  output: {json.dumps(upload_resp.output, ensure_ascii=False, indent=2) if upload_resp.output else 'None'}")

# 尝试各种方式提取 file_id
if upload_resp.output:
    output = upload_resp.output
    print(f"\n  output keys: {list(output.keys()) if isinstance(output, dict) else 'NOT A DICT'}")
else:
    print("\n  [ERROR] output 为空!")
    # 检查其他属性
    print(f"  dir(upload_resp): {[a for a in dir(upload_resp) if not a.startswith('_')]}")
    for attr in ['id', 'file_id', 'data', 'body', 'message', 'code']:
        if hasattr(upload_resp, attr):
            print(f"  upload_resp.{attr}: {getattr(upload_resp, attr)}")
    sys.exit(1)

# 提取 file_id
file_id = None
if isinstance(output, dict):
    # 尝试多种格式
    if "uploaded_files" in output:
        files = output["uploaded_files"]
        if files:
            file_id = files[0].get("file_id")
    if not file_id and "uploaded_file" in output:
        file_id = output["uploaded_file"].get("file_id")
    if not file_id:
        file_id = output.get("file_id")

if not file_id:
    print(f"  [ERROR] 无法提取 file_id")
    sys.exit(1)

print(f"\n  [OK] file_id: {file_id}")

# ──────── 步骤2: 获取URL并提交转写 ────────
print("\n" + "="*60)
print("步骤2: Files.get → Transcription.async_call")
print("="*60)

from dashscope.audio.asr import Transcription

file_info = dashscope.Files.get(file_id=file_id, api_key=settings.dashscope_api_key)
file_url = file_info.output["url"]
print(f"  file_url (截断): {file_url[:80]}...")

print("\n  提交转写任务...")
response = Transcription.async_call(
    model=settings.refined_asr_model,
    file_urls=[file_url],
    language_hints=["zh"],
    api_key=settings.dashscope_api_key,
)
print(f"  status_code: {response.status_code}")
if response.output and isinstance(response.output, dict):
    print(f"  output: {json.dumps(response.output, ensure_ascii=False, indent=2)}")
    task_id = response.output.get("task_id")
else:
    print(f"  output: {response.output}")
    try:
        print(f"  message: {response.message}")
    except Exception:
        pass
    print("[ERROR] 无法提交任务")
    sys.exit(1)

if not task_id:
    print("[ERROR] 无法获取 task_id")
    sys.exit(1)

print(f"\n  [OK] task_id: {task_id}")

# ──────── 步骤3: 轮询等待 ────────
print("\n" + "="*60)
print("步骤3: Transcription.fetch() 轮询")
print("="*60)

for i in range(60):
    fetch_resp = Transcription.fetch(task=task_id, api_key=settings.dashscope_api_key)

    if fetch_resp.output and isinstance(fetch_resp.output, dict):
        status = fetch_resp.output.get("task_status", "UNKNOWN")
        print(f"  [{i+1}] task_status: {status}")

        if status == "SUCCEEDED":
            print(f"  output keys: {list(fetch_resp.output.keys())}")
            full = json.dumps(fetch_resp.output, ensure_ascii=False, indent=2)
            if len(full) > 3000:
                print(f"  output (截断): {full[:3000]}...")
            else:
                print(f"  output: {full}")
            break
        elif status in ("FAILED", "CANCELED"):
            print(f"  任务失败: {json.dumps(fetch_resp.output, ensure_ascii=False, indent=2)}")
            break
    else:
        print(f"  [{i+1}] output=None")

    time.sleep(3)
else:
    print("  [ERROR] 轮询超时")

print("\n[DONE] 测试完成")
