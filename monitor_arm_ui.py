#!/usr/bin/env python3
"""SO-101 based four-servo monitor-arm controller.

The application starts in simulation mode.  Supplying ``--hardware`` enables
the Feetech STS3215 bus, but the serial port is still opened only when the user
presses the connect button.

Motor mapping used by this project:
    ID 1: shoulder_lift
    ID 2: elbow_flex
    ID 3: wrist_roll
    ID 4: wrist_flex
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from dataclasses import dataclass
from typing import Dict, Mapping, Protocol


ROOT_DIR = Path(__file__).resolve().parent
URDF_PATH = ROOT_DIR / "SO-ARM100-main/Simulation/SO101/so101_new_calib.urdf"
SDK_PATH = ROOT_DIR / "STServo_Python/stservo-env/scservo_sdk"
CALIBRATION_PATH = ROOT_DIR / "monitor_arm_calibration.json"


class KinematicsError(ValueError):
    """Raised when a requested monitor position is outside the workspace."""


@dataclass(frozen=True)
class ArmGeometry:
    """Planar geometry derived from ``so101_new_calib.urdf`` (metres/radians)."""

    shoulder_x: float = 0.0692345
    shoulder_z: float = 0.1166
    upper_arm_length: float = math.hypot(0.028, 0.11257)
    lower_arm_length: float = math.hypot(0.1349, 0.0052)
    upper_zero_angle: float = math.atan2(0.11257, 0.028)
    lower_zero_angle: float = math.atan2(0.0052, 0.1349)
    # Exact zero-pose transforms from wrist_flex to the gripper motor output axis.
    wrist_to_roll_x: float = 0.0611
    roll_to_gripper_x: float = 0.0234
    roll_to_gripper_y: float = 0.0177956
    roll_to_gripper_z: float = 0.021091
    # Neutral gripper motor axis height in the new-calibration URDF is 0.255461 m.
    fixed_height: float = 0.255461


@dataclass(frozen=True)
class JointConfig:
    servo_id: int
    name: str
    minimum: float
    maximum: float


JOINTS: Dict[str, JointConfig] = {
    "shoulder_lift": JointConfig(1, "shoulder_lift", -1.74533, 1.74533),
    "elbow_flex": JointConfig(2, "elbow_flex", -1.69, 1.69),
    "wrist_roll": JointConfig(3, "wrist_roll", -2.74385, 2.84121),
    "wrist_flex": JointConfig(4, "wrist_flex", -1.65806, 1.65806),
}


@dataclass
class ServoCalibration:
    zero_tick: int = 2048
    direction: int = 1


class CalibrationStore:
    """Persistent assembly-specific mapping between URDF angles and raw ticks."""

    def __init__(self, path: Path = CALIBRATION_PATH) -> None:
        self.path = path
        self.values = {name: ServoCalibration() for name in JOINTS}

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            joints = data["joints"]
            for name in JOINTS:
                item = joints[name]
                direction = int(item["direction"])
                zero_tick = int(item["zero_tick"])
                if direction not in (-1, 1):
                    raise ValueError(f"{name} direction must be -1 or 1")
                if not 0 <= zero_tick <= 4095:
                    raise ValueError(f"{name} zero_tick must be 0..4095")
                self.values[name] = ServoCalibration(zero_tick, direction)
            return True
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"캘리브레이션 파일 오류: {self.path}: {exc}") from exc

    def save(self) -> None:
        data = {
            "version": 1,
            "reference_pose": "upper arm vertical, lower arm horizontal (L pose)",
            "joints": {
                name: {
                    "servo_id": JOINTS[name].servo_id,
                    "zero_tick": value.zero_tick,
                    "direction": value.direction,
                }
                for name, value in self.values.items()
            },
        }
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def calibrate_from_pose(
        self,
        raw_ticks: Mapping[str, int],
        known_angles: Mapping[str, float],
    ) -> None:
        ticks_per_radian = 4096.0 / (2.0 * math.pi)
        calculated: Dict[str, int] = {}
        for name in JOINTS:
            calibration = self.values[name]
            zero_tick = round(
                raw_ticks[name]
                - calibration.direction * known_angles[name] * ticks_per_radian
            )
            if not 0 <= zero_tick <= 4095:
                raise ValueError(
                    f"{name} 계산 영점 {zero_tick}이 엔코더 범위를 벗어납니다. "
                    "방향 설정과 기준 자세를 확인하세요."
                )
            calculated[name] = zero_tick
        for name, zero_tick in calculated.items():
            self.values[name].zero_tick = zero_tick


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def radians_to_tick(
    angle: float,
    joint: JointConfig,
    calibration: ServoCalibration | None = None,
) -> int:
    """Convert a new-calibration URDF angle to an STS3215 encoder position."""

    if not joint.minimum <= angle <= joint.maximum:
        raise KinematicsError(
            f"{joint.name} 명령 {math.degrees(angle):.1f}°가 URDF 제한을 벗어납니다."
        )
    calibration = calibration or ServoCalibration()
    tick = calibration.zero_tick + calibration.direction * round(
        angle * 4096.0 / (2.0 * math.pi)
    )
    if not 0 <= tick <= 4095:
        raise KinematicsError(
            f"{joint.name} 변환 tick {tick}이 0~4095 범위를 벗어납니다. "
            "조립 영점 또는 모터 방향을 확인하세요."
        )
    return tick


def tick_to_radians(
    tick: int,
    calibration: ServoCalibration | None = None,
) -> float:
    calibration = calibration or ServoCalibration()
    return (
        calibration.direction
        * (tick - calibration.zero_tick)
        * (2.0 * math.pi / 4096.0)
    )


class PlanarMonitorArm:
    """SO-101 IK including the wrist, roll housing, and gripper motor axis."""

    def __init__(self, geometry: ArmGeometry | None = None) -> None:
        self.geometry = geometry or ArmGeometry()

    def solve(
        self,
        target_x: float,
        target_z: float,
        monitor_pitch: float = 0.0,
        wrist_roll: float = 0.0,
    ) -> Dict[str, float]:
        """Solve shoulder/elbow so the gripper motor axis reaches the target."""

        g = self.geometry
        tool_x, tool_z = self.tool_offset(monitor_pitch, wrist_roll)
        wrist_target_x = target_x - tool_x
        wrist_target_z = target_z - tool_z
        dx = wrist_target_x - g.shoulder_x
        dz = wrist_target_z - g.shoulder_z
        radius = math.hypot(dx, dz)
        minimum_reach = abs(g.upper_arm_length - g.lower_arm_length)
        maximum_reach = g.upper_arm_length + g.lower_arm_length
        if radius < minimum_reach - 1e-9 or radius > maximum_reach + 1e-9:
            raise KinematicsError(
                f"목표점이 가동범위 밖입니다: 어깨에서 {radius * 100:.1f}cm "
                f"(허용 {minimum_reach * 100:.1f}~{maximum_reach * 100:.1f}cm)"
            )

        cosine = (radius * radius - g.upper_arm_length**2 - g.lower_arm_length**2) / (
            2.0 * g.upper_arm_length * g.lower_arm_length
        )
        cosine = clamp(cosine, -1.0, 1.0)

        # Negative relative link angle selects the non-folded, monitor-arm branch.
        relative_link_angle = -math.acos(cosine)
        upper_world_angle = math.atan2(dz, dx) - math.atan2(
            g.lower_arm_length * math.sin(relative_link_angle),
            g.upper_arm_length + g.lower_arm_length * math.cos(relative_link_angle),
        )

        shoulder = g.upper_zero_angle - upper_world_angle
        elbow = (
            g.lower_zero_angle
            - g.upper_zero_angle
            - relative_link_angle
        )

        self._validate_joint("shoulder_lift", shoulder)
        self._validate_joint("elbow_flex", elbow)
        return {"shoulder_lift": shoulder, "elbow_flex": elbow}

    def forward_wrist(self, shoulder: float, elbow: float) -> tuple[float, float]:
        """Return the wrist_flex pivot position for two URDF joint angles."""

        g = self.geometry
        upper_angle = g.upper_zero_angle - shoulder
        lower_angle = g.lower_zero_angle - shoulder - elbow
        x = (
            g.shoulder_x
            + g.upper_arm_length * math.cos(upper_angle)
            + g.lower_arm_length * math.cos(lower_angle)
        )
        z = (
            g.shoulder_z
            + g.upper_arm_length * math.sin(upper_angle)
            + g.lower_arm_length * math.sin(lower_angle)
        )
        return x, z

    def forward_motor(
        self,
        shoulder: float,
        elbow: float,
        wrist_flex: float,
        wrist_roll: float,
    ) -> tuple[float, float]:
        """Return the gripper motor output-axis position using the full chain."""

        wrist_x, wrist_z = self.forward_wrist(shoulder, elbow)
        total_pitch = shoulder + elbow + wrist_flex
        tool_x, tool_z = self.tool_offset(total_pitch, wrist_roll)
        return wrist_x + tool_x, wrist_z + tool_z

    def tool_offset(self, monitor_pitch: float, wrist_roll: float) -> tuple[float, float]:
        """Return wrist_flex-to-gripper-axis X/Z offset from URDF transforms."""

        g = self.geometry
        # wrist_roll rotates the off-axis gripper motor origin around local X.
        base_x = g.wrist_to_roll_x + g.roll_to_gripper_x
        rolled_z = (
            -g.roll_to_gripper_y * math.sin(wrist_roll)
            + g.roll_to_gripper_z * math.cos(wrist_roll)
        )
        # wrist_flex/arm pitch rotates the resulting tool vector in the X-Z plane.
        x = base_x * math.cos(monitor_pitch) + rolled_z * math.sin(monitor_pitch)
        z = -base_x * math.sin(monitor_pitch) + rolled_z * math.cos(monitor_pitch)
        return x, z

    def l_pose_angles(self) -> Dict[str, float]:
        """New-calibration angles for vertical/horizontal printed-frame L pose."""

        # At URDF zero the upper_arm_link X axis is vertical and the
        # lower_arm_link X axis is horizontal.  Joint-center vectors are
        # intentionally not used here because their motor offsets are angled.
        return {
            "shoulder_lift": 0.0,
            "elbow_flex": 0.0,
            "wrist_roll": 0.0,
            "wrist_flex": 0.0,
        }

    @staticmethod
    def gimbal_wrist_flex(shoulder: float, elbow: float, pitch_offset: float = 0.0) -> float:
        """Compensate arm pitch so the monitor keeps its initial orientation."""

        wrist = -(shoulder + elbow) + pitch_offset
        PlanarMonitorArm._validate_joint("wrist_flex", wrist)
        return wrist

    @staticmethod
    def _validate_joint(name: str, angle: float) -> None:
        joint = JOINTS[name]
        if not joint.minimum <= angle <= joint.maximum:
            raise KinematicsError(
                f"{name} 계산값 {math.degrees(angle):.1f}°가 URDF 제한 "
                f"{math.degrees(joint.minimum):.1f}~{math.degrees(joint.maximum):.1f}°를 벗어납니다."
            )


class ServoBus(Protocol):
    connected: bool

    def connect(self) -> str: ...

    def send(self, angles: Mapping[str, float]) -> Dict[str, int]: ...

    def hold(self) -> Dict[str, int]: ...

    def read_positions(self) -> Dict[str, int]: ...

    def set_torque(self, enabled: bool) -> None: ...

    def close(self) -> None: ...


class SimulationBus:
    def __init__(self, calibrations: CalibrationStore) -> None:
        self.calibrations = calibrations
        self.connected = False
        self.last_ticks = {
            name: calibration.zero_tick
            for name, calibration in calibrations.values.items()
        }
        self.torque_enabled = True

    def connect(self) -> str:
        self.connected = True
        return "시뮬레이션 연결됨"

    def send(self, angles: Mapping[str, float]) -> Dict[str, int]:
        if not self.connected:
            raise RuntimeError("먼저 시뮬레이션을 연결하세요.")
        self.last_ticks = {
            name: radians_to_tick(
                angle,
                JOINTS[name],
                self.calibrations.values[name],
            )
            for name, angle in angles.items()
        }
        return dict(self.last_ticks)

    def hold(self) -> Dict[str, int]:
        if not self.connected:
            raise RuntimeError("먼저 시뮬레이션을 연결하세요.")
        return dict(self.last_ticks)

    def read_positions(self) -> Dict[str, int]:
        if not self.connected:
            raise RuntimeError("먼저 시뮬레이션을 연결하세요.")
        return dict(self.last_ticks)

    def set_torque(self, enabled: bool) -> None:
        if not self.connected:
            raise RuntimeError("먼저 시뮬레이션을 연결하세요.")
        self.torque_enabled = enabled

    def close(self) -> None:
        self.connected = False


class FeetechBus:
    """Small adapter around the Feetech SCServo Python SDK bundled in this repo."""

    def __init__(
        self,
        device: str,
        calibrations: CalibrationStore,
        baudrate: int = 1_000_000,
        speed: int = 800,
        acceleration: int = 30,
    ) -> None:
        self.device = device
        self.calibrations = calibrations
        self.baudrate = baudrate
        self.speed = speed
        self.acceleration = acceleration
        self.connected = False
        self.port_handler = None
        self.packet_handler = None
        self.comm_success = 0

    def connect(self) -> str:
        if self.connected:
            return f"하드웨어 연결됨: {self.device}"
        if not SDK_PATH.is_dir():
            raise RuntimeError(f"Feetech SDK 폴더를 찾을 수 없습니다: {SDK_PATH}")
        if str(SDK_PATH) not in sys.path:
            sys.path.insert(0, str(SDK_PATH))

        from port_handler import PortHandler  # type: ignore
        from sms_sts import sms_sts  # type: ignore
        from scservo_def import COMM_SUCCESS  # type: ignore

        self.comm_success = COMM_SUCCESS
        self.port_handler = PortHandler(self.device)
        self.packet_handler = sms_sts(self.port_handler)
        if not self.port_handler.openPort():
            raise RuntimeError(f"시리얼 포트를 열 수 없습니다: {self.device}")
        if not self.port_handler.setBaudRate(self.baudrate):
            self.port_handler.closePort()
            raise RuntimeError(f"보레이트 설정 실패: {self.baudrate}")

        missing = []
        for joint in JOINTS.values():
            _model, result, error = self.packet_handler.ping(joint.servo_id)
            if result != self.comm_success or error != 0:
                missing.append(str(joint.servo_id))
        if missing:
            self.port_handler.closePort()
            raise RuntimeError(f"응답하지 않는 모터 ID: {', '.join(missing)}")

        self.connected = True
        return f"하드웨어 연결됨: {self.device} (ID 1~4 확인 완료)"

    def send(self, angles: Mapping[str, float]) -> Dict[str, int]:
        if not self.connected or self.packet_handler is None:
            raise RuntimeError("먼저 모터 버스를 연결하세요.")

        ticks = {
            name: radians_to_tick(
                angle,
                JOINTS[name],
                self.calibrations.values[name],
            )
            for name, angle in angles.items()
        }
        self._send_ticks(ticks)
        return ticks

    def hold(self) -> Dict[str, int]:
        """Read all present positions and immediately command those positions."""

        if not self.connected or self.packet_handler is None:
            raise RuntimeError("먼저 모터 버스를 연결하세요.")
        ticks = self.read_positions()
        self._send_ticks(ticks)
        return ticks

    def read_positions(self) -> Dict[str, int]:
        if not self.connected or self.packet_handler is None:
            raise RuntimeError("먼저 모터 버스를 연결하세요.")
        ticks: Dict[str, int] = {}
        for name, joint in JOINTS.items():
            position, result, error = self.packet_handler.ReadPos(joint.servo_id)
            if result != self.comm_success or error != 0:
                raise RuntimeError(f"ID {joint.servo_id} 현재 위치 읽기 실패")
            ticks[name] = int(clamp(position, 0, 4095))
        return ticks

    def set_torque(self, enabled: bool) -> None:
        if not self.connected or self.packet_handler is None:
            raise RuntimeError("먼저 모터 버스를 연결하세요.")
        # Address 40 is SMS_STS_TORQUE_ENABLE in the bundled SDK.
        for joint in JOINTS.values():
            result, error = self.packet_handler.write1ByteTxRx(
                joint.servo_id,
                40,
                1 if enabled else 0,
            )
            if result != self.comm_success or error != 0:
                state = "활성화" if enabled else "해제"
                raise RuntimeError(f"ID {joint.servo_id} 토크 {state} 실패")

    def _send_ticks(self, ticks: Mapping[str, int]) -> None:
        sync = self.packet_handler.groupSyncWrite
        sync.clearParam()
        for name, tick in ticks.items():
            joint = JOINTS[name]
            if not self.packet_handler.SyncWritePosEx(
                joint.servo_id, tick, self.speed, self.acceleration
            ):
                sync.clearParam()
                raise RuntimeError(f"ID {joint.servo_id} 동기 명령 구성 실패")
        result = sync.txPacket()
        sync.clearParam()
        if result != self.comm_success:
            raise RuntimeError(self.packet_handler.getTxRxResult(result))

    def close(self) -> None:
        if self.port_handler is not None:
            self.port_handler.closePort()
        self.connected = False


class MonitorArmUI:
    def __init__(
        self,
        root: tk.Tk,
        bus: ServoBus,
        calibrations: CalibrationStore,
        hardware_mode: bool,
    ) -> None:
        self.root = root
        self.bus = bus
        self.calibrations = calibrations
        self.hardware_mode = hardware_mode
        self.kinematics = PlanarMonitorArm()
        self.geometry = self.kinematics.geometry
        self.current_angles = {name: 0.0 for name in JOINTS}
        self.valid_target = True
        self.calibration_torque_released = False

        self.face_base_cm = tk.DoubleVar(value=75.0)
        self.target_distance_cm = tk.DoubleVar(value=50.0)
        self.auto_ik = tk.BooleanVar(value=True)
        self.gimbal_lock = tk.BooleanVar(value=True)
        self.pitch_offset_deg = tk.DoubleVar(value=0.0)
        self.status = tk.StringVar(value="연결 대기 중")
        self.calibration_status = tk.StringVar(
            value=(
                f"캘리브레이션: {calibrations.path.name}"
                if calibrations.path.exists()
                else "캘리브레이션: 기본값 사용 중 (아직 저장되지 않음)"
            )
        )
        self.target_text = tk.StringVar()
        self.joint_vars = {name: tk.DoubleVar(value=0.0) for name in JOINTS}
        self.reverse_vars = {
            name: tk.BooleanVar(value=calibrations.values[name].direction < 0)
            for name in JOINTS
        }
        self.joint_value_labels: Dict[str, ttk.Label] = {}
        self.joint_scales: Dict[str, ttk.Scale] = {}

        self.root.title("POCO SO-101 Monitor Arm Controller")
        self.root.geometry("1040x860")
        self.root.minsize(940, 780)
        self._build()
        self._refresh_target()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(1, weight=1)

        title = ttk.Label(outer, text="SO-101 4축 모니터암", font=("TkDefaultFont", 18, "bold"))
        title.grid(row=0, column=0, sticky="w")
        mode_text = "실제 하드웨어 모드" if self.hardware_mode else "안전한 시뮬레이션 모드"
        ttk.Label(outer, text=mode_text).grid(row=0, column=1, sticky="e")

        controls = ttk.Frame(outer)
        controls.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(12, 0))
        preview = ttk.LabelFrame(outer, text="기구학 미리보기", padding=10)
        preview.grid(row=1, column=1, sticky="nsew", pady=(12, 0))

        distance = ttk.LabelFrame(controls, text="거리 유지", padding=12)
        distance.pack(fill="x", pady=(0, 10))
        self._make_scale(
            distance,
            "사용자 얼굴–베이스 추정 거리",
            self.face_base_cm,
            55.0,
            90.0,
            "cm",
            self._refresh_target,
        )
        self._make_scale(
            distance,
            "목표 사용자–모니터 거리",
            self.target_distance_cm,
            35.0,
            70.0,
            "cm",
            self._refresh_target,
        )
        ttk.Label(
            distance,
            text=(
                f"고정 높이: {self.geometry.fixed_height * 100:.1f}cm "
                "(URDF 중립 gripper 모터 축 높이)"
            ),
        ).pack(anchor="w")
        ttk.Label(distance, textvariable=self.target_text).pack(anchor="w", pady=(4, 0))

        modes = ttk.Frame(distance)
        modes.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(modes, text="ID 1·2 자동 IK", variable=self.auto_ik, command=self._mode_changed).pack(side="left")
        ttk.Checkbutton(
            modes,
            text="ID 4 자세 유지(짐벌)",
            variable=self.gimbal_lock,
            command=self._mode_changed,
        ).pack(side="left", padx=18)

        offset_row = ttk.Frame(distance)
        offset_row.pack(fill="x", pady=(6, 0))
        ttk.Label(offset_row, text="짐벌 pitch 오프셋").pack(side="left")
        ttk.Spinbox(
            offset_row,
            from_=-20.0,
            to=20.0,
            increment=0.5,
            width=8,
            textvariable=self.pitch_offset_deg,
            command=self._refresh_target,
        ).pack(side="left", padx=8)
        ttk.Label(offset_row, text="°").pack(side="left")

        calibration_frame = ttk.LabelFrame(
            controls,
            text="조립 영점 캘리브레이션",
            padding=12,
        )
        calibration_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(
            calibration_frame,
            text=(
                "모니터를 제거하거나 확실히 지지한 뒤, 상부 링크는 수직·하부 링크는 "
                "수평인 정확한 ㄱ자로 맞춥니다. 방향 반전은 캘리브레이션 전에 선택하세요."
            ),
            wraplength=610,
        ).pack(anchor="w")
        directions = ttk.Frame(calibration_frame)
        directions.pack(fill="x", pady=6)
        for name, joint in JOINTS.items():
            ttk.Checkbutton(
                directions,
                text=f"ID {joint.servo_id} 방향 반전",
                variable=self.reverse_vars[name],
                command=self._direction_changed,
            ).pack(side="left", padx=(0, 12))

        calibration_actions = ttk.Frame(calibration_frame)
        calibration_actions.pack(fill="x")
        ttk.Button(
            calibration_actions,
            text="1. 캘리브레이션 시작(토크 해제)",
            command=self._start_calibration,
        ).pack(side="left")
        ttk.Button(
            calibration_actions,
            text="2. 현재 ㄱ자 자세 저장",
            command=self._save_l_pose_calibration,
        ).pack(side="left", padx=8)
        ttk.Label(
            calibration_frame,
            textvariable=self.calibration_status,
        ).pack(anchor="w", pady=(6, 0))

        joints_frame = ttk.LabelFrame(controls, text="모터별 조인트 제어", padding=12)
        joints_frame.pack(fill="x", pady=(0, 10))
        for name, joint in JOINTS.items():
            row = ttk.Frame(joints_frame)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=f"ID {joint.servo_id}  {name}", width=25).pack(side="left")
            scale = ttk.Scale(
                row,
                from_=math.degrees(joint.minimum),
                to=math.degrees(joint.maximum),
                variable=self.joint_vars[name],
                command=lambda _value, n=name: self._manual_joint_changed(n),
            )
            scale.pack(side="left", fill="x", expand=True, padx=8)
            value = ttk.Label(row, width=17, anchor="e")
            value.pack(side="right")
            self.joint_scales[name] = scale
            self.joint_value_labels[name] = value

        actions = ttk.LabelFrame(controls, text="통신 및 실행", padding=12)
        actions.pack(fill="x")
        ttk.Button(actions, text="연결", command=self._connect).pack(side="left")
        ttk.Button(actions, text="현재 목표 명령 전송", command=self._send).pack(side="left", padx=8)
        ttk.Button(actions, text="현재 위치 유지", command=self._hold_position).pack(side="left")
        ttk.Label(actions, textvariable=self.status).pack(side="left", padx=16)

        self.canvas = tk.Canvas(preview, width=360, height=470, background="#161a20", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        ttk.Label(
            preview,
            text=(
                "파란 점: shoulder · 회색 점: wrist_flex · 주황 점: gripper 모터 축\n"
                "URDF 전체 축간 오프셋을 포함하며 충돌 검사는 포함하지 않습니다."
            ),
            justify="center",
        ).pack(pady=(8, 0))

    def _make_scale(self, parent, label, variable, minimum, maximum, unit, callback) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=28).pack(side="left")
        value_label = ttk.Label(row, width=9, anchor="e")
        value_label.pack(side="right")

        def changed(_value=None):
            value_label.configure(text=f"{variable.get():.1f}{unit}")
            callback()

        ttk.Scale(row, from_=minimum, to=maximum, variable=variable, command=changed).pack(
            side="left", fill="x", expand=True, padx=8
        )
        value_label.configure(text=f"{variable.get():.1f}{unit}")

    def _direction_changed(self) -> None:
        for name in JOINTS:
            self.calibrations.values[name].direction = (
                -1 if self.reverse_vars[name].get() else 1
            )
        self.calibration_status.set(
            "방향 설정 변경됨 · 정확한 ㄱ자 자세에서 다시 저장하세요."
        )
        self._refresh_labels()

    def _start_calibration(self) -> None:
        if not self.hardware_mode:
            messagebox.showinfo(
                "실제 하드웨어 필요",
                "조립 영점 캘리브레이션은 --hardware 모드에서만 저장할 수 있습니다.",
            )
            return
        if not self.bus.connected:
            messagebox.showwarning("연결 필요", "먼저 모터 버스를 연결하세요.")
            return
        if self.hardware_mode:
            answer = messagebox.askokcancel(
                "토크 해제 확인",
                "모니터를 제거했거나 팔 전체를 확실히 지지했습니까?\n"
                "확인을 누르면 ID 1~4의 토크가 해제되어 팔이 떨어질 수 있습니다.",
            )
            if not answer:
                return
        try:
            self.bus.set_torque(False)
            self.calibration_torque_released = True
            self.calibration_status.set(
                "토크 해제됨 · 상부 링크 수직/하부 링크 수평의 ㄱ자로 맞춘 뒤 2번을 누르세요."
            )
        except Exception as exc:
            self.calibration_status.set("토크 해제 실패")
            messagebox.showerror("캘리브레이션 시작 실패", str(exc))

    def _save_l_pose_calibration(self) -> None:
        if not self.hardware_mode:
            messagebox.showinfo(
                "실제 하드웨어 필요",
                "조립 영점 캘리브레이션은 --hardware 모드에서만 저장할 수 있습니다.",
            )
            return
        if not self.bus.connected:
            messagebox.showwarning("연결 필요", "먼저 모터 버스를 연결하세요.")
            return
        if self.hardware_mode and not self.calibration_torque_released:
            messagebox.showwarning(
                "순서 확인",
                "먼저 '캘리브레이션 시작(토크 해제)'을 눌러 안전하게 자세를 맞추세요.",
            )
            return

        try:
            raw_ticks = self.bus.read_positions()
            known_angles = self.kinematics.l_pose_angles()
            self.calibrations.calibrate_from_pose(raw_ticks, known_angles)
            self.calibrations.save()

            # Store the present pose as the goal before restoring torque.
            self.bus.hold()
            self.bus.set_torque(True)
            self.calibration_torque_released = False

            self.current_angles.update(known_angles)
            for name, angle in known_angles.items():
                self.joint_vars[name].set(math.degrees(angle))
            zeros = ", ".join(
                f"ID {JOINTS[name].servo_id}={value.zero_tick}"
                for name, value in self.calibrations.values.items()
            )
            self.calibration_status.set(f"ㄱ자 영점 저장 완료 · {zeros}")
            self._refresh_target()
            self.status.set("캘리브레이션 완료 · 현재 자세 토크 유지")
        except Exception as exc:
            self.calibration_status.set(
                "저장 실패 · 안전을 위해 현재 토크 상태를 직접 확인하세요."
            )
            messagebox.showerror("캘리브레이션 저장 실패", str(exc))

    def _mode_changed(self) -> None:
        self._refresh_target()

    def _manual_joint_changed(self, name: str) -> None:
        if not self.auto_ik.get() or name in ("wrist_roll", "wrist_flex"):
            self.current_angles[name] = math.radians(self.joint_vars[name].get())
        self._refresh_target()

    def _refresh_target(self) -> None:
        target_x = (self.face_base_cm.get() - self.target_distance_cm.get()) / 100.0
        target_z = self.geometry.fixed_height
        self.valid_target = True

        try:
            wrist_roll = math.radians(self.joint_vars["wrist_roll"].get())
            pitch_offset = math.radians(self.pitch_offset_deg.get())
            self.current_angles["wrist_roll"] = wrist_roll
            if self.auto_ik.get():
                solved = self.kinematics.solve(
                    target_x,
                    target_z,
                    monitor_pitch=pitch_offset,
                    wrist_roll=wrist_roll,
                )
                self.current_angles.update(solved)
                self.joint_vars["shoulder_lift"].set(math.degrees(solved["shoulder_lift"]))
                self.joint_vars["elbow_flex"].set(math.degrees(solved["elbow_flex"]))
            else:
                self.current_angles["shoulder_lift"] = math.radians(self.joint_vars["shoulder_lift"].get())
                self.current_angles["elbow_flex"] = math.radians(self.joint_vars["elbow_flex"].get())

            if self.gimbal_lock.get():
                wrist = self.kinematics.gimbal_wrist_flex(
                    self.current_angles["shoulder_lift"],
                    self.current_angles["elbow_flex"],
                    pitch_offset,
                )
                self.current_angles["wrist_flex"] = wrist
                self.joint_vars["wrist_flex"].set(math.degrees(wrist))
            else:
                self.current_angles["wrist_flex"] = math.radians(self.joint_vars["wrist_flex"].get())

            actual_x, actual_z = self.kinematics.forward_motor(
                self.current_angles["shoulder_lift"],
                self.current_angles["elbow_flex"],
                self.current_angles["wrist_flex"],
                self.current_angles["wrist_roll"],
            )
            self.target_text.set(
                f"gripper 모터 축 목표 X={target_x * 100:.1f}cm, Z={target_z * 100:.1f}cm  |  "
                f"전체 체인 계산 X={actual_x * 100:.1f}cm, Z={actual_z * 100:.1f}cm"
            )
            self.status.set("목표 계산 완료")
        except KinematicsError as exc:
            self.valid_target = False
            self.target_text.set(str(exc))
            self.status.set("전송 불가: 목표/관절 제한 확인")

        self._update_scale_states()
        self._refresh_labels()
        self._draw_arm()

    def _update_scale_states(self) -> None:
        auto_state = "disabled" if self.auto_ik.get() else "normal"
        self.joint_scales["shoulder_lift"].configure(state=auto_state)
        self.joint_scales["elbow_flex"].configure(state=auto_state)
        self.joint_scales["wrist_roll"].configure(state="normal")
        self.joint_scales["wrist_flex"].configure(
            state="disabled" if self.gimbal_lock.get() else "normal"
        )

    def _refresh_labels(self) -> None:
        for name, joint in JOINTS.items():
            angle = self.current_angles[name]
            tick = radians_to_tick(
                angle,
                joint,
                self.calibrations.values[name],
            )
            self.joint_value_labels[name].configure(text=f"{math.degrees(angle):6.1f}° / {tick:4d}")

    def _connect(self) -> None:
        try:
            message = self.bus.connect()
            self.status.set(message)
        except Exception as exc:
            self.status.set("연결 실패")
            messagebox.showerror("연결 실패", str(exc))

    def _send(self) -> None:
        if not self.valid_target:
            messagebox.showwarning("전송 불가", "현재 목표가 가동범위 또는 관절 제한을 벗어났습니다.")
            return
        if self.hardware_mode:
            answer = messagebox.askokcancel(
                "실제 모터 구동 확인",
                "모니터를 지지하고 주변 충돌물이 없는지 확인했습니다.\n현재 4축 목표를 전송할까요?",
            )
            if not answer:
                return
        try:
            ticks = self.bus.send(self.current_angles)
            text = ", ".join(f"ID {JOINTS[name].servo_id}={tick}" for name, tick in ticks.items())
            self.status.set(f"명령 전송 완료 · {text}")
        except Exception as exc:
            self.status.set("명령 전송 실패")
            messagebox.showerror("명령 전송 실패", str(exc))

    def _hold_position(self) -> None:
        # Torque is intentionally retained because releasing a loaded arm can drop the monitor.
        try:
            self.bus.hold()
            self.status.set("현재 위치 유지 명령 전송됨 (모터 토크 유지)")
        except Exception as exc:
            self.status.set("현재 위치 유지 실패")
            messagebox.showerror("현재 위치 유지 실패", str(exc))

    def _draw_arm(self) -> None:
        c = self.canvas
        c.delete("all")
        width = max(c.winfo_width(), 360)
        height = max(c.winfo_height(), 470)
        scale = min(width / 0.52, height / 0.42)
        origin_x = 20
        origin_y = height - 35

        def point(x: float, z: float) -> tuple[float, float]:
            return origin_x + x * scale, origin_y - z * scale

        g = self.geometry
        shoulder = point(g.shoulder_x, g.shoulder_z)
        q1 = self.current_angles["shoulder_lift"]
        q2 = self.current_angles["elbow_flex"]
        upper_angle = g.upper_zero_angle - q1
        elbow_x = g.shoulder_x + g.upper_arm_length * math.cos(upper_angle)
        elbow_z = g.shoulder_z + g.upper_arm_length * math.sin(upper_angle)
        elbow = point(elbow_x, elbow_z)
        wrist_x, wrist_z = self.kinematics.forward_wrist(q1, q2)
        wrist = point(wrist_x, wrist_z)
        motor_x, motor_z = self.kinematics.forward_motor(
            q1,
            q2,
            self.current_angles["wrist_flex"],
            self.current_angles["wrist_roll"],
        )
        motor = point(motor_x, motor_z)

        c.create_line(0, origin_y, width, origin_y, fill="#5b6573", width=2)
        c.create_line(*shoulder, *elbow, fill="#f0c84b", width=9)
        c.create_line(*elbow, *wrist, fill="#f0c84b", width=9)
        c.create_line(*wrist, *motor, fill="#aab3bf", width=7)
        c.create_oval(
            shoulder[0] - 7, shoulder[1] - 7,
            shoulder[0] + 7, shoulder[1] + 7,
            fill="#4aa3ff", outline="",
        )
        c.create_oval(
            elbow[0] - 7, elbow[1] - 7,
            elbow[0] + 7, elbow[1] + 7,
            fill="#f0c84b", outline="",
        )
        c.create_oval(
            wrist[0] - 6, wrist[1] - 6,
            wrist[0] + 6, wrist[1] + 6,
            fill="#aab3bf", outline="",
        )
        c.create_oval(
            motor[0] - 8, motor[1] - 8,
            motor[0] + 8, motor[1] + 8,
            fill="#ff8a47", outline="",
        )
        fixed_height_y = point(0, g.fixed_height)[1]
        c.create_line(
            0, fixed_height_y, width, fixed_height_y,
            fill="#3f8f68", dash=(5, 5),
        )
        c.create_text(
            8, fixed_height_y - 8,
            text=f"고정 높이 {g.fixed_height * 100:.1f}cm",
            fill="#7bdba7", anchor="w",
        )
        c.create_text(
            motor[0] + 8, motor[1] - 12,
            text=f"motor X {motor_x * 100:.1f} / Z {motor_z * 100:.1f}cm",
            fill="white", anchor="w",
        )

    def _on_close(self) -> None:
        if self.calibration_torque_released and self.bus.connected:
            restore = messagebox.askyesno(
                "토크 해제 상태",
                "캘리브레이션 토크가 해제되어 있습니다. 현재 위치를 목표로 저장하고 "
                "토크를 다시 활성화한 뒤 종료할까요?",
            )
            if restore:
                try:
                    self.bus.hold()
                    self.bus.set_torque(True)
                    self.calibration_torque_released = False
                except Exception as exc:
                    messagebox.showerror("토크 복귀 실패", str(exc))
                    return
        self.bus.close()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SO-101 four-axis monitor-arm UI")
    parser.add_argument("--hardware", action="store_true", help="enable the real Feetech motor bus")
    parser.add_argument("--port", default=os.environ.get("POCO_SERVO_PORT", "/dev/ttyACM0"))
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--speed", type=int, default=800, help="STS3215 position command speed")
    parser.add_argument("--acceleration", type=int, default=30, help="STS3215 acceleration (0-254)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    calibrations = CalibrationStore()
    calibrations.load()
    bus: ServoBus
    if args.hardware:
        bus = FeetechBus(
            args.port,
            calibrations,
            args.baudrate,
            args.speed,
            args.acceleration,
        )
    else:
        bus = SimulationBus(calibrations)
    root = tk.Tk()
    MonitorArmUI(root, bus, calibrations, args.hardware)
    root.mainloop()


if __name__ == "__main__":
    main()
