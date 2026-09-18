"""Accelerated long-media verification, using generated PCM only (no device or cloud access)."""

import argparse
import json
import resource
import tempfile
import time
import wave
from pathlib import Path

from class_copilot.audio import RATE, encode_mp3, run_media, split_file

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=int, default=14400)
args = parser.parse_args()
start = time.monotonic()
with tempfile.TemporaryDirectory(prefix="copilot-soak-") as temporary:
    root = Path(temporary)
    original = root / "generated.wav"
    frame = b"\x01\x10" * RATE
    with wave.open(str(original), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        for _ in range(args.seconds):
            file.writeframesraw(frame)
    chunks = split_file(original, root / "chunks", dict(max_chunk_seconds=12, silence_ms=600))
    assert chunks[0]["start_ms"] == 0
    assert chunks[-1]["end_ms"] == args.seconds * 1000
    assert all(left["end_ms"] == right["start_ms"] for left, right in zip(chunks, chunks[1:]))
    assert sum(c["end_ms"] - c["start_ms"] for c in chunks) == args.seconds * 1000
    output = root / "playback.mp3"
    encode_mp3([root / "chunks" / c["filename"] for c in chunks], output)
    info = json.loads(run_media(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(output)]))
    assert abs(float(info["format"]["duration"]) - args.seconds) < 0.2
    result = dict(
        generated_duration_seconds=args.seconds,
        chunks=len(chunks),
        playback_duration_seconds=float(info["format"]["duration"]),
        playback_bytes=output.stat().st_size,
        peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        wall_seconds=round(time.monotonic() - start, 2),
        contiguous=True,
        scope="accelerated synthetic PCM splitting and MP3 encoding; not real-time device/cloud acceptance",
    )
    print(json.dumps(result, indent=2))
