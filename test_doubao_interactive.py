"""Interactive diagnostic tool for Doubao v3 WebSocket connection.

Tests different credential + resource ID combinations to diagnose auth issues.
Usage: python test_doubao_interactive.py
"""
import asyncio
import uuid
import sys

try:
    import websockets
    from websockets.exceptions import InvalidStatus
except ImportError:
    print("请先安装 websockets: pip install websockets")
    sys.exit(1)


RESOURCE_IDS = {
    "1": ("volc.bigasr.sauc.duration",     "1.0 小时版"),
    "2": ("volc.bigasr.sauc.concurrent",   "1.0 并发版"),
    "3": ("volc.seedasr.sauc.duration",     "2.0 小时版"),
    "4": ("volc.seedasr.sauc.concurrent",   "2.0 并发版"),
}


async def test_connection(appid: str, token: str, resource_id: str, label: str):
    url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    connect_id = str(uuid.uuid4())
    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": connect_id,
    }
    print(f"\n  测试: {label} ({resource_id})")
    print(f"  Connect-Id: {connect_id}")
    try:
        ws = await websockets.connect(url, additional_headers=headers)
        print(f"  ✅ 连接成功!")
        # Read response headers
        resp_headers = ws.response_headers
        logid = resp_headers.get("X-Tt-Logid", "N/A")
        print(f"  X-Tt-Logid: {logid}")
        await ws.close()
        return True
    except InvalidStatus as e:
        body = ""
        if e.response.body:
            body = e.response.body.decode("utf-8", errors="replace")
        logid = "N/A"
        for key, val in e.response.headers.raw_items():
            if key.lower() == "x-tt-logid":
                logid = val
        print(f"  ❌ HTTP {e.response.status_code}: {body}")
        print(f"  X-Tt-Logid: {logid}")
        return False
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        return False


def load_from_db():
    """Try to load credentials from the app database."""
    import os
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "data", "class_copilot.db")
    if not os.path.exists(db_path):
        return None, None

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value, is_encrypted FROM settings "
            "WHERE key IN ('doubao_appid', 'doubao_access_token', 'doubao_api_key')"
        )
        rows = cursor.fetchall()
        conn.close()

        creds = {}
        for key, value, is_encrypted in rows:
            if is_encrypted:
                try:
                    from class_copilot.services.encryption_service import decrypt_value
                    creds[key] = decrypt_value(value)
                except Exception:
                    creds[key] = value  # fallback to raw
            else:
                creds[key] = value

        appid = creds.get("doubao_appid", "")
        token = creds.get("doubao_access_token") or creds.get("doubao_api_key", "")
        return appid, token
    except Exception as e:
        print(f"  (从数据库加载失败: {e})")
        return None, None


async def run_tests(appid: str, token: str):
    print(f"\n{'='*60}")
    print(f"AppID:  {appid}")
    print(f"Token:  {'***' + token[-4:] if len(token) > 4 else '(空)'}")
    print(f"{'='*60}")

    any_success = False
    for key in sorted(RESOURCE_IDS.keys()):
        rid, label = RESOURCE_IDS[key]
        ok = await test_connection(appid, token, rid, label)
        if ok:
            any_success = True

    if not any_success:
        print("\n⚠️  所有 Resource ID 均连接失败。")
        print("   可能原因：")
        print("   1. 旧版控制台的 Access Token 不支持 2.0 模型")
        print("      → 请切换到新版控制台，在 API Key 管理中获取 API Key")
        print("   2. APP ID 与 Token/API Key 不匹配")
        print("   3. 服务未开通或已过期")


async def main():
    print("=" * 60)
    print("  豆包语音识别 v3 API 连接诊断工具")
    print("=" * 60)

    # Try loading from DB
    db_appid, db_token = load_from_db()

    while True:
        print("\n选项:")
        if db_appid:
            print(f"  [1] 使用数据库中的凭据 (AppID: {db_appid})")
        print("  [2] 手动输入凭据")
        print("  [q] 退出")

        choice = input("\n请选择: ").strip().lower()

        if choice == "q":
            break
        elif choice == "1" and db_appid:
            await run_tests(db_appid, db_token)
        elif choice == "2" or (choice == "1" and not db_appid):
            appid = input("请输入 APP ID: ").strip()
            token = input("请输入 Access Token / API Key: ").strip()
            if not appid or not token:
                print("AppID 和 Token 不能为空")
                continue
            await run_tests(appid, token)
        else:
            print("无效选择")

        print("\n" + "-" * 60)
        input("按 Enter 继续...")


if __name__ == "__main__":
    asyncio.run(main())
