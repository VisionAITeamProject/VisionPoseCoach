import socket
from threading import Lock


class WiFiManager:
    def __init__(self, mode: str = "dry_run"):
        if mode not in {"dry_run", "mock", "real"}:
            mode = "dry_run"

        self.mode = mode
        self._lock = Lock()
        self._connected = False
        self._ssid = None
        self._last_configured_ssid = None
        self._last_error = None

    def get_status(self):
        with self._lock:
            connected = self._connected
            ssid = self._ssid
            last_configured_ssid = self._last_configured_ssid
            last_error = self._last_error

        return {
            "type": "wifi_status",
            "mode": self.mode,
            "connected": connected,
            "ssid": ssid,
            "local_ip": self._get_local_ip(),
            "hostname": self._get_hostname(),
            "provisioning_required": not connected,
            "last_configured_ssid": last_configured_ssid,
            "last_error": last_error,
        }

    def get_network_status(self):
        status = self.get_status()
        status.pop("type", None)
        return {
            "type": "network_status",
            "wifi": status,
        }

    def list_networks(self):
        return {
            "type": "wifi_scan",
            "mode": self.mode,
            "networks": [],
            "message": "현재 단계에서는 실제 WiFi 스캔을 수행하지 않습니다.",
        }

    def configure_wifi(self, ssid, password):
        validation = self.validate_wifi_payload({"ssid": ssid, "password": password})
        if not validation["ok"]:
            with self._lock:
                self._last_error = validation["message"]
            return {
                "type": "wifi_configure_result",
                "ok": False,
                "mode": self.mode,
                "ssid": ssid if isinstance(ssid, str) else None,
                "message": validation["message"],
            }

        normalized_ssid = ssid.strip()
        with self._lock:
            self._last_configured_ssid = normalized_ssid
            self._last_error = None

        return {
            "type": "wifi_configure_result",
            "ok": True,
            "mode": self.mode,
            "ssid": normalized_ssid,
            "message": "WiFi 설정 요청을 저장했습니다. 실제 연결 변경은 배포 단계에서 구현됩니다.",
        }

    def forget_wifi(self):
        with self._lock:
            self._ssid = None
            self._connected = False
            self._last_configured_ssid = None
            self._last_error = None

        return {
            "type": "wifi_forget_result",
            "ok": True,
            "message": "저장된 WiFi 설정 정보를 초기화했습니다.",
        }

    def validate_wifi_payload(self, payload):
        if not isinstance(payload, dict):
            return {"ok": False, "message": "WiFi 설정 payload가 올바르지 않습니다."}

        ssid = payload.get("ssid")
        password = payload.get("password")

        if not isinstance(ssid, str) or not ssid.strip():
            return {"ok": False, "message": "SSID가 올바르지 않습니다."}

        if len(ssid.encode("utf-8")) > 32:
            return {"ok": False, "message": "SSID는 32바이트 이하여야 합니다."}

        if not isinstance(password, str) or not password:
            return {"ok": False, "message": "WiFi 비밀번호가 올바르지 않습니다."}

        if not 8 <= len(password) <= 63:
            return {"ok": False, "message": "WiFi 비밀번호는 8자 이상 63자 이하여야 합니다."}

        return {"ok": True, "message": "ok"}

    def mask_sensitive_data(self, payload):
        if isinstance(payload, dict):
            masked = {}
            for key, value in payload.items():
                if str(key).lower() in {"password", "pw", "passphrase", "psk"}:
                    masked[key] = "***"
                else:
                    masked[key] = self.mask_sensitive_data(value)
            return masked

        if isinstance(payload, list):
            return [self.mask_sensitive_data(item) for item in payload]

        return payload

    def _get_hostname(self):
        try:
            return socket.gethostname()
        except OSError:
            return None

    def _get_local_ip(self):
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass

        return None
