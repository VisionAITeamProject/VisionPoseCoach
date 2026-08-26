#!/usr/bin/env python
import sys
import os

# scservo_sdk 폴더 경로 설정 (사용자 환경에 맞게 경로 확인 필요)
sdk_path = os.path.abspath("./STServo_Python/stservo-env/scservo_sdk") 
sys.path.append(sdk_path)

from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *

# 포트 및 통신 설정
DEVICENAME = '/dev/ttyACM0'  
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

print("=" * 50)
print("STS3215 3번 모터 키보드 수동 제어 프로그램")
print("- 'a' 입력: 반시방향(-)으로 이동")
print("- 'd' 입력: 시계방향(+)으로 이동")
print("- 숫자 직접 입력: 해당 위치(0~4095)로 즉시 이동 (예: 2048)")
print("- 종료하려면 'q' 또는 'quit' 입력")
print("=" * 50)

# 현재 위치를 추적하기 위한 초기값 (모터의 중앙값인 2048로 설정, 필요시 읽어올 수도 있음)
current_pos = 2048
step_size = 100  # a, d를 누를 때마다 움직일 이동량 (조절 가능)

# 시작할 때 중앙 위치로 초기화 이동
packetHandler.WritePosEx(3, current_pos, 2400, 40)
print(f"초기 위치: {current_pos}")

try:
    while True:
        user_input = input(f"\n현재위치[{current_pos}] - 입력 (a:감소, d:증가, 숫자, q:종료): ").strip().lower()
        
        # 종료 조건
        if user_input in ['q', 'quit', 'exit']:
            print("프로그램을 종료합니다.")
            break
            
        # 'a' 입력 시 위치 감소
        if user_input == 'a':
            current_pos -= step_size
            if current_pos < 0:
                current_pos = 0
                print("최소 범위(0)에 도달했습니다.")
                
        # 'd' 입력 시 위치 증가
        elif user_input == 'd':
            current_pos += step_size
            if current_pos > 4095:
                current_pos = 4095
                print("최대 범위(4095)에 도달했습니다.")
                
        else:
            # 숫자를 직접 입력한 경우
            try:
                target_pos = int(user_input)
                if 0 <= target_pos <= 4095:
                    current_pos = target_pos
                else:
                    print("범위 초과! 0에서 4095 사이의 값을 입력해주세요.")
                    continue
            except ValueError:
                print("잘못된 입력입니다. 'a', 'd', 숫자 또는 'q'를 입력해주세요.")
                continue
                
        # 3번 모터로 목표 위치 전송
        result, error = packetHandler.WritePosEx(3, current_pos, 2400, 40)
        
        if result == COMM_SUCCESS:
            print(f"[이동 완료] 3번 모터 -> 위치: {current_pos}")
            if error != 0:
                print(f"[경고] 모터 에러 코드: {error}")
        else:
            print(f"[실패] 통신 에러 코드: {result}")

except KeyboardInterrupt:
    print("\n사용자에 의해 강제 종료되었습니다.")

finally:
    portHandler.closePort()
    print("포트를 닫고 프로그램을 종료합니다.")