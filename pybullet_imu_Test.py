import pybullet as p
import pybullet_data
import time
import os
import math
import random


# ==========================
# 기본 설정
# ==========================
DT = 1.0 / 240.0
TARGET_DISTANCE = 0.50


# ==========================
# IMU 설정
# ==========================
ORIENTATION_DEADBAND_DEG = 0.5
IMU_ALPHA = 0.15

# Gaussian Noise 표준편차
# 0.4도 기준으로 X, Y 각각 독립적인 노이즈 발생
IMU_NOISE_STD_DEG = 0.4


# ==========================
# PID 설정
# ==========================
PITCH_KP = 10.0
PITCH_KI = 0.0
PITCH_KD = 0.0

ROLL_KP = 2.8
ROLL_KI = 0.08
ROLL_KD = 0.18

PID_OUTPUT_LIMIT = 100.0
PID_INTEGRAL_LIMIT = 0.35
DERIVATIVE_FILTER_ALPHA = 0.15


# ==========================
# 관절 설정
# ==========================
MAX_JOINT_SPEED = 100.2
MAX_JOINT_ACCEL = 150.0
WRIST_FORCE = 80
WRIST_MAX_VELOCITY = 100.5
IK_FORCE = 200


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def low_pass_filter(current, previous, alpha):
    return alpha * current + (1.0 - alpha) * previous


def relative_orientation(reference_quat, current_quat):
    _, inv_reference = p.invertTransform([0, 0, 0], reference_quat)
    _, relative_quat = p.multiplyTransforms(
        [0, 0, 0], inv_reference,
        [0, 0, 0], current_quat
    )

    roll, pitch, yaw = p.getEulerFromQuaternion(relative_quat)

    return (
        normalize_angle(roll),
        normalize_angle(pitch),
        normalize_angle(yaw)
    )


class PIDController:
    def __init__(self, kp, ki, kd, output_limit, integral_limit,
                 deadband_deg=0.5, derivative_alpha=0.15):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limit = abs(output_limit)
        self.integral_limit = abs(integral_limit)
        self.deadband = math.radians(deadband_deg)
        self.derivative_alpha = derivative_alpha
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.previous_error = None
        self.filtered_derivative = 0.0

    def update(self, error, dt):
        if dt <= 0.0:
            return 0.0

        # ==========================
        # Dead Band
        # ==========================
        if abs(error) <= self.deadband:
            self.integral = 0.0
            self.previous_error = error
            self.filtered_derivative = 0.0
            return 0.0

        # ==========================
        # D
        # ==========================
        if self.previous_error is None:
            derivative = 0.0
        else:
            derivative = (error - self.previous_error) / dt

        self.filtered_derivative = (
            self.derivative_alpha * derivative
            + (1.0 - self.derivative_alpha) * self.filtered_derivative
        )

        # ==========================
        # I
        # ==========================
        integral_candidate = self.integral + error * dt
        integral_candidate = clamp(
            integral_candidate,
            -self.integral_limit,
            self.integral_limit
        )

        unsaturated_output = (
            self.kp * error
            + self.ki * integral_candidate
            + self.kd * self.filtered_derivative
        )

        # ==========================
        # Anti Wind-up
        # ==========================
        allow_integral = False

        if abs(unsaturated_output) <= self.output_limit:
            allow_integral = True
        elif unsaturated_output > self.output_limit and error < 0.0:
            allow_integral = True
        elif unsaturated_output < -self.output_limit and error > 0.0:
            allow_integral = True

        if allow_integral:
            self.integral = integral_candidate

        output = (
            self.kp * error
            + self.ki * self.integral
            + self.kd * self.filtered_derivative
        )

        output = clamp(output, -self.output_limit, self.output_limit)
        self.previous_error = error

        return output


