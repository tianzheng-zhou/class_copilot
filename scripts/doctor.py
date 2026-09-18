"""Read-only dependency diagnostics. Never opens input devices or reads stored keys."""

import ctypes.util
import shutil
import sys

checks = {
    "Python 3.12": sys.version_info[:2] == (3, 12),
    "ffmpeg": bool(shutil.which("ffmpeg")),
    "ffprobe": bool(shutil.which("ffprobe")),
    "PortAudio": bool(ctypes.util.find_library("portaudio")),
    "pactl (system audio enumeration)": bool(shutil.which("pactl")),
    "parec (system audio capture)": bool(shutil.which("parec")),
}
for label, available in checks.items():
    print(f"{'OK' if available else 'MISSING':7} {label}")
if not checks["pactl (system audio enumeration)"] or not checks["parec (system audio capture)"]:
    print("For Ubuntu system audio: sudo apt install pulseaudio-utils")
