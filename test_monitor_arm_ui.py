import math
from pathlib import Path
import tempfile
import unittest

from monitor_arm_ui import (
    ArmGeometry,
    CalibrationStore,
    JOINTS,
    KinematicsError,
    PlanarMonitorArm,
    SimulationBus,
    ServoCalibration,
    radians_to_tick,
)


class PlanarMonitorArmTests(unittest.TestCase):
    def setUp(self):
        self.arm = PlanarMonitorArm()

    def test_default_distance_target_matches_fixed_height(self):
        solution = self.arm.solve(target_x=0.25, target_z=ArmGeometry().fixed_height)
        wrist_flex = self.arm.gimbal_wrist_flex(
            solution["shoulder_lift"], solution["elbow_flex"]
        )
        x, z = self.arm.forward_motor(
            solution["shoulder_lift"],
            solution["elbow_flex"],
            wrist_flex,
            0.0,
        )
        self.assertAlmostEqual(x, 0.25, places=7)
        self.assertAlmostEqual(z, ArmGeometry().fixed_height, places=7)

    def test_multiple_reachable_targets_round_trip(self):
        for target_x in (0.23, 0.25, 0.28, 0.32, 0.37):
            with self.subTest(target_x=target_x):
                solution = self.arm.solve(target_x, ArmGeometry().fixed_height)
                wrist_flex = self.arm.gimbal_wrist_flex(
                    solution["shoulder_lift"], solution["elbow_flex"]
                )
                x, z = self.arm.forward_motor(
                    solution["shoulder_lift"],
                    solution["elbow_flex"],
                    wrist_flex,
                    0.0,
                )
                self.assertAlmostEqual(x, target_x, places=7)
                self.assertAlmostEqual(z, ArmGeometry().fixed_height, places=7)

    def test_unreachable_target_is_rejected(self):
        with self.assertRaises(KinematicsError):
            self.arm.solve(0.50, ArmGeometry().fixed_height)

    def test_gimbal_cancels_planar_arm_pitch(self):
        shoulder = math.radians(12.0)
        elbow = math.radians(-20.0)
        wrist = self.arm.gimbal_wrist_flex(shoulder, elbow)
        self.assertAlmostEqual(shoulder + elbow + wrist, 0.0)

    def test_angle_to_tick_uses_new_calibration_center(self):
        joint = JOINTS["shoulder_lift"]
        self.assertEqual(radians_to_tick(0.0, joint), 2048)
        self.assertEqual(radians_to_tick(math.pi / 2.0, joint), 3072)

    def test_full_chain_includes_gripper_motor_axis_offset(self):
        x, z = self.arm.tool_offset(0.0, 0.0)
        self.assertAlmostEqual(x, 0.0845, places=7)
        self.assertAlmostEqual(z, 0.021091, places=7)

    def test_roll_and_pitch_tool_offset_round_trip(self):
        pitch = math.radians(8.0)
        roll = math.radians(20.0)
        target_x = 0.30
        target_z = ArmGeometry().fixed_height
        solution = self.arm.solve(target_x, target_z, pitch, roll)
        wrist_flex = self.arm.gimbal_wrist_flex(
            solution["shoulder_lift"],
            solution["elbow_flex"],
            pitch,
        )
        x, z = self.arm.forward_motor(
            solution["shoulder_lift"],
            solution["elbow_flex"],
            wrist_flex,
            roll,
        )
        self.assertAlmostEqual(x, target_x, places=7)
        self.assertAlmostEqual(z, target_z, places=7)

    def test_printed_frame_l_pose_is_new_calibration_zero(self):
        pose = self.arm.l_pose_angles()
        self.assertTrue(all(angle == 0.0 for angle in pose.values()))

    def test_l_pose_calibration_recovers_assembly_zero_ticks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CalibrationStore(Path(directory) / "calibration.json")
            store.values["elbow_flex"].direction = -1
            known = self.arm.l_pose_angles()
            expected_zeros = {
                "shoulder_lift": 1900,
                "elbow_flex": 2150,
                "wrist_roll": 2000,
                "wrist_flex": 2075,
            }
            raw = {
                name: radians_to_tick(
                    known[name],
                    JOINTS[name],
                    ServoCalibration(
                        expected_zeros[name],
                        store.values[name].direction,
                    ),
                )
                for name in JOINTS
            }
            store.calibrate_from_pose(raw, known)
            for name, expected in expected_zeros.items():
                self.assertLessEqual(abs(store.values[name].zero_tick - expected), 1)
            store.save()
            loaded = CalibrationStore(store.path)
            self.assertTrue(loaded.load())
            self.assertEqual(loaded.values["elbow_flex"].direction, -1)

    def test_simulation_bus_holds_last_command(self):
        store = CalibrationStore(Path("unused-test-calibration.json"))
        bus = SimulationBus(store)
        bus.connect()
        angles = {name: 0.0 for name in JOINTS}
        sent = bus.send(angles)
        self.assertEqual(bus.hold(), sent)


if __name__ == "__main__":
    unittest.main()
