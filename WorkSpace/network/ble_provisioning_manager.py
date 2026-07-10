from threading import Lock


class BLEProvisioningManager:
    """HTTP mock state manager for the future BLE WiFi provisioning flow.

    This class does not start Bluetooth advertising or expose GATT services.
    The /provisioning/ble/* API uses it to test the app/server provisioning
    contract before the Raspberry Pi BLE peripheral implementation exists.
    """

    STATE_NOT_STARTED = "NOT_STARTED"
    STATE_ADVERTISING = "ADVERTISING"
    STATE_CLIENT_CONNECTED = "CLIENT_CONNECTED"
    STATE_WIFI_CONFIG_RECEIVED = "WIFI_CONFIG_RECEIVED"
    STATE_WIFI_CONFIGURED = "WIFI_CONFIGURED"
    STATE_COMPLETED = "COMPLETED"
    STATE_ERROR = "ERROR"

    NEXT_START_BLE_ADVERTISING = "START_BLE_ADVERTISING"
    NEXT_WAIT_FOR_APP = "WAIT_FOR_APP"
    NEXT_SEND_WIFI_CONFIG = "SEND_WIFI_CONFIG"
    NEXT_CHECK_NETWORK_STATUS = "CHECK_NETWORK_STATUS"
    NEXT_READY_TO_REGISTER = "READY_TO_REGISTER"
    NEXT_ERROR = "ERROR"

    def __init__(
        self,
        wifi_manager,
        mode: str = "dry_run",
        device_name: str = "VisionPoseCoach-Pi",
        pairing_code: str = "123456",
    ):
        if mode not in {"dry_run", "mock", "real"}:
            mode = "dry_run"

        self.wifi_manager = wifi_manager
        self.mode = mode
        self.device_name = device_name
        self._pairing_code = pairing_code
        self._lock = Lock()
        self._advertising = False
        self._last_client_id = None
        self._last_message_type = None
        self._provisioning_state = self.STATE_NOT_STARTED
        self._provisioning_completed = False
        self._last_error = None

    def get_status(self):
        wifi_status = self._wifi_status()
        with self._lock:
            return {
                "mode": self.mode,
                "implementation": "http_mock",
                "transport": "http",
                "available": False,
                "mock_available": True,
                "real_ble": False,
                "gatt_available": False,
                "advertising": self._advertising,
                "device_name": self.device_name,
                "pairing_code": self._pairing_code,
                "provisioning_state": self._provisioning_state,
                "last_client_id": self._last_client_id,
                "last_message_type": self._last_message_type,
                "last_configured_ssid": wifi_status.get("last_configured_ssid"),
                "provisioning_completed": self._provisioning_completed,
                "last_error": self._last_error,
            }

    def get_registration_status(self):
        status = self.get_status()
        return {
            "type": "provisioning_status",
            "mode": self.mode,
            "device_name": self.device_name,
            "provisioning_state": status["provisioning_state"],
            "provisioning_completed": status["provisioning_completed"],
            "ble": {
                "available": status["available"],
                "implementation": status["implementation"],
                "transport": status["transport"],
                "mock_available": status["mock_available"],
                "real_ble": status["real_ble"],
                "gatt_available": status["gatt_available"],
                "advertising": status["advertising"],
                "last_client_id": status["last_client_id"],
                "last_message_type": status["last_message_type"],
            },
            "wifi": self._wifi_status(),
            "next_step": self._next_step(status["provisioning_state"]),
            "message": self._status_message(status["provisioning_state"]),
        }

    def start_advertising(self):
        with self._lock:
            self._advertising = True
            self._provisioning_state = self.STATE_ADVERTISING
            self._provisioning_completed = False
            self._last_error = None

        return {
            "type": "ble_advertising_result",
            "ok": True,
            "ble": self.get_status(),
            "next_step": self.NEXT_WAIT_FOR_APP,
            "message": "HTTP mock BLE provisioning advertising 상태를 시작했습니다. 실제 BLE advertising은 아직 수행하지 않습니다.",
        }

    def stop_advertising(self):
        with self._lock:
            self._advertising = False
            if self._provisioning_state == self.STATE_ADVERTISING:
                self._provisioning_state = self.STATE_NOT_STARTED
            self._last_error = None

        return {
            "type": "ble_advertising_result",
            "ok": True,
            "ble": self.get_status(),
            "next_step": self._next_step(self.get_status()["provisioning_state"]),
            "message": "HTTP mock BLE provisioning advertising 상태를 중지했습니다. 실제 BLE advertising은 아직 수행하지 않습니다.",
        }

    def handle_provisioning_message(self, payload):
        if not isinstance(payload, dict):
            return self._error_response(
                "INVALID_PROVISIONING_PAYLOAD",
                "BLE provisioning payload가 올바르지 않습니다.",
                message_type=None,
            )

        message_type = payload.get("type")
        client_id = payload.get("client_id")
        self._record_message(client_id, message_type)

        if message_type == "hello":
            with self._lock:
                self._provisioning_state = self.STATE_CLIENT_CONNECTED
                self._last_error = None
            return {
                "type": "ble_provisioning_response",
                "ok": True,
                "message_type": "hello",
                "device_name": self.device_name,
                "pairing_code": self.get_pairing_code(),
                "provisioning_state": self.STATE_CLIENT_CONNECTED,
                "provisioning_completed": self.get_status()["provisioning_completed"],
                "next_step": self.NEXT_SEND_WIFI_CONFIG,
                "message": "기기와 연결되었습니다. WiFi 정보를 전송해주세요.",
            }

        if message_type == "configure_wifi":
            return self._handle_configure_wifi(payload)

        if message_type == "status":
            return {
                "type": "ble_provisioning_response",
                "ok": True,
                "message_type": "status",
                "provisioning_state": self.get_status()["provisioning_state"],
                "provisioning_completed": self.get_status()["provisioning_completed"],
                "next_step": self._next_step(self.get_status()["provisioning_state"]),
                "ble": self.get_status(),
                "wifi": self._wifi_status(),
            }

        if message_type == "reset":
            self.reset_provisioning()
            self._record_message(client_id, message_type)
            return {
                "type": "ble_provisioning_response",
                "ok": True,
                "message_type": "reset",
                "provisioning_state": self.STATE_NOT_STARTED,
                "provisioning_completed": False,
                "next_step": self.NEXT_START_BLE_ADVERTISING,
                "message": "Provisioning 상태를 초기화했습니다.",
            }

        return self._error_response(
            "UNKNOWN_PROVISIONING_MESSAGE",
            "알 수 없는 BLE provisioning 메시지입니다.",
            message_type=message_type,
        )

    def get_pairing_code(self):
        return self._pairing_code

    def reset_provisioning(self):
        with self._lock:
            self._advertising = False
            self._last_client_id = None
            self._last_message_type = None
            self._provisioning_state = self.STATE_NOT_STARTED
            self._provisioning_completed = False
            self._last_error = None

        return {
            "type": "ble_reset_result",
            "ok": True,
            "ble": self.get_status(),
            "message": "Provisioning 상태를 초기화했습니다.",
        }

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

    def _handle_configure_wifi(self, payload):
        ssid = payload.get("ssid")
        password = payload.get("password")
        with self._lock:
            self._provisioning_state = self.STATE_WIFI_CONFIG_RECEIVED
        wifi_result = self.wifi_manager.configure_wifi(ssid, password)
        ok = bool(wifi_result.get("ok"))

        with self._lock:
            self._advertising = False if ok else self._advertising
            self._provisioning_state = self.STATE_COMPLETED if ok else self.STATE_ERROR
            self._provisioning_completed = ok
            self._last_error = None if ok else wifi_result.get("message")

        current_state = self.get_status()["provisioning_state"]
        response = {
            "type": "ble_provisioning_response",
            "ok": ok,
            "message_type": "configure_wifi",
            "provisioning_state": current_state,
            "provisioning_completed": ok,
            "next_step": self._next_step(current_state),
            "message": (
                "WiFi 설정 요청을 처리했습니다."
                if ok
                else wifi_result.get("message", "WiFi 설정 요청 처리에 실패했습니다.")
            ),
            "wifi": self._wifi_status(),
        }

        if not ok:
            response["error_code"] = "WIFI_CONFIGURE_FAILED"

        return response

    def _record_message(self, client_id, message_type):
        with self._lock:
            self._last_client_id = client_id if isinstance(client_id, str) else None
            self._last_message_type = message_type if isinstance(message_type, str) else None

    def _error_response(self, error_code, message, message_type):
        with self._lock:
            self._provisioning_state = self.STATE_ERROR
            self._last_error = message

        return {
            "type": "ble_provisioning_response",
            "ok": False,
            "message_type": message_type,
            "provisioning_state": self.STATE_ERROR,
            "provisioning_completed": False,
            "next_step": self.NEXT_ERROR,
            "error_code": error_code,
            "message": message,
        }

    def _wifi_status(self):
        status = self.wifi_manager.get_status()
        status.pop("type", None)
        return status

    def _next_step(self, provisioning_state):
        mapping = {
            self.STATE_NOT_STARTED: self.NEXT_START_BLE_ADVERTISING,
            self.STATE_ADVERTISING: self.NEXT_WAIT_FOR_APP,
            self.STATE_CLIENT_CONNECTED: self.NEXT_SEND_WIFI_CONFIG,
            self.STATE_WIFI_CONFIG_RECEIVED: self.NEXT_CHECK_NETWORK_STATUS,
            self.STATE_WIFI_CONFIGURED: self.NEXT_CHECK_NETWORK_STATUS,
            self.STATE_COMPLETED: self.NEXT_CHECK_NETWORK_STATUS,
            self.STATE_ERROR: self.NEXT_ERROR,
        }
        return mapping.get(provisioning_state, self.NEXT_ERROR)

    def _status_message(self, provisioning_state):
        mapping = {
            self.STATE_NOT_STARTED: "BLE advertising을 시작해 앱의 기기 추가 요청을 기다리세요.",
            self.STATE_ADVERTISING: "앱에서 기기를 선택하고 hello 메시지를 보낼 때까지 대기 중입니다.",
            self.STATE_CLIENT_CONNECTED: "기기와 연결되었습니다. WiFi 정보를 전송해주세요.",
            self.STATE_WIFI_CONFIG_RECEIVED: "WiFi 설정 요청을 받았습니다.",
            self.STATE_WIFI_CONFIGURED: "WiFi 설정 요청이 처리되었습니다. /network/status 또는 /health로 연결 상태를 확인하세요.",
            self.STATE_COMPLETED: "WiFi 설정 요청이 처리되었습니다. /network/status 또는 /health로 연결 상태를 확인하세요.",
            self.STATE_ERROR: "Provisioning 처리 중 오류가 발생했습니다.",
        }
        return mapping.get(provisioning_state, "Provisioning 상태를 확인할 수 없습니다.")
