# VisionPoseCoach Server Stage 1

This is the first server skeleton for smartphone app integration.
It does not implement AI inference, calibration, BLE, or WiFi setup.

## Install

```bash
pip install -r requirements-server.txt
```

## Run

Run from the `WorkSpace` directory:

```bash
python server_main.py
```

Or:

```bash
uvicorn server_main:app --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /health`: server state and camera status
- `GET /mjpg`: MJPG stream; returns a dummy frame if a camera is not available
- `WS /ws`: accepts `start_session` and `stop_session`

WebSocket command examples:

```json
{"command": "start_session"}
```

```json
{"command": "stop_session"}
```
