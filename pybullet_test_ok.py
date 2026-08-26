import pybullet as p
import pybullet_data
import time
import os
import math

def main():
    # 1. PyBullet 물리 시뮬레이터 연결 (GUI 모드)
    physicsClient = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)
    
    p.resetDebugVisualizerCamera(
        cameraDistance=1.2, 
        cameraYaw=50,
        cameraPitch=-30, 
        cameraTargetPosition=[0, 0, 0.3]
    )

    planeId = p.loadURDF("plane.urdf")

    # 2. 사용자 더미 초기 위치 (50cm 유지를 위해 0.75m 정도에서 시작)
    user_pos = [0.75, 0.0, 0.3]  
    user_visual = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.15, 0.15, 0.3], rgbaColor=[0.2, 0.6, 1.0, 1])
    user_collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.15, 0.15, 0.3])
    user_body = p.createMultiBody(
        baseMass=0,  
        baseCollisionShapeIndex=user_collision,
        baseVisualShapeIndex=user_visual,
        basePosition=user_pos
    )

    urdf_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "SO-ARM100-main/Simulation/SO101/so101_monitor_attached.urdf",
    )
    if not os.path.exists(urdf_path):
        print(f"경고: {urdf_path} 경로에 URDF 파일이 없습니다.")
    
    robot_id = p.loadURDF(urdf_path, [0, 0, 0], p.getQuaternionFromEuler([0, 0, 0]), useFixedBase=True)

    num_joints = p.getNumJoints(robot_id)
    end_effector_link_idx = -1
    shoulder_lift_idx = -1
    elbow_flex_idx = -1
    
    for i in range(num_joints):
        info = p.getJointInfo(robot_id, i)
        joint_name = info[1].decode('utf-8')
        if joint_name == "shoulder_lift":
            shoulder_lift_idx = i
        elif joint_name == "elbow_flex":
            elbow_flex_idx = i
        end_effector_link_idx = i

    marker_visual = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.02, 0.02, 0.02], rgbaColor=[1.0, 0.0, 0.0, 1.0])
    marker_body = p.createMultiBody(baseMass=0, baseVisualShapeIndex=marker_visual, basePosition=[0, 0, 0])

    p.stepSimulation()
    initial_link_state = p.getLinkState(robot_id, end_effector_link_idx)
    FIXED_EE_Y = initial_link_state[4][1]
    
    # 50cm 거리에서 팔이 꺾이지 않도록 안정적인 고정 높이 지정
    FIXED_EE_Z = 0.25  

    laser_line_id = -1
    TARGET_DISTANCE = 0.5  # 유지할 목표 거리 (50cm)

    print("\n[실행 중] F, H 키로 사용자를 앞뒤로 움직여 보세요.")

    while p.isConnected():
        keys = p.getKeyboardEvents()
        step_size = 0.015
        
        # 키보드 입력으로 사용자 이동
        if ord('f') in keys and keys[ord('f')] & p.KEY_IS_DOWN:
            user_pos[0] -= step_size
        if ord('h') in keys and keys[ord('h')] & p.KEY_IS_DOWN:
            user_pos[0] += step_size
        if ord('t') in keys and keys[ord('t')] & p.KEY_IS_DOWN:
            user_pos[1] += step_size
        if ord('g') in keys and keys[ord('g')] & p.KEY_IS_DOWN:
            user_pos[1] -= step_size
            
        p.resetBasePositionAndOrientation(user_body, user_pos, [0, 0, 0, 1])

        # 현재 사용자 위치 가져오기
        curr_user_pos, _ = p.getBasePositionAndOrientation(user_body)

        # [핵심 수정] 사용자의 X 위치에서 정확히 0.5m를 뺀 위치를 IK 타겟으로 설정
        # 로봇이 도달할 수 있는 안전 범위 내로 제한하여 튀는 현상 방지
        desired_ee_x = curr_user_pos[0] - TARGET_DISTANCE
        desired_ee_x = max(0.15, min(desired_ee_x, 0.55)) # 로봇 팔 길이에 맞는 가동 범위 제한
        
        desired_ee_y = FIXED_EE_Y  
        desired_ee_z = FIXED_EE_Z  
        
        target_position_ik = [desired_ee_x, desired_ee_y, desired_ee_z]

        # 역기구학 계산
        calculated_ik_joints = p.calculateInverseKinematics(
            bodyUniqueId=robot_id,
            endEffectorLinkIndex=end_effector_link_idx,
            targetPosition=target_position_ik,
            maxNumIterations=100
        )

        # 모터 제어 적용
        if shoulder_lift_idx != -1 and shoulder_lift_idx < len(calculated_ik_joints):
            p.setJointMotorControl2(robot_id, shoulder_lift_idx, p.POSITION_CONTROL, 
                                    targetPosition=calculated_ik_joints[shoulder_lift_idx], force=200)

        if elbow_flex_idx != -1 and elbow_flex_idx < len(calculated_ik_joints):
            p.setJointMotorControl2(robot_id, elbow_flex_idx, p.POSITION_CONTROL, 
                                    targetPosition=calculated_ik_joints[elbow_flex_idx], force=200)
        
        p.stepSimulation()

        # 상태 업데이트 및 화면 표시
        link_state = p.getLinkState(robot_id, end_effector_link_idx)
        updated_ee_pos = link_state[4]
        p.resetBasePositionAndOrientation(marker_body, updated_ee_pos, link_state[5])

        # 실제 측정된 X 거리 계산
        real_x_dist = abs(curr_user_pos[0] - updated_ee_pos[0])
        distance_3d = math.sqrt(
            (curr_user_pos[0] - updated_ee_pos[0])**2 +
            (curr_user_pos[1] - updated_ee_pos[1])**2 +
            (curr_user_pos[2] - updated_ee_pos[2])**2
        )

        p.addUserDebugText(
            f"Real X-Dist: {real_x_dist:.2f}m | 3D-Dist: {distance_3d:.2f}m (Target: {TARGET_DISTANCE}m)", 
            [0, 0, 0.8], 
            textColorRGB=[1, 1, 0], 
            textSize=1.2, 
            replaceItemUniqueId=1
        )

        ray_target = [curr_user_pos[0], curr_user_pos[1], updated_ee_pos[2]]
        ray_results = p.rayTest(updated_ee_pos, ray_target)
        hit_position = ray_results[0][3] if ray_results[0][0] != -1 else ray_target

        laser_line_id = p.addUserDebugLine(
            updated_ee_pos, hit_position, 
            lineColorRGB=[1, 0, 0], lineWidth=2, replaceItemUniqueId=laser_line_id
        )

        time.sleep(1.0 / 240.0)

if __name__ == "__main__":
    main()
