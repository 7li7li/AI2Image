from __future__ import annotations

import atexit
import json
import os
from pathlib import Path

os.environ.setdefault("STORAGE_BACKEND", "json")

ROOT_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.json"

if not ROOT_CONFIG_FILE.exists():
    ROOT_CONFIG_FILE.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
    atexit.register(lambda: ROOT_CONFIG_FILE.exists() and ROOT_CONFIG_FILE.unlink())
