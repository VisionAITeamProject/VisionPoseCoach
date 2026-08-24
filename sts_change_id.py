#!/usr/bin/env python
import sys
import os

if os.name == 'nt':
    import msvcrt
    def getch():
        return msvcrt.getch().decode()
else:
    import sys, tty, termios
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    def getch():
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

# 1. 절대 경로 지정
sdk_path = os.path.abspath("./STServo_Python/stservo-env/scservo_sdk")
if sdk_path not in sys.path:
    sys.path.append(sdk_path)

# 2. 임포트
from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *

# ================= 설정을 여기서 변경하세요 =================
SCS_ID = 1             # 현재 모터의 ID (기본값 보통 1)
NEW_ID = 3             # 바꾸고 싶은 새로운 ID
BAUDRATE = 1000000     # 통신 속도
DEVICENAME = '/dev/ttyACM0'  # 포트 이름
scs_id = 5
# ==========================================================

# 포트 및 패킷 핸들러 초기화 (여기를 수정했습니다!)
portHandler = PortHandler(DEVICENAME)
packetHandler = sms_sts(portHandler)  # 인자로 portHandler를 그대로 전달

# 포트 열기
if portHandler.openPort():
    print("Succeeded to open the port")
else:
    print("Failed to open the port")
    print("Press any key to terminate...")
    getch()
    quit()

# 보레이트 설정
if portHandler.setBaudRate(BAUDRATE):
    print("Succeeded to set the baudrate")
else:
    print("Failed to set the baudrate")
    portHandler.closePort()
    quit()

# 1. EEPROM 잠금 해제
scs_comm_result, scs_error = packetHandler.unLockEprom(SCS_ID)
if scs_comm_result != COMM_SUCCESS:
    print("Unlock Error:", packetHandler.getTxRxResult(scs_comm_result))
elif scs_error != 0:
    print("Unlock Packet Error:", packetHandler.getRxPacketError(scs_error))
    getch()
    quit()

# 2. 새로운 ID로 쓰기
scs_comm_result, scs_error = packetHandler.write1ByteTxRx(SCS_ID, scs_id, NEW_ID)

if scs_comm_result != COMM_SUCCESS:
    print("Write Error:", packetHandler.getTxRxResult(scs_comm_result))
else:
    # 3. 변경 완료 후 다시 EEPROM 잠그기
    packetHandler.LockEprom(NEW_ID)
    print(f"Succeeded to change the Servo ID from {SCS_ID} to {NEW_ID}!")

if scs_error != 0:
    print("Write Packet Error:", packetHandler.getRxPacketError(scs_error))

portHandler.closePort()