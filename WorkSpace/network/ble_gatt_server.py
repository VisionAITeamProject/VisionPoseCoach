"""BlueZ D-Bus BLE peripheral for VisionPoseCoach Wi-Fi provisioning.

The optional dbus-next dependency is imported only when the server starts, so
FastAPI and unit tests remain usable on machines without BlueZ or D-Bus.
"""

import asyncio
import json
import logging
from typing import Any


DEVICE_NAME = "VisionPoseCoach-Pi"
ADVERTISE_NAME = "VPC-Pi"
SERVICE_UUID = "9f4c0001-7d9a-4b57-9d9f-000000000001"
WIFI_CONFIG_UUID = "9f4c0002-7d9a-4b57-9d9f-000000000002"
STATUS_UUID = "9f4c0003-7d9a-4b57-9d9f-000000000003"
HELLO_UUID = "9f4c0004-7d9a-4b57-9d9f-000000000004"
MAX_WRITE_BYTES = 512
WIFI_CONFIG_FLAGS = ("write",)
STATUS_FLAGS = ("read", "notify")
HELLO_FLAGS = ("read",)

BLUEZ_SERVICE = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
ADV_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
APP_PATH = "/com/visionposecoach/ble"
SERVICE_PATH = f"{APP_PATH}/service0"
CONFIG_PATH = f"{SERVICE_PATH}/char0"
STATUS_PATH = f"{SERVICE_PATH}/char1"
HELLO_PATH = f"{SERVICE_PATH}/char2"
ADVERTISEMENT_PATH = f"{APP_PATH}/advertisement0"


class BLEBackendUnavailable(RuntimeError):
    """Raised with an actionable message when BlueZ cannot host the GATT app."""


def backend_available() -> bool:
    try:
        import dbus_next  # noqa: F401
    except ImportError:
        return False
    return True


def encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def advertisement_properties(advertise_name: str | None = ADVERTISE_NAME) -> dict[str, Any]:
    """Return the BlueZ advertisement fields used by each registration attempt."""
    properties = {"Type": "peripheral", "ServiceUUIDs": [SERVICE_UUID]}
    if advertise_name is not None:
        properties["LocalName"] = advertise_name
    return properties


def hello_payload(device_name: str = DEVICE_NAME) -> dict[str, str]:
    return {"type": "device_info", "device_name": device_name, "service_uuid": SERVICE_UUID}


def decode_configure_write(value: bytes | bytearray | list[int]) -> dict[str, Any]:
    raw = bytes(value)
    if not raw or len(raw) > MAX_WRITE_BYTES:
        raise ValueError(f"BLE write는 1~{MAX_WRITE_BYTES}바이트여야 합니다.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("유효한 UTF-8 JSON payload가 필요합니다.") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON object가 필요합니다.")
    return payload


