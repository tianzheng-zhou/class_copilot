"""Non-interactive quick test - runs all resource IDs with DB credentials."""
import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

import websockets
from websockets.exceptions import InvalidStatus


RESOURCE_IDS = {
    "1": ("volc.bigasr.sauc.duration",     "1.0 小时版"),
    "2": ("volc.bigasr.sauc.concurrent",   "1.0 并发版"),
    "3": ("volc.seedasr.sauc.duration",     "2.0 小时版"),
    "4": ("volc.seedasr.sauc.concurrent",   "2.0 并发版"),
}


def load_from_db():
    """Load credentials from the app database."""
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
                    creds[key] = value
            else:
                creds[key] = value

        appid = creds.get("doubao_appid", "")
        token = creds.get("doubao_access_token") or creds.get("doubao_api_key", "")
        return appid, token
    except Exception as e:
        print(f"  (从数据库加载失败: {e})")
        return None, None


async def test_connection(appid, token, resource_id, label, use_new_auth):
    url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    connect_id = str(uuid.uuid4())
    headers = {
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": connect_id,
    }
    if use_new_auth:
        headers["x-api-key"] = token
        auth_label = "x-api-key"
    else:
        headers["X-Api-App-Key"] = appid
        headers["X-Api-Access-Key"] = token
        auth_label = "App-Key + Access-Key"

    print(f"\n  测试: {label} ({resource_id}) [{auth_label}]")
    try:
        ws = await websockets.connect(url, additional_headers=headers)
        print(f"  ✅ 连接成功!")
        await ws.close()
        return True
    except InvalidStatus as e:
        body = ""
        if e.response.body:
            body = e.response.body.decode("utf-8", errors="replace")
        print(f"  ❌ HTTP {e.response.status_code}: {body}")
        return False
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
        return False


async def main():
    appid, token = load_from_db()
    print(f"AppID: {appid or '(空)'}")
    print(f"Token: {'***' + token[-4:] if token and len(token) > 4 else '(空)'}")
    print(f"Token length: {len(token) if token else 0}")

    if not token:
        print("No credentials in DB")
        return

    # Test with new-style auth (x-api-key)
    print("\n=== 新版控制台鉴权 (x-api-key) ===")
    for key in sorted(RESOURCE_IDS.keys()):
        rid, label = RESOURCE_IDS[key]
        await test_connection(appid, token, rid, label, use_new_auth=True)

    # Test with old-style auth (App-Key + Access-Key)
    if appid:
        print("\n=== 旧版控制台鉴权 (App-Key + Access-Key) ===")
        for key in sorted(RESOURCE_IDS.keys()):
            rid, label = RESOURCE_IDS[key]
            await test_connection(appid, token, rid, label, use_new_auth=False)


if __name__ == "__main__":
    asyncio.run(main())
