"""Quick test for Doubao v3 WebSocket connection - using real credentials"""
import asyncio
import sqlite3
import os
import uuid
import websockets
from websockets.exceptions import InvalidStatus

def load_credentials():
    """Load real credentials from database"""
    db_path = os.path.join("d:\\python_programs\\class_copilot\\data", "class_copilot.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value, is_encrypted FROM settings WHERE key IN ('doubao_appid', 'doubao_access_token')")
    rows = cursor.fetchall()
    conn.close()
    creds = {}
    for key, value, is_encrypted in rows:
        if is_encrypted:
            # Decrypt using the app's encryption service
            from class_copilot.services.encryption_service import decrypt_value
            creds[key] = decrypt_value(value)
        else:
            creds[key] = value
    return creds

async def test_resource_id(appid, token, resource_id):
    url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        ws = await websockets.connect(url, additional_headers=headers)
        print(f"  [{resource_id}] -> CONNECTED!")
        await ws.close()
        return True
    except InvalidStatus as e:
        body = ""
        if e.response.body:
            body = e.response.body.decode("utf-8", errors="replace")
        print(f"  [{resource_id}] -> HTTP {e.response.status_code}: {body}")
        return False
    except Exception as e:
        print(f"  [{resource_id}] -> {type(e).__name__}: {e}")
        return False

async def main():
    creds = load_credentials()
    appid = creds.get("doubao_appid", "")
    token = creds.get("doubao_access_token", "")
    print(f"AppID: {appid}")
    print(f"Token: {'***' + token[-4:] if len(token) > 4 else '(empty)'}")
    print()

    resource_ids = [
        "volc.bigasr.sauc.duration",        # 1.0 hourly
        "volc.bigasr.sauc.concurrent",       # 1.0 concurrent
        "volc.seedasr.sauc.duration",        # 2.0 hourly
        "volc.seedasr.sauc.concurrent",      # 2.0 concurrent
    ]

    print("Testing streaming resource IDs:")
    for rid in resource_ids:
        await test_resource_id(appid, token, rid)

asyncio.run(main())
