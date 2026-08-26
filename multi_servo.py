#!/usr/bin/env python
import sys
import os
import time

# 1. 경로 설정 및 임포트
sdk_path = os.path.abspath("./STServo_Python/stservo-env/scservo_sdk")
if sdk_path not in sys.path:
    sys.path.append(sdk_path)

from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *

DEVICENAME = '/dev/ttyACM0'
BAUDRATE = 1000000

portHandler = PortHandler(DEVICENAME)
packetHandler = sms_sts(portHandler)

if not portHandler.openPort():
    print("포트 오픈 실패!")
    exit()

if not portHandler.setBaudRate(BAUDRATE):
    print("보레이트 설정 실패!")
    exit()

print("✅ 다중 모터 제어 테스트 시작 (1번 ~ 4번)")

# 제어할 모터 ID 리스트
servo_ids = [1, 2, 3]
target_position = 2048  # 정중앙 위치 (180도)
speed = 2000
acc = 50

# 1번부터 4번 모터를 차례대로 회전
for servo_id in servo_ids:
    print(f"👉 [ID: {servo_id}] 모터를 위치 {target_position}으로 이동 중...")
    
    result, error = packetHandler.WritePosEx(servo_id, target_position, speed, acc)
    
    if result != COMM_SUCCESS:
        print(f"ID {servo_id} 통신 에러: {packetHandler.getTxRxResult(result)}")
    elif error != 0:
        print(f"ID {servo_id} 모터 에러 발생: {packetHandler.getRxPacketError(error)}")
    else:
        print(f"ID {servo_id} 명령 전송 완료!")
    
    # 모터가 움직일 수 있도록 1초씩 대기
    time.sleep(1.0)

print("\n모든 모터 순차 제어 완료!")
portHandler.closePort()