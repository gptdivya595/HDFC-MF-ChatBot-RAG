from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

APP_SERVER_PATH = APP_DIR / "server.py"
SPEC = importlib.util.spec_from_file_location("fundclear_app_server", APP_SERVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load FastAPI app from {APP_SERVER_PATH}")

MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
app = MODULE.app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, app_dir=str(APP_DIR))
