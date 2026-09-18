"""Isolated browser acceptance server. Synthetic adapters; never uses real hardware/cloud."""

import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/tests"))
from class_copilot.main import create_app
from conftest import FakeHardware, FakeProvider

with tempfile.TemporaryDirectory(prefix="copilot-browser-") as root:
    app = create_app(root, provider=FakeProvider(), hardware=FakeHardware())
    uvicorn.run(app, host="127.0.0.1", port=29039, log_level="warning")
