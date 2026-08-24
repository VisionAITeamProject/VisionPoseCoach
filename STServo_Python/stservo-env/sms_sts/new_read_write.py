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

# scservo_sdk 폴더가 있는 절대/상대 경로를 직접 시스템 패스에 추가합니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
# 현재 파일이 sms_sts 폴더 안에 있으므로, scservo_sdk 폴더 위치를 정확히 지정
sdk_path = os.path.abspath(os.path.join(current_dir, '..')) 
sys.path.append(sdk_path)

# 직접 파일들을 임포트합니다.
from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *

# Default setting
SCS_ID = 1                 
BAUDRATE = 1000000           
DEVICENAME = '/dev/ttyACM0'    
SCS_MINIMUM_POSITION_VALUE = 0           
SCS_MAXIMUM_POSITION_VALUE = 4095
SCS_MOVING_SPEED = 2400        
SCS_MOVING_ACC = 50          

index = 0
scs_goal_position = [SCS_MINIMUM_POSITION_VALUE, SCS_MAXIMUM_POSITION_VALUE]         

portHandler = PortHandler(DEVICENAME)
packetHandler = sms_sts(portHandler)
    
if portHandler.openPort():
    print("Succeeded to open the port")
else:
    print("Failed to open the port")
    getch()
    quit()

if portHandler.setBaudRate(BAUDRATE):
    print("Succeeded to change the baudrate")
else:
    print("Failed to change the baudrate")
    getch()
    quit()

while 1:
    print("Press any key to continue! (or press ESC to quit!)")
    if getch() == chr(0x1b):
        break

    scs_comm_result, scs_error = packetHandler.WritePosEx(SCS_ID, scs_goal_position[index], SCS_MOVING_SPEED, SCS_MOVING_ACC)
    if scs_comm_result != COMM_SUCCESS:
        print("%s" % packetHandler.getTxRxResult(scs_comm_result))
    elif scs_error != 0:
        print("%s" % packetHandler.getRxPacketError(scs_error))

    while 1:
        scs_present_position, scs_present_speed, scs_comm_result, scs_error = packetHandler.ReadPosSpeed(SCS_ID)
        if scs_comm_result != COMM_SUCCESS:
            print(packetHandler.getTxRxResult(scs_comm_result))
        else:
            print("[ID:%03d] GoalPos:%d PresPos:%d PresSpd:%d" % (SCS_ID, scs_goal_position[index], scs_present_position, scs_present_speed))
        if scs_error != 0:
            print(packetHandler.getRxPacketError(scs_error))

        moving, scs_comm_result, scs_error = packetHandler.ReadMoving(SCS_ID)
        if scs_comm_result != COMM_SUCCESS:
            print(packetHandler.getTxRxResult(scs_comm_result))

        if moving == 0:
            break

    if index == 0:
        index = 1
    else:
        index = 0

portHandler.closePort()