class SimulatedIMU:
    def __init__(self, reference_quat, alpha=0.15, noise_std_deg=0.4):
        self.reference_quat = reference_quat
        self.alpha = alpha
        self.noise_std = math.radians(noise_std_deg)
        self.filtered_x = 0.0
        self.filtered_y = 0.0

    def reset_reference(self, reference_quat):
        self.reference_quat = reference_quat
        self.filtered_x = 0.0
        self.filtered_y = 0.0

    def read(self, robot_id, monitor_link_idx):
        state = p.getLinkState(
            robot_id,
            monitor_link_idx,
            computeForwardKinematics=True
        )

        current_quat = state[5]
        roll, pitch, yaw = relative_orientation(
            self.reference_quat,
            current_quat
        )

        # ==========================
        # Gaussian Noise
        # ==========================
        noise_x = random.gauss(0.0, self.noise_std)
        noise_y = random.gauss(0.0, self.noise_std)

        # 실제 IMU 값이라고 가정
        # X -> Pitch, Y -> Roll
        raw_x = pitch + noise_x
        raw_y = roll + noise_y

        # ==========================
        # Low Pass Filter
        # ==========================
        self.filtered_x = low_pass_filter(raw_x, self.filtered_x, self.alpha)
        self.filtered_y = low_pass_filter(raw_y, self.filtered_y, self.alpha)

        return self.filtered_x, self.filtered_y, yaw


def acceleration_limit(target_velocity, previous_velocity, max_accel, dt):
    max_delta = max_accel * dt
    delta = target_velocity - previous_velocity
    delta = clamp(delta, -max_delta, max_delta)

    return previous_velocity + delta


def measure_orientation_jacobian(robot_id, monitor_link_idx,
                                 wrist_flex_idx, wrist_roll_idx,
                                 reference_quat):
    eps = math.radians(2.0)

    original_flex = p.getJointState(robot_id, wrist_flex_idx)[0]
    original_roll = p.getJointState(robot_id, wrist_roll_idx)[0]

    def get_pitch_roll():
        state = p.getLinkState(
            robot_id,
            monitor_link_idx,
            computeForwardKinematics=True
        )

        roll, pitch, _ = relative_orientation(reference_quat, state[5])
        return pitch, roll

    def derivative_for_joint(joint_idx, original_value):
        info = p.getJointInfo(robot_id, joint_idx)
        lower = info[8]
        upper = info[9]

        plus = clamp(original_value + eps, lower, upper)
        minus = clamp(original_value - eps, lower, upper)

        p.resetJointState(robot_id, joint_idx, plus)
        pitch_plus, roll_plus = get_pitch_roll()

        p.resetJointState(robot_id, joint_idx, minus)
        pitch_minus, roll_minus = get_pitch_roll()

        p.resetJointState(robot_id, joint_idx, original_value)

        dq = plus - minus

        if abs(dq) < 1e-8:
            return 0.0, 0.0

        dpitch = normalize_angle(pitch_plus - pitch_minus)
        droll = normalize_angle(roll_plus - roll_minus)

        return dpitch / dq, droll / dq

    pitch_flex, roll_flex = derivative_for_joint(
        wrist_flex_idx,
        original_flex
    )

    pitch_roll, roll_roll = derivative_for_joint(
        wrist_roll_idx,
        original_roll
    )

    p.resetJointState(robot_id, wrist_flex_idx, original_flex)
    p.resetJointState(robot_id, wrist_roll_idx, original_roll)

    return pitch_flex, pitch_roll, roll_flex, roll_roll


def orientation_rate_to_joint_rate(pitch_rate, roll_rate, jacobian):
    a, b, c, d = jacobian
    determinant = a * d - b * c

    if abs(determinant) > 0.05:
        flex_velocity = (d * pitch_rate - b * roll_rate) / determinant
        roll_velocity = (-c * pitch_rate + a * roll_rate) / determinant
        return flex_velocity, roll_velocity

    flex_velocity = 0.0
    roll_velocity = 0.0

    if abs(a) > 0.1:
        flex_velocity = pitch_rate / a

    if abs(d) > 0.1:
        roll_velocity = roll_rate / d

    return flex_velocity, roll_velocity