class BlueZGattServer:
    """Registers one provisioning service and advertisement with BlueZ."""

    def __init__(
        self,
        provisioning_manager,
        device_name: str = DEVICE_NAME,
        advertise_name: str = ADVERTISE_NAME,
        logger=None,
    ):
        self.manager = provisioning_manager
        self.device_name = device_name
        self.advertise_name = advertise_name
        self.local_name_included = True
        self.log = logger or logging.getLogger(__name__)
        self._bus = None
        self._adapter_path = None
        self._gatt_manager = None
        self._adv_manager = None
        self._exports: list[tuple[str, Any]] = []
        self._advertisement = None
        self._status_characteristic = None
        self._stopped = asyncio.Event()

    def status_payload(self) -> dict[str, Any]:
        current = self.manager.get_status()
        wifi = self.manager.wifi_manager.get_status()
        legacy_state = current.get("provisioning_state")
        state_map = {
            "NOT_STARTED": self.manager.BLE_STATE_IDLE,
            "ADVERTISING": self.manager.BLE_STATE_ADVERTISING,
            "CLIENT_CONNECTED": self.manager.BLE_STATE_CONNECTED,
            "WIFI_CONFIG_RECEIVED": self.manager.BLE_STATE_WIFI_CONFIGURING,
            "WIFI_CONFIGURED": self.manager.BLE_STATE_WIFI_CONNECTED,
            "COMPLETED": self.manager.BLE_STATE_WIFI_CONNECTED,
            "ERROR": self.manager.BLE_STATE_FAILED,
        }
        return {
            "mode": "real_ble",
            "device_name": self.device_name,
            "state": state_map.get(legacy_state, self.manager.BLE_STATE_IDLE),
            "wifi_connected": bool(wifi.get("connected")),
            "ssid": wifi.get("ssid") or wifi.get("last_configured_ssid"),
            "last_error": current.get("last_error"),
        }

    async def start(self):
        api = _load_dbus_api()
        self._api = api
        self._bus = await api["MessageBus"](bus_type=api["BusType"].SYSTEM).connect()
        self._adapter_path = await self._find_adapter()
        await self._build_and_export_objects()
        await self._gatt_manager.call_register_application(APP_PATH, {})
        await self._register_advertisement_with_fallback()
        self.manager.start_advertising()
        self.log.info(
            "BLE GATT provisioning started: device_name=%s advertise_name=%s",
            self.device_name,
            self.advertise_name,
        )

    async def stop(self):
        if self._bus is None:
            return
        try:
            if self._adv_manager and self._advertisement:
                await self._adv_manager.call_unregister_advertisement(ADVERTISEMENT_PATH)
        except Exception as exc:  # BlueZ may already be gone during shutdown.
            self.log.debug("BLE advertisement cleanup skipped: %s", type(exc).__name__)
        try:
            if self._gatt_manager:
                await self._gatt_manager.call_unregister_application(APP_PATH)
        except Exception as exc:
            self.log.debug("GATT cleanup skipped: %s", type(exc).__name__)
        for path, interface in reversed(self._exports):
            self._bus.unexport(path, interface)
        self._exports.clear()
        self.manager.stop_advertising()
        self._bus.disconnect()
        self._bus = None
        self._stopped.set()

    async def wait(self):
        await self._stopped.wait()

    async def _find_adapter(self):
        introspection = await self._bus.introspect(BLUEZ_SERVICE, "/")
        root = self._bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        objects = await root.get_interface(DBUS_OBJECT_MANAGER_IFACE).call_get_managed_objects()
        for path, interfaces in objects.items():
            if GATT_MANAGER_IFACE in interfaces and ADV_MANAGER_IFACE in interfaces:
                return path
        raise BLEBackendUnavailable(
            "BLE GATT/advertising 지원 BlueZ adapter를 찾지 못했습니다. bluetooth.service, rfkill, adapter 전원을 확인하세요."
        )

    async def _build_and_export_objects(self):
        api = self._api
        introspection = await self._bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        adapter = self._bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        self._gatt_manager = adapter.get_interface(GATT_MANAGER_IFACE)
        self._adv_manager = adapter.get_interface(ADV_MANAGER_IFACE)

        classes = _build_dbus_classes(api)
        self._classes = classes
        status_reader = lambda: encode_json(self.status_payload())
        self._status_characteristic = classes["Characteristic"](
            STATUS_PATH, STATUS_UUID, SERVICE_PATH, list(STATUS_FLAGS), read=status_reader
        )
        config = classes["Characteristic"](
            CONFIG_PATH, WIFI_CONFIG_UUID, SERVICE_PATH, list(WIFI_CONFIG_FLAGS), write=self._on_config_write
        )
        hello = classes["Characteristic"](
            HELLO_PATH,
            HELLO_UUID,
            SERVICE_PATH,
            list(HELLO_FLAGS),
            read=lambda: encode_json(hello_payload(self.device_name)),
        )
        service = classes["Service"](SERVICE_PATH, SERVICE_UUID, [CONFIG_PATH, STATUS_PATH, HELLO_PATH])
        app = classes["Application"]({
            SERVICE_PATH: service,
            CONFIG_PATH: config,
            STATUS_PATH: self._status_characteristic,
            HELLO_PATH: hello,
        })
        self._advertisement = classes["Advertisement"](ADVERTISEMENT_PATH, self.advertise_name)
        for path, interface in [
            (APP_PATH, app), (SERVICE_PATH, service), (CONFIG_PATH, config),
            (STATUS_PATH, self._status_characteristic), (HELLO_PATH, hello),
            (ADVERTISEMENT_PATH, self._advertisement),
        ]:
            self._bus.export(path, interface)
            self._exports.append((path, interface))

    async def _register_advertisement_with_fallback(self):
        try:
            await self._adv_manager.call_register_advertisement(ADVERTISEMENT_PATH, {})
            return
        except Exception as exc:
            self._log_advertisement_error(exc, local_name_included=True)
            if not _is_advertisement_parameter_error(exc):
                raise

        self.log.warning(
            "Retrying BLE advertisement registration without LocalName: service_uuid=%s",
            SERVICE_UUID,
        )
        self._replace_advertisement_with_service_uuid_only()
        try:
            await self._adv_manager.call_register_advertisement(ADVERTISEMENT_PATH, {})
        except Exception as exc:
            self._log_advertisement_error(exc, local_name_included=False)
            raise
        self.log.info("BLE advertisement registered with ServiceUUIDs only (LocalName omitted)")

    def _replace_advertisement_with_service_uuid_only(self):
        previous = self._advertisement
        self._bus.unexport(ADVERTISEMENT_PATH, previous)
        self._exports = [
            (path, interface)
            for path, interface in self._exports
            if not (path == ADVERTISEMENT_PATH and interface is previous)
        ]
        self._advertisement = self._classes["ServiceOnlyAdvertisement"](ADVERTISEMENT_PATH)
        self.local_name_included = False
        self._bus.export(ADVERTISEMENT_PATH, self._advertisement)
        self._exports.append((ADVERTISEMENT_PATH, self._advertisement))

    def _log_advertisement_error(self, exc: Exception, *, local_name_included: bool):
        error_name, error_message = _dbus_error_details(exc)
        self.log.error(
            "BLE advertisement registration failed: adapter path=%s; device_name=%s; "
            "advertise_name=%s; service_uuid=%s; local_name included=%s; "
            "service_uuid included=yes; dbus error type/name=%s; dbus error message=%s",
            self._adapter_path,
            self.device_name,
            self.advertise_name,
            SERVICE_UUID,
            "yes" if local_name_included else "no",
            error_name,
            error_message,
        )

    def _on_config_write(self, value):
        try:
            payload = decode_configure_write(value)
        except ValueError as exc:
            self.manager._error_response("INVALID_GATT_WRITE", str(exc), None)
            self._notify_status()
            return
        asyncio.create_task(self._configure_wifi(payload))

    async def _configure_wifi(self, payload):
        # nmcli is blocking; keep the D-Bus event loop responsive.
        await asyncio.to_thread(self.manager.handle_gatt_configure, payload)
        self._notify_status()

    def _notify_status(self):
        if self._status_characteristic:
            self._status_characteristic.update_value(encode_json(self.status_payload()))


def _load_dbus_api():
    try:
        from dbus_next import BusType, Variant
        from dbus_next.aio import MessageBus
        from dbus_next.service import ServiceInterface, dbus_property, method
        from dbus_next.constants import PropertyAccess
    except ImportError as exc:
        raise BLEBackendUnavailable(
            "실제 BLE 서버에는 dbus-next가 필요합니다. requirements-server.txt를 설치하세요."
        ) from exc
    return locals()


def _dbus_error_details(exc: Exception) -> tuple[str, str]:
    error_name = getattr(exc, "type", None) or getattr(exc, "name", None) or type(exc).__name__
    error_message = getattr(exc, "text", None) or getattr(exc, "message", None) or str(exc)
    return str(error_name), str(error_message)


def _is_advertisement_parameter_error(exc: Exception) -> bool:
    error_name, error_message = _dbus_error_details(exc)
    combined = f"{error_name} {error_message}".lower()
    return (
        "invalidparameters" in combined
        or "invalid parameters" in combined
        or "failed to register advertisement" in combined
    )


def _build_dbus_classes(api):
    ServiceInterface = api["ServiceInterface"]
    dbus_property, method = api["dbus_property"], api["method"]
    PropertyAccess, Variant = api["PropertyAccess"], api["Variant"]

    class Application(ServiceInterface):
        def __init__(self, objects):
            super().__init__(DBUS_OBJECT_MANAGER_IFACE)
            self.objects = objects

        @method()
        def GetManagedObjects(self) -> "a{oa{sa{sv}}}":
            return {path: obj.managed() for path, obj in self.objects.items()}

    class Service(ServiceInterface):
        def __init__(self, path, uuid, characteristics):
            super().__init__("org.bluez.GattService1")
            self.path, self.uuid, self.characteristics = path, uuid, characteristics

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s": return self.uuid
        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> "b": return True
        @dbus_property(access=PropertyAccess.READ)
        def Characteristics(self) -> "ao": return self.characteristics
        def managed(self):
            return {self.name: {"UUID": Variant("s", self.uuid), "Primary": Variant("b", True), "Characteristics": Variant("ao", self.characteristics)}}

    class Characteristic(ServiceInterface):
        def __init__(self, path, uuid, service_path, flags, read=None, write=None):
            super().__init__("org.bluez.GattCharacteristic1")
            self.path, self.uuid, self.service_path, self.flags = path, uuid, service_path, flags
            self.reader, self.writer, self.value, self.notifying = read, write, b"", False

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s": return self.uuid
        @dbus_property(access=PropertyAccess.READ)
        def Service(self) -> "o": return self.service_path
        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> "as": return self.flags
        @dbus_property(access=PropertyAccess.READ)
        def Notifying(self) -> "b": return self.notifying
        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> "ay": return self.value
        @method()
        def ReadValue(self, options: "a{sv}") -> "ay":
            return self.reader() if self.reader else self.value
        @method()
        def WriteValue(self, value: "ay", options: "a{sv}"):
            if self.writer: self.writer(value)
        @method()
        def StartNotify(self): self.notifying = True
        @method()
        def StopNotify(self): self.notifying = False
        def update_value(self, value):
            self.value = value
            if self.notifying: self.emit_properties_changed({"Value": value})
        def managed(self):
            return {self.name: {"UUID": Variant("s", self.uuid), "Service": Variant("o", self.service_path), "Flags": Variant("as", self.flags)}}

    class Advertisement(ServiceInterface):
        def __init__(self, path, local_name):
            super().__init__("org.bluez.LEAdvertisement1")
            self.path = path
            self.properties = advertisement_properties(local_name)
        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s": return self.properties["Type"]
        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> "as": return self.properties["ServiceUUIDs"]
        @dbus_property(access=PropertyAccess.READ)
        def LocalName(self) -> "s": return self.properties["LocalName"]
        @method()
        def Release(self): pass

    class ServiceOnlyAdvertisement(ServiceInterface):
        """Fallback advertisement whose D-Bus interface omits LocalName entirely."""

        def __init__(self, path):
            super().__init__("org.bluez.LEAdvertisement1")
            self.path = path
            self.properties = advertisement_properties(None)
        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s": return self.properties["Type"]
        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> "as": return self.properties["ServiceUUIDs"]
        @method()
        def Release(self): pass

    return {
        "Application": Application,
        "Service": Service,
        "Characteristic": Characteristic,
        "Advertisement": Advertisement,
        "ServiceOnlyAdvertisement": ServiceOnlyAdvertisement,
    }
