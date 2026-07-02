import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "http://127.0.0.1:8000/health"


def check_health(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            return {
                "ok": response.status == 200 and bool(data.get("ok")),
                "status_code": response.status,
                "payload": data,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": exc.code, "payload": None, "error": str(exc)}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "status_code": None, "payload": None, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Check Vision Pose Coach /health without extra dependencies.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Health URL to check.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    result = check_health(args.url, timeout=args.timeout)
    if result["ok"]:
        app = result["payload"].get("app", {})
        print("Server health OK")
        print(f"state={app.get('state')} screen_hint={app.get('screen_hint')}")
        return 0

    print("Server health check failed")
    if result["status_code"] is not None:
        print(f"status_code={result['status_code']}")
    if result["error"]:
        print(f"error={result['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
