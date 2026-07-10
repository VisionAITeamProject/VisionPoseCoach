<p align="center">
<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/e77c6f5d0e1ae55fe3329129abc43a7e8f1f03b3/%EC%9E%90%EC%84%B8%EC%BD%94%EC%B9%AD.png" alt="배너" width="100%"/>
</a>

<br/>
<br/>
<br/>


# ✨팀명 : 포코 (POCO)
> 비전 AI 기반 자세 교정 및 일일 리포트 시스템
<br/>

# 1. Project Overview (프로젝트 개요)
VisionPoseCoach는 사용자의 앉은 자세를 실시간으로 분석하고, 비정상적인 자세가 감지되었을 때 즉시 알림을 제공하여 사용자가 올바른 자세로 돌아갈 수 있도록 돕는 자세 코칭 시스템입니다.

또한 하루 동안의 자세 데이터를 리포트로 시각화하여, 사용자가 평소 인식하지 못했던 자세 습관을 확인하고 개선할 수 있도록 지원합니다.

<br/>

## 프로젝트 목표

- 현대인은 장시간 책상에 앉아 작업하거나 공부하는 과정에서 거북목, 어깨 불균형, 허리 굽음 등 다양한 자세 문제를 겪기 쉽습니다.

- 본 프로젝트는 카메라 기반 비전 AI 기술을 활용하여 사용자의 자세 상태를 분석하고, 비정상적인 자세가 지속될 경우 즉각적인 피드백을 제공하는 것을 목표로 합니다.

<br/>

### 핵심 목표

- 사용자의 비정상적인 자세를 실시간으로 감지
- 자세가 흐트러졌을 때 알림을 통해 즉각적인 교정 유도
- 일일 리포트를 통해 사용자의 자세 습관을 시각적으로 제공
- 자세 점수 및 피드백을 통해 지속적인 자세 개선 지원

<br/>
<br/>
<br/>

# 2. Team Members (팀원 및 팀 소개)
| 조병현 | 신동민 | 이종현 | 최은비 |
|:------:|:------:|:------:|:------:|
| <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/4786246569c1237d3ee9a73786d18f3fbdaa8efe/byunghyun.png" alt="조병현" width="150" height="150" > | <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/525a65bd8bcf20387ab53856dfa0d6694551d765/YouYou.jpg" alt="신동민" width="150" height="150"> | <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/main/jhprf.jpeg" alt="이종현" width="150" height="150"> | <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/2cd3711948bca333d3e7c517373cbf9463c5b163/eun.png" alt="최은비" width="150" height="150"> |

<br/>
<br/>
<br/>


# 3. 주요 기능

### 3.1 자세 판단 기능

>**사용자의 신체 랜드마크 데이터를 기반으로 자세 상태를 분석합니다.**
 
- 정상 자세 판단
- 어깨 불균형 감지
- 목 기울어짐 감지
- 자세 불안정 상태 감지
- 사용자별 기준 자세 설정
<br/>

### 3.2 피로도 분석 기능

>**Face Mesh 기반 데이터를 활용하여 사용자의 피로 상태를 보조적으로 분석합니다.**:
  
- 눈 감김 시간 측정
- 하품 여부 판단
- 피로도 관련 Feature 추출
- 자세 데이터와 함께 종합적인 상태 분석
<br/>

### 3.3 실시간 알림 기능

>**비정상적인 자세가 일정 시간 이상 지속될 경우 사용자에게 즉각적인 알림을 제공합니다.**
  
- 부저 알림
- 진동 알림
- 자세 교정 유도 (추후 확장성 고려 후순위)
- 하드웨어 기반 피드백 제공
<br/>

### 3.4 일일 리포트 웹 기능

>**측정된 자세 데이터를 기반으로 하루 단위 리포트를 제공합니다.**
  
- 정상 자세 유지 시간
- 비정상 자세 발생 횟수
- 자세 유형별 통계
- 자세 점수 계산
- 차트 기반 시각화
- 사용자 맞춤 피드백 제공
<br/>


### 3.5 웹캠 수평 보정 기능

