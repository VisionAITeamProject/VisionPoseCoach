"""
FastAPI server entrypoint for smartphone app integration.

Run from the WorkSpace directory:
    python server_main.py

Or run with uvicorn directly:
    uvicorn server_main:app --host 0.0.0.0 --port 8000

Required packages for this server stage:
    pip install fastapi uvicorn opencv-python numpy
"""
from pathlib import Path
import sys

import uvicorn


ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from network.api_server import create_app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "server_main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