def main():
    # ==========================
    # PyBullet
    # ==========================
    physicsClient = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(DT)

    p.resetDebugVisualizerCamera(
        cameraDistance=1.2,
        cameraYaw=50,
        cameraPitch=-30,
        cameraTargetPosition=[0, 0, 0.3]
    )

    p.loadURDF("plane.urdf")

    # ==========================
    # 사용자 더미
    # ==========================
    user_pos = [0.75, 0.0, 0.3]

    user_visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=[0.15, 0.15, 0.3],
        rgbaColor=[0.2, 0.6, 1.0, 1.0]
    )

    user_collision = p.createCollisionShape(
        p.GEOM_BOX,
        halfExtents=[0.15, 0.15, 0.3]
    )

    user_body = p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=user_collision,
        baseVisualShapeIndex=user_visual,
        basePosition=user_pos
    )

    # ==========================
    # Robot
    # ==========================
    urdf_path = "/home/rungmin/VIsion/VisionPoseCoach/SO-ARM100-main/Simulation/SO101/so101_monitor_attached.urdf"

    if not os.path.exists(urdf_path):
        print("ERROR: URDF 파일이 없습니다.")
        print(urdf_path)
        return

    robot_id = p.loadURDF(
        urdf_path,
        [0, 0, 0],
        p.getQuaternionFromEuler([0, 0, 0]),
        useFixedBase=True
    )

    # ==========================
    # Joint 검색
    # ==========================
    num_joints = p.getNumJoints(robot_id)
    joint_name_to_idx = {}
    movable_joint_indices = []
    ik_joint_map = {}
    monitor_link_idx = -1

    print("\n========== Joint List ==========")

    for i in range(num_joints):
        info = p.getJointInfo(robot_id, i)
        joint_name = info[1].decode("utf-8")
        q_index = info[3]
        link_name = info[12].decode("utf-8")

        joint_name_to_idx[joint_name] = i
        print(f"Joint {i:2d} | {joint_name:20s} | Link: {link_name}")

        if q_index >= 0:
            ik_joint_map[i] = len(movable_joint_indices)
            movable_joint_indices.append(i)

        if link_name == "monitor_link":
            monitor_link_idx = i

    print("================================\n")

    shoulder_lift_idx = joint_name_to_idx.get("shoulder_lift", -1)
    elbow_flex_idx = joint_name_to_idx.get("elbow_flex", -1)
    wrist_flex_idx = joint_name_to_idx.get("wrist_flex", -1)
    wrist_roll_idx = joint_name_to_idx.get("wrist_roll", -1)

    required = {
        "shoulder_lift": shoulder_lift_idx,
        "elbow_flex": elbow_flex_idx,
        "wrist_flex": wrist_flex_idx,
        "wrist_roll": wrist_roll_idx,
        "monitor_link": monitor_link_idx
    }

    for name, idx in required.items():
        if idx == -1:
            print(f"ERROR: {name} 없음")
            return

    # ==========================
    # 초기 자세
    # ==========================
    p.stepSimulation()

    initial_monitor_state = p.getLinkState(
        robot_id,
        monitor_link_idx,
        computeForwardKinematics=True
    )

    initial_monitor_position = initial_monitor_state[4]
    initial_monitor_orientation = initial_monitor_state[5]

    FIXED_EE_Y = initial_monitor_position[1]
    FIXED_EE_Z = 0.25

    # ==========================
    # IMU / PID
    # ==========================
    imu = SimulatedIMU(
        initial_monitor_orientation,
        alpha=IMU_ALPHA,
        noise_std_deg=IMU_NOISE_STD_DEG
    )

    pitch_pid = PIDController(
        PITCH_KP,
        PITCH_KI,
        PITCH_KD,
        PID_OUTPUT_LIMIT,
        PID_INTEGRAL_LIMIT,
        ORIENTATION_DEADBAND_DEG,
        DERIVATIVE_FILTER_ALPHA
    )

    roll_pid = PIDController(
        ROLL_KP,
        ROLL_KI,
        ROLL_KD,
        PID_OUTPUT_LIMIT,
        PID_INTEGRAL_LIMIT,
        ORIENTATION_DEADBAND_DEG,
        DERIVATIVE_FILTER_ALPHA
    )

    orientation_jacobian = measure_orientation_jacobian(
        robot_id,
        monitor_link_idx,
        wrist_flex_idx,
        wrist_roll_idx,
        initial_monitor_orientation
    )

    a, b, c, d = orientation_jacobian

    print("[Orientation Jacobian]")
    print(f"Pitch <- Flex : {a:+.3f}")
    print(f"Pitch <- Roll : {b:+.3f}")
    print(f"Roll  <- Flex : {c:+.3f}")
    print(f"Roll  <- Roll : {d:+.3f}")
    print(f"IMU Gaussian Noise STD : {IMU_NOISE_STD_DEG:.2f} deg")

    # ==========================
    # Wrist 초기 상태
    # ==========================
    wrist_flex_target = p.getJointState(robot_id, wrist_flex_idx)[0]
    wrist_roll_target = p.getJointState(robot_id, wrist_roll_idx)[0]
    wrist_flex_velocity = 0.0
    wrist_roll_velocity = 0.0

    flex_info = p.getJointInfo(robot_id, wrist_flex_idx)
    roll_info = p.getJointInfo(robot_id, wrist_roll_idx)

    flex_lower = flex_info[8]
    flex_upper = flex_info[9]
    roll_lower = roll_info[8]
    roll_upper = roll_info[9]

    # ==========================
    # Marker
    # ==========================
    marker_visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=[0.02, 0.02, 0.02],
        rgbaColor=[1, 0, 0, 1]
    )

    marker_body = p.createMultiBody(
        baseMass=0,
        baseVisualShapeIndex=marker_visual,
        basePosition=[0, 0, 0]
    )

    laser_line_id = -1
    debug_text_id = -1

    print("\n[실행 중]")
    print("F / H : 사용자 앞뒤")
    print("T / G : 사용자 좌우")
    print("R : 현재 모니터 자세 IMU 0점 재설정\n")

    while p.isConnected():
        keys = p.getKeyboardEvents()
        step_size = 0.015

        # ==========================
        # 사용자 움직임
        # ==========================
        if ord("f") in keys and keys[ord("f")] & p.KEY_IS_DOWN:
            user_pos[0] -= step_size

        if ord("h") in keys and keys[ord("h")] & p.KEY_IS_DOWN:
            user_pos[0] += step_size

        if ord("t") in keys and keys[ord("t")] & p.KEY_IS_DOWN:
            user_pos[1] += step_size

        if ord("g") in keys and keys[ord("g")] & p.KEY_IS_DOWN:
            user_pos[1] -= step_size

        p.resetBasePositionAndOrientation(user_body, user_pos, [0, 0, 0, 1])
        curr_user_pos, _ = p.getBasePositionAndOrientation(user_body)

        # ==========================
        # IMU Calibration
        # ==========================
        if ord("r") in keys and keys[ord("r")] & p.KEY_WAS_TRIGGERED:
            current_state = p.getLinkState(
                robot_id,
                monitor_link_idx,
                computeForwardKinematics=True
            )

            imu.reset_reference(current_state[5])
            pitch_pid.reset()
            roll_pid.reset()
            wrist_flex_velocity = 0.0
            wrist_roll_velocity = 0.0

            print("IMU Calibration 완료")

        # ==========================
        # 위치 제어
        # ==========================
        desired_ee_x = curr_user_pos[0] - TARGET_DISTANCE
        desired_ee_x = clamp(desired_ee_x, 0.15, 0.55)

        target_position_ik = [desired_ee_x, FIXED_EE_Y, FIXED_EE_Z]

        calculated_ik_joints = p.calculateInverseKinematics(
            bodyUniqueId=robot_id,
            endEffectorLinkIndex=monitor_link_idx,
            targetPosition=target_position_ik,
            maxNumIterations=100,
            residualThreshold=0.0001
        )

        if shoulder_lift_idx in ik_joint_map:
            ik_idx = ik_joint_map[shoulder_lift_idx]

            if ik_idx < len(calculated_ik_joints):
                p.setJointMotorControl2(
                    robot_id,
                    shoulder_lift_idx,
                    p.POSITION_CONTROL,
                    targetPosition=calculated_ik_joints[ik_idx],
                    force=IK_FORCE
                )

        if elbow_flex_idx in ik_joint_map:
            ik_idx = ik_joint_map[elbow_flex_idx]

            if ik_idx < len(calculated_ik_joints):
                p.setJointMotorControl2(
                    robot_id,
                    elbow_flex_idx,
                    p.POSITION_CONTROL,
                    targetPosition=calculated_ik_joints[ik_idx],
                    force=IK_FORCE
                )

        # ==========================
        # IMU
        # ==========================
        imu_x, imu_y, imu_yaw = imu.read(robot_id, monitor_link_idx)

        pitch_error = -imu_x
        roll_error = -imu_y

        # ==========================
        # PID
        # ==========================
        pitch_correction_rate = pitch_pid.update(pitch_error, DT)
        roll_correction_rate = roll_pid.update(roll_error, DT)

        desired_flex_velocity, desired_roll_velocity = orientation_rate_to_joint_rate(
            pitch_correction_rate,
            roll_correction_rate,
            orientation_jacobian
        )

        desired_flex_velocity = clamp(
            desired_flex_velocity,
            -MAX_JOINT_SPEED,
            MAX_JOINT_SPEED
        )

        desired_roll_velocity = clamp(
            desired_roll_velocity,
            -MAX_JOINT_SPEED,
            MAX_JOINT_SPEED
        )

        # ==========================
        # 가속도 제한
        # ==========================
        wrist_flex_velocity = acceleration_limit(
            desired_flex_velocity,
            wrist_flex_velocity,
            MAX_JOINT_ACCEL,
            DT
        )

        wrist_roll_velocity = acceleration_limit(
            desired_roll_velocity,
            wrist_roll_velocity,
            MAX_JOINT_ACCEL,
            DT
        )

        # ==========================
        # 속도 -> 목표 각도
        # ==========================
        new_flex_target = wrist_flex_target + wrist_flex_velocity * DT
        new_roll_target = wrist_roll_target + wrist_roll_velocity * DT

        clamped_flex_target = clamp(new_flex_target, flex_lower, flex_upper)
        clamped_roll_target = clamp(new_roll_target, roll_lower, roll_upper)

        if clamped_flex_target != new_flex_target:
            wrist_flex_velocity = 0.0

        if clamped_roll_target != new_roll_target:
            wrist_roll_velocity = 0.0

        wrist_flex_target = clamped_flex_target
        wrist_roll_target = clamped_roll_target

        # ==========================
        # 모터 제어
        # ==========================
        p.setJointMotorControl2(
            robot_id,
            wrist_flex_idx,
            p.POSITION_CONTROL,
            targetPosition=wrist_flex_target,
            force=WRIST_FORCE,
            maxVelocity=WRIST_MAX_VELOCITY
        )

        p.setJointMotorControl2(
            robot_id,
            wrist_roll_idx,
            p.POSITION_CONTROL,
            targetPosition=wrist_roll_target,
            force=WRIST_FORCE,
            maxVelocity=WRIST_MAX_VELOCITY
        )

        p.stepSimulation()

        # ==========================
        # 상태 표시
        # ==========================
        monitor_state = p.getLinkState(
            robot_id,
            monitor_link_idx,
            computeForwardKinematics=True
        )

        updated_ee_pos = monitor_state[4]
        updated_ee_orn = monitor_state[5]

        p.resetBasePositionAndOrientation(
            marker_body,
            updated_ee_pos,
            updated_ee_orn
        )

        real_x_dist = abs(curr_user_pos[0] - updated_ee_pos[0])

        distance_3d = math.sqrt(
            (curr_user_pos[0] - updated_ee_pos[0]) ** 2
            + (curr_user_pos[1] - updated_ee_pos[1]) ** 2
            + (curr_user_pos[2] - updated_ee_pos[2]) ** 2
        )

        debug_text = (
            f"X Dist: {real_x_dist:.3f} m | 3D: {distance_3d:.3f} m\n"
            f"IMU X(Pitch): {math.degrees(imu_x):+.2f} deg | "
            f"IMU Y(Roll): {math.degrees(imu_y):+.2f} deg\n"
            f"Pitch PID: {math.degrees(pitch_correction_rate):+.1f} deg/s | "
            f"Roll PID: {math.degrees(roll_correction_rate):+.1f} deg/s\n"
            f"Wrist Flex: {math.degrees(wrist_flex_target):+.1f} deg | "
            f"Wrist Roll: {math.degrees(wrist_roll_target):+.1f} deg"
        )

        debug_text_id = p.addUserDebugText(
            debug_text,
            [0, 0, 0.8],
            textColorRGB=[1, 1, 0],
            textSize=1.1,
            replaceItemUniqueId=debug_text_id
        )

        ray_target = [curr_user_pos[0], curr_user_pos[1], updated_ee_pos[2]]
        ray_results = p.rayTest(updated_ee_pos, ray_target)
        hit_position = ray_results[0][3] if ray_results[0][0] != -1 else ray_target

        laser_line_id = p.addUserDebugLine(
            updated_ee_pos,
            hit_position,
            lineColorRGB=[1, 0, 0],
            lineWidth=2,
            replaceItemUniqueId=laser_line_id
        )

        time.sleep(DT)

    p.disconnect()


if __name__ == "__main__":
    main()