>**정확한 자세 판단을 위해 카메라의 기울어짐을 보정하는 기능을 제공합니다.**

- 웹캠 수평 상태 확인
- 기준 자세 설정 보조
- 카메라 각도 오차 최소화
- 자세 판단 정확도 향상

<br/>
<br/>
<br/>

# 4. Tasks & Responsibilities (작업 및 역할 분담)
|  |  |  |
|-----------------|-----------------|-----------------|
| 조병현    |  <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/4786246569c1237d3ee9a73786d18f3fbdaa8efe/byunghyun.png" alt="조병현" width="100"> | <ul><li>Pose 모델 구현 및 튜닝</li><li>자세 데이터 수집</li></ul>     |
| 신동민   |  <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/525a65bd8bcf20387ab53856dfa0d6694551d765/YouYou.jpg" alt="신동민" width="100">| <ul><li>리포트 웹 개발</li><li>데이터 수집</li></ul> |
| 이종현   |  <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/main/jhprf.jpeg" alt="이종현" width="100">    |<ul><li>Face 모델 구현 및 튜닝</li><li>피로도 데이터 수집</li></ul>  |
| 최은비    |  <img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/2cd3711948bca333d3e7c517373cbf9463c5b163/eun.png" alt="최은비" width="100">    | <ul><li>하드웨어 카메라 수평 조절 기능</li><li>하드웨어 부저 및 알림 기능</li><li>데이터 수집</li></ul>    |


<br/>
<br/>
<br/>

## 담당 기능 상세

### 모델 파트

- **자세 및 피로도 판단을 위한 데이터를 수집하고, 필요한 Feature를 추출하여 모델 학습 및 판단 로직을 구성합니다.**
  - Pose Landmark 기반 자세 Feature 추출
  - Face Landmark 기반 피로도 Feature 추출
  - 학습용 데이터 수집
  - 자세 및 피로도 판단 모델 구현
  - 사용자별 기준 자세 데이터 활용

<br/>

### 프론트엔드 파트

- **측정된 데이터를 사용자가 이해하기 쉽게 웹 화면에 시각화합니다.**
  - 실시간 측정 시작 / 종료 UI
  - 일일 리포트 화면 구현
  - 자세 점수 표시
  - 차트 및 수치 데이터 시각화
  - 사용자 피드백 메시지 출력
  - CSV / JSON 기반 데이터 연동

<br/>

### 하드웨어 파트

- **비정상적인 자세가 감지되었을 때 사용자에게 물리적인 피드백을 제공합니다.**
  - 부저 알림 기능
  - 진동 알림 기능
  - 라즈베리파이 기반 하드웨어 제어
  - 자세 불균형 상태에 따른 알림 처리

<br/>
<br/>
<br/>


# 5. Technology Stack (기술 스택)
## 5.1 Stacks
|  |  |
|-----------------|-----------------|
| Python    |<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/4786246569c1237d3ee9a73786d18f3fbdaa8efe/Python.png" alt="Python" width="100">|
| RasPI5    |<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/4786246569c1237d3ee9a73786d18f3fbdaa8efe/Raspberry%20Pi%20(1).png" alt="Raspi5" width="100">|
| TensorFlow    |<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/4786246569c1237d3ee9a73786d18f3fbdaa8efe/TensorFlow.png" alt="TensorFlow" width="100">|
| Arduino    |<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/b384f1fd15d78fb33fb819dfae5760fef20a0fd3/Arduino.png" alt="Arduino" width="100">|
<br/>

## 5.2 Tools
|  |  |  |
|-----------------|-----------------|-----------------|
| PyQt    |  <img width="100" height="100" alt="Image" src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/3856e4dc4cf324b7b757dc39256c0d044d13651b/Qt%20Framework.png" /> |  |
| Git    |  <img src="https://github.com/user-attachments/assets/483abc38-ed4d-487c-b43a-3963b33430e6" alt="git" width="100">    |
| Streamlit    |<img src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/6fb8c9841f37247689fd3032bf65cb00c0d38769/Streamlit.png" alt="Streamlit" width="100">|

<br/>

## 5.3 Collaboration
|  |  |
|-----------------|-----------------|
| Notion    |  <img src="https://github.com/user-attachments/assets/34141eb9-deca-416a-a83f-ff9543cc2f9a" alt="Notion" width="100">    |
| Discord    |  <img width="100" height="100" alt="Discord" src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/6fb8c9841f37247689fd3032bf65cb00c0d38769/discord.png" />   |

<br/>

# 6. Project Structure (프로젝트 구조)

<img alt="SystemArchitecture" src="https://github.com/VisionAITeamProject/ImageUploadRepo/blob/cacffd38a044ea610876e089157071acede97404/TempImage.png"/>

<br/>
<br/>
<br/>

## 데이터 흐름

| 단계 | 설명 |
|---|---|
| 1 | 카메라 영상 입력 |
| 2 | Pose / Face Landmark 추출 |
| 3 | 자세 및 피로도 Feature 계산 |
| 4 | 모델 또는 판단 로직을 통한 상태 분류 |
| 5 | 비정상 자세 감지 시 하드웨어 알림 발생 |
| 6 | 측정 데이터 CSV / JSON 저장 |
| 7 | 일일 리포트 웹 화면에 통계 표시 |

<br/>

## 기대 효과

- 사용자가 자신의 자세 습관을 객관적으로 확인할 수 있음
- 비정상 자세를 실시간으로 인지하고 빠르게 교정 가능
- 하루 단위 리포트를 통해 장기적인 자세 개선 방향 제공
- 비전 AI, 웹, 하드웨어를 결합한 통합형 자세 코칭 시스템 구현

## Raspberry Pi BLE Wi-Fi Provisioning

BLE는 최초 Wi-Fi 설정에만 사용합니다. 실제 측정 데이터는 Wi-Fi 연결 후 HTTP/WebSocket/MJPG로 전송합니다. `/provisioning/ble/*`는 개발 PC와 Flutter 사전 연동을 위한 HTTP mock이며 실제 Bluetooth가 아닙니다. 실제 peripheral은 BlueZ system D-Bus 기반 `WorkSpace/network/ble_gatt_server.py`입니다. `dbus-next`는 BlueZ API를 Python에서 비동기로 등록하기 위한 얇은 D-Bus 클라이언트로 선택했습니다.

Raspberry Pi OS에서 다음 구성요소가 필요합니다.

```bash
sudo apt update
sudo apt install -y bluez network-manager python3-venv
cd WorkSpace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt
sudo systemctl enable --now bluetooth
sudo systemctl status bluetooth
bluetoothctl show
nmcli device status
VPC_WIFI_MODE=real python tools/run_ble_gatt_server.py
```

옵션은 `--device-name VisionPoseCoach-Pi`, `--wifi-mode mock`, `--debug`입니다. 일반 사용자 D-Bus 정책에서 GATT 등록이 거부되면 전용 systemd 서비스/BlueZ policy 구성을 권장하며, 진단 목적으로만 `sudo -E` 실행 여부를 확인할 수 있습니다. 광고가 보이지 않으면 아래를 점검합니다. 코드는 시스템 설정을 자동 변경하지 않습니다.

```bash
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth
rfkill list bluetooth
bluetoothctl show
journalctl -u bluetooth -n 100 --no-pager
```

어댑터가 `Powered: yes`인지, BlueZ가 GATT/LE Advertising manager를 노출하는지, 동시에 실행 중인 다른 GATT peripheral이 없는지 확인합니다. 실제 UUID와 Flutter 흐름은 `WorkSpace/BLE_GATT_SPEC.md`를 따릅니다.

<br/>

## 프로젝트 차별점

- 단순 자세 감지가 아닌 실시간 교정 유도 기능 제공
- Pose와 Face 데이터를 함께 활용하여 자세와 피로도를 종합적으로 분석
- 일일 리포트를 통해 사용자의 자세 패턴을 시각적으로 제공
- 라즈베리파이와 하드웨어 알림 장치를 활용한 실사용 중심 시스템
- DB 없이 CSV / JSON 기반으로 간단하고 가볍게 동작하는 로컬 MVP 구조

<br/>
<br/>

