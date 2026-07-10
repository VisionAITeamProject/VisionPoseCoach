import os
import socket
import subprocess
from threading import Lock


class WiFiManager:
    VALID_MODES = {"dry_run", "mock", "real"}

    def __init__(self, mode: str | None = None, command_timeout: int = 20):
        if mode is None:
            mode = os.getenv("VPC_WIFI_MODE", "dry_run")

        if isinstance(mode, str):
            mode = mode.strip().lower()

        if mode not in self.VALID_MODES:
            mode = "dry_run"

        self.mode = mode
        self.command_timeout = command_timeout
        self._lock = Lock()
        self._connected = False
        self._ssid = None
        self._last_configured_ssid = None
        self._last_error = None

    def get_status(self):
        if self.mode == "real":
            with self._lock:
                last_configured_ssid = self._last_configured_ssid
            real_status = self._get_real_status()
            real_status["last_configured_ssid"] = last_configured_ssid
            return real_status

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
            "online": connected,
        }

    def get_network_status(self):
        status = self.get_status()
        status.pop("type", None)
        return {
            "type": "network_status",
            "wifi": status,
        }

    def list_networks(self):
        if self.mode == "mock":
            return {
                "type": "wifi_scan",
                "ok": True,
                "mode": self.mode,
                "networks": [
                    {"ssid": "VisionCoach-Lab", "signal": 92, "security": "WPA2", "secured": True},
                    {"ssid": "Home-Training", "signal": 78, "security": "WPA2", "secured": True},
                    {"ssid": "Open-Studio", "signal": 41, "security": "", "secured": False},
                ],
                "message": "mock WiFi 목록을 반환했습니다.",
            }

        if self.mode == "real":
            return self._list_real_networks()

        return {
            "type": "wifi_scan",
            "ok": True,
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

        if self.mode == "mock":
            with self._lock:
                self._connected = True
                self._ssid = normalized_ssid
            return {
                "type": "wifi_configure_result",
                "ok": True,
                "mode": self.mode,
                "ssid": normalized_ssid,
                "connected": True,
                "message": "mock WiFi 연결 성공 응답을 반환했습니다.",
            }

        if self.mode == "real":
            return self._configure_real_wifi(normalized_ssid, password)

        return {
            "type": "wifi_configure_result",
            "ok": True,
            "mode": self.mode,
            "ssid": normalized_ssid,
            "connected": False,
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

    def _list_real_networks(self):
        result = self._run_nmcli(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes",
            ]
        )
        if not result["ok"]:
            return self._wifi_error("wifi_scan", result["message"], networks=[])

        networks_by_ssid = {}
        for line in result["stdout"].splitlines():
            parsed = self._parse_scan_line(line)
            if parsed is None:
                continue
            current = networks_by_ssid.get(parsed["ssid"])
            if current is None or parsed["signal"] > current["signal"]:
                networks_by_ssid[parsed["ssid"]] = parsed

        networks = sorted(networks_by_ssid.values(), key=lambda item: item["signal"], reverse=True)
        return {
            "type": "wifi_scan",
            "ok": True,
            "mode": self.mode,
            "networks": networks,
            "message": "WiFi 목록을 조회했습니다.",
        }

    def _configure_real_wifi(self, ssid, password):
        result = self._run_nmcli(["nmcli", "device", "wifi", "connect", ssid, "password", password])
        result_message = self._sanitize_sensitive_text(result["message"], password)
        if not result["ok"]:
            with self._lock:
                self._connected = False
                self._ssid = None
                self._last_error = result_message
            return {
                "type": "wifi_configure_result",
                "ok": False,
                "mode": self.mode,
                "ssid": ssid,
                "connected": False,
                "message": result_message,
            }

        with self._lock:
            self._connected = True
            self._ssid = ssid
            self._last_error = None

        return {
            "type": "wifi_configure_result",
            "ok": True,
            "mode": self.mode,
            "ssid": ssid,
            "connected": True,
            "message": "WiFi connected",
        }

    def _get_real_status(self):
        connected = False
        ssid = None
        last_error = None

        result = self._run_nmcli(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
        if result["ok"]:
            for line in result["stdout"].splitlines():
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0] == "yes" and parts[1].strip():
                    connected = True
                    ssid = parts[1].strip()
                    break
        else:
            last_error = result["message"]

        with self._lock:
            self._connected = connected
            self._ssid = ssid
            self._last_error = last_error

        local_ip = self._get_hostname_ip()
        return {
            "type": "wifi_status",
            "mode": self.mode,
            "connected": connected,
            "ssid": ssid,
            "local_ip": local_ip,
            "hostname": self._get_hostname(),
            "provisioning_required": not connected,
            "last_error": last_error,
            "online": connected and bool(local_ip),
        }

    def _get_hostname_ip(self):
        try:
            result = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            if result.returncode == 0:
                first_ip = result.stdout.strip().split()
                if first_ip:
                    return first_ip[0]
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            pass
        return self._get_local_ip()

    def _parse_scan_line(self, line):
        if not line or not line.strip():
            return None

        parts = self._split_nmcli_terse_line(line, expected_fields=3)
        if len(parts) < 3:
            return None

        ssid = parts[0].strip()
        if not ssid:
            return None

        try:
            signal = int(parts[1].strip())
        except ValueError:
            signal = 0

        security = parts[2].strip()
        secured = bool(security and security != "--")
        return {
            "ssid": ssid,
            "signal": signal,
            "security": security,
            "secured": secured,
        }

    def _split_nmcli_terse_line(self, line, expected_fields):
        parts = []
        current = []
        escaped = False

        for char in line:
            if escaped:
                current.append(char)
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == ":" and len(parts) < expected_fields - 1:
                parts.append("".join(current))
                current = []
                continue

            current.append(char)

        if escaped:
            current.append("\\")

        parts.append("".join(current))
        return parts

    def _run_nmcli(self, command):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
                shell=False,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "stdout": "",
                "message": "nmcli를 찾을 수 없습니다. Raspberry Pi OS에서 NetworkManager/nmcli 설치 상태를 확인하세요.",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "stdout": "",
                "message": "nmcli 명령이 시간 초과되었습니다. WiFi 장치 상태를 확인하세요.",
            }
        except OSError as exc:
            return {
                "ok": False,
                "stdout": "",
                "message": f"nmcli 실행에 실패했습니다: {exc}",
            }

        if result.returncode == 0:
            return {"ok": True, "stdout": result.stdout, "message": "ok"}

        message = (result.stderr or result.stdout or "nmcli 명령이 실패했습니다.").strip()
        return {"ok": False, "stdout": result.stdout, "message": message}

    def _wifi_error(self, response_type, message, networks=None):
        with self._lock:
            self._last_error = message

        response = {
            "type": response_type,
            "ok": False,
            "mode": self.mode,
            "message": message,
        }
        if networks is not None:
            response["networks"] = networks
        return response

    def _sanitize_sensitive_text(self, text, secret):
        if not isinstance(text, str):
            return text
        if isinstance(secret, str) and secret:
            return text.replace(secret, "***")
        return text
