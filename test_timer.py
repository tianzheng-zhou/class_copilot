"""Quick test for auto-stop timer via WebSocket"""
import asyncio
import json
import time

import websockets


async def test():
    async with websockets.connect("ws://localhost:8765/ws") as ws:
        # Receive initial status
        msg = json.loads(await ws.recv())
        asr = msg["data"].get("auto_stop_remaining", "MISSING")
        print(f"Initial status: type={msg['type']} auto_stop_remaining={asr}")

        # Send start_listening with auto_stop_seconds=10
        await ws.send(json.dumps({
            "type": "start_listening",
            "data": {
                "course_name": "test_timer",
                "auto_stop_seconds": 10,
                "auto_stop_label": "test",
            },
        }))
        print("Sent start_listening with auto_stop_seconds=10")

        # Listen for messages for 15 seconds
        start = time.time()
        while time.time() - start < 15:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                t = msg["type"]
                d = msg["data"]
                elapsed = time.time() - start
                if t == "status":
                    print(f"[{elapsed:.1f}s] STATUS: status={d.get('status')} auto_stop_remaining={d.get('auto_stop_remaining', 'MISSING')}")
                elif t == "auto_stop_tick":
                    print(f"[{elapsed:.1f}s] TICK: remaining={d.get('remaining')}")
                elif t == "notification":
                    print(f"[{elapsed:.1f}s] NOTIFICATION: {d}")
                elif t == "error":
                    print(f"[{elapsed:.1f}s] ERROR: {d}")
                    break
                else:
                    pass  # ignore transcription etc
            except asyncio.TimeoutError:
                print(f"[{time.time()-start:.1f}s] (no message)")

        print("Test complete.")


asyncio.run(test())
