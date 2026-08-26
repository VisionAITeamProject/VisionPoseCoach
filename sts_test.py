#!/usr/bin/env python
import sys
import os

# 만약 2단계에서 pip install을 안 했다면, scservo_sdk 폴더 경로를 직접 잡아줍니다.
# 현재 파일(run_servo.py)이 있는 위치를 기준으로 scservo_sdk 폴더의 정확한 경로를 지정하세요.
sdk_path = os.path.abspath("./STServo_Python/stservo-env/scservo_sdk") # 본인 폴더 구조에 맞게 확인
sys.path.append(sdk_path)

# 이제 에러 없이 바로 임포트됩니다.
from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *

# 포트 및 통신 설정
DEVICENAME = '/dev/ttyACM0'  # 아까 확인한 포트
BAUDRATE = 1000000

portHandler = PortHandler(DEVICENAME)
packetHandler = sms_sts(portHandler)

# 포트 열기
if portHandler.openPort():
    print("Succeeded to open the port")
else:
    print("Failed to open the port")
    exit()

# 통신 속도 설정
if portHandler.setBaudRate(BAUDRATE):
    print("Succeeded to change the baudrate")
else:
    print("Failed to change the baudrate")
    exit()

print("모터 제어 테스트 시작!")

# ID 1번 모터를 2048(중앙) 위치로 이동
# WritePosEx(ID, 목표위치, 속도, 가속도)
result, error = packetHandler.WritePosEx(4, 2048, 2400, 40)

if result == COMM_SUCCESS:
    print("모터 명령 전송 성공!")
else:
    print(f"통신 에러 코드: {result}")

portHandler.closePort()