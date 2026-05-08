# face_dataset.py
# ============================================================
# 필요한 라이브러리 import
# ============================================================
import os
import glob
import cv2
import pandas as pd
import mediapipe as mp
from detector import LandmarkerDetector
from facemodule import FaceModule

# ============================================================
# 0. 폴더 존재 확인 함수
# ============================================================

def check_parent_dir_exists(path: str):
    r"""
    CSV 파일을 저장하기 전에, 저장할 폴더가 이미 존재하는지만 확인한다.

    중요:
        이 함수는 폴더를 자동 생성하지 않는다.
        팀원이 직접 아래 폴더를 만들어둔 상태에서 실행해야 한다.

    예:
        C:\Users\KCCISTC\Desktop\csv
    """

    folder = os.path.dirname(path)

    # output.csv처럼 현재 폴더에 바로 저장하는 경우는 검사하지 않는다.
    if folder == "":
        return

    # 폴더가 없으면 자동 생성하지 않고 에러를 발생시킨다.
    if not os.path.isdir(folder):
        raise FileNotFoundError(
            f"CSV 저장 폴더가 없습니다. 폴더를 먼저 만들어주세요: {folder}"
        )


# ============================================================
# 1. 영상 1개 -> 프레임 단위 CSV 저장
# ============================================================

def save_frame_csv_from_video(
    video_path: str,
    output_csv_path: str,
    label: str,
    skip_frame: int = 1
):
    """
    영상 1개를 읽어서 프레임 단위 feature CSV로 저장하는 함수.

    이 함수의 역할:
        1. 영상 파일을 연다.
        2. 프레임을 하나씩 읽는다.
        3. 각 프레임을 MediaPipe Image로 변환한다.
        4. FaceLandmarker로 얼굴을 분석한다.
        5. FaceModule로 눈/입/하품 관련 feature를 추출한다.
        6. 프레임 하나당 CSV 한 줄로 저장한다.

    여기서 만들어지는 CSV는 최종 학습용 CSV가 아니라,
    '프레임 단위 원본 feature CSV'이다.

    예:
        30fps, 60초 영상, skip_frame=1이면
        약 1800개의 프레임 데이터가 저장된다.

    Parameters
    ----------
    video_path:
        분석할 영상 파일 경로.
        예: "videos/normal/normal_01.mp4"

    output_csv_path:
        프레임 단위 CSV 저장 경로.
        예: "csv/frame/frame_normal_normal_01.csv"

    label:
        이 영상에 붙일 정답 라벨.
        예:
            "normal"
            "drowsy"

        현재 구조에서는 영상 하나 전체가 하나의 라벨이라고 가정한다.

    skip_frame:
        몇 프레임마다 분석할지 정하는 값.

        skip_frame=1:
            모든 프레임 분석

        skip_frame=2:
            2프레임마다 1개만 분석

        skip_frame=5:
            5프레임마다 1개만 분석

        라즈베리파이에서 처리 속도가 느리면 값을 올릴 수 있다.
    """

    # CSV 저장 폴더가 없으면 자동 생성
    check_parent_dir_exists(output_csv_path)

    # MediaPipe FaceLandmarker / PoseLandmarker 탐지 객체 생성
    detector = LandmarkerDetector()

    # 얼굴 feature 추출 객체 생성
    # 나중에 30초 단위 CSV로 변환할 것이기 때문에
    # FaceModule 내부 window도 30초로 맞춘다.
    face_module = FaceModule(window_sec=30.0)

    # OpenCV로 영상 파일 열기
    cap = cv2.VideoCapture(video_path)

    # 영상이 정상적으로 열리지 않으면 에러 발생
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {video_path}")

    # 영상의 FPS 가져오기
    # 1초에 몇 개의 프레임이 있는지 의미한다.
    fps = cap.get(cv2.CAP_PROP_FPS)

    # FPS를 제대로 읽지 못하는 경우 기본값 30 사용
    if fps <= 0:
        fps = 30.0

    # 영상 파일 이름만 추출
    # 예:
    # "videos/normal/normal_01.mp4" -> "normal_01.mp4"
    video_name = os.path.basename(video_path)

    # FaceModule에서 사용하는 feature 이름 목록 가져오기
    #
    # 예:
    # eye_blink_left
    # eye_blink_right
    # eye_closed_score
    # eye_closed_duration
    # jaw_open
    # mouth_open_duration
    # yawn_count_window
    # no_face_duration
    # fatigue_feature_score
    feature_names = face_module.get_feature_names()

    # CSV에 저장할 행들을 담는 리스트
    rows = []

    # 원본 영상 기준 프레임 번호
    frame_idx = 0

    # 실제 CSV에 저장되는 샘플 번호
    #
    # skip_frame=1이면 frame_idx와 거의 같지만,
    # skip_frame=5이면 frame_idx는 0, 5, 10...으로 증가하고
    # sample_idx는 0, 1, 2...로 증가한다.
    sample_idx = 0

    # 이전에 처리한 프레임의 시간
    # dt 계산에 사용한다.
    prev_timestamp_sec = None

    print("\n====================================")
    print(f"[INFO] 영상 분석 시작: {video_path}")
    print(f"[INFO] FPS: {fps:.2f}")
    print(f"[INFO] Label: {label}")
    print(f"[INFO] Output: {output_csv_path}")
    print("====================================")

    # 영상이 끝날 때까지 반복
    while True:
        # cap.read()는 영상에서 프레임을 한 장 읽는다.
        #
        # ret:
        #   읽기 성공 여부
        #
        # frame:
        #   실제 이미지 프레임
        ret, frame = cap.read()

        # ret이 False이면 영상 끝 또는 읽기 실패
        if not ret:
            break

        # skip_frame 조건에 맞지 않는 프레임은 분석하지 않고 건너뛴다.
        #
        # 예:
        # skip_frame=5이면 frame_idx가 0, 5, 10, 15...일 때만 분석한다.
        if frame_idx % skip_frame != 0:
            frame_idx += 1
            continue

        # 현재 프레임이 영상 시작 후 몇 초 지점인지 계산
        #
        # 예:
        # frame_idx = 90
        # fps = 30
        # timestamp_sec = 3.0초
        timestamp_sec = frame_idx / fps

        # dt 계산
        #
        # dt는 이전에 처리한 프레임과 현재 프레임 사이의 시간 차이다.
        #
        # 이 값은 나중에:
        # - 눈을 감은 총 시간
        # - 입을 벌린 총 시간
        # - 눈 감김 비율
        # 등을 계산할 때 중요하다.
        #
        # 첫 번째 프레임은 이전 프레임이 없으므로 dt=0.0으로 둔다.
        if prev_timestamp_sec is None:
            dt = 0.0
        else:
            dt = timestamp_sec - prev_timestamp_sec

        # 다음 프레임에서 dt를 계산하기 위해 현재 시간을 저장한다.
        prev_timestamp_sec = timestamp_sec

        # OpenCV는 BGR 형식으로 이미지를 읽는다.
        # MediaPipe는 RGB 형식을 사용하므로 변환해야 한다.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # RGB 이미지를 MediaPipe Image 객체로 변환한다.
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb
        )

        # MediaPipe 얼굴/자세 탐지 실행
        #
        # face_res:
        #   얼굴 랜드마크와 face blendshape 결과
        #
        # pose_res:
        #   자세 랜드마크 결과
        #
        # 현재 face_dataset.py에서는 face_res만 사용한다.
        # pose_res는 나중에 거북목, 어깨 기울어짐 등을 추가할 때 활용 가능하다.
        face_res, pose_res = detector.detect(mp_image)

        # FaceModule로 얼굴 feature 추출
        #
        # face_features에는 다음 정보가 들어간다.
        # - face_detected
        # - eye_blink_left
        # - eye_blink_right
        # - eye_closed_score
        # - eye_closed_duration
        # - jaw_open
        # - mouth_open_duration
        # - yawn_count_window
        # - no_face_duration
        # - fatigue_feature_score
        face_features = face_module.update(face_res, dt)

        # FaceFeatures 객체를 MLP 입력용 숫자 리스트로 변환한다.
        #
        # feature_names와 model_input은 같은 순서를 가진다.
        model_input = face_module.to_model_input(face_features)

        # 현재 프레임에서 눈을 감았는지 여부 계산
        #
        # eye_closed_score:
        #   왼쪽/오른쪽 눈 감김 정도의 평균
        #
        # face_module.eye_closed_threshold:
        #   눈을 감았다고 판단하는 기준값
        #
        # 기준값 이상이면 눈 감음 = 1
        # 아니면 눈 뜸 = 0
        is_eye_closed = int(face_features.eye_closed_score >= face_module.eye_closed_threshold)

        # 프레임 단위 CSV의 한 줄 생성
        row = {
            # 어떤 영상에서 나온 프레임인지
            "video_name": video_name,

            # 원본 영상 기준 프레임 번호
            "frame_idx": frame_idx,

            # CSV 저장 기준 샘플 번호
            "sample_idx": sample_idx,

            # 영상 시작 후 몇 초 지점인지
            "timestamp_sec": round(timestamp_sec, 4),

            # 이전 처리 프레임과 현재 프레임 사이의 시간 차이
            #
            # 나중에 30초 구간에서 is_eye_closed가 1인 프레임들의 dt를 더하면
            # 30초 동안 눈을 감은 총 시간을 구할 수 있다.
            "dt": round(dt, 6),

            # 얼굴 감지 여부
            # True/False를 1/0으로 변환해서 저장
            "face_detected": int(face_features.face_detected),

            # 현재 프레임에서 눈을 감았는지 여부
            "is_eye_closed": is_eye_closed,

            # 정답 라벨
            "label": label
        }

        # FaceModule에서 추출한 feature들을 row에 추가한다.
        #
        # 예:
        # row["eye_blink_left"] = 0.13
        # row["jaw_open"] = 0.05
        for name, value in zip(feature_names, model_input):
            row[name] = value

        # 완성된 프레임 데이터를 rows에 추가한다.
        rows.append(row)

        # 진행 상황 출력
        # 30fps 기준 sample_idx 150개는 약 5초 정도에 해당한다.
        if sample_idx % 150 == 0:
            print(f"[INFO] 저장 프레임 {sample_idx}개 처리 중... ({timestamp_sec:.1f}초)")

        # 다음 프레임 처리를 위해 인덱스 증가
        frame_idx += 1
        sample_idx += 1

    # 영상 파일 자원 해제
    cap.release()

    # MediaPipe detector 자원 해제
    detector.close()

    # rows 리스트를 DataFrame으로 변환
    df = pd.DataFrame(rows)

    # DataFrame을 CSV로 저장
    #
    # index=False:
    #   pandas가 자동으로 붙이는 index 컬럼을 저장하지 않음
    #
    # encoding="utf-8-sig":
    #   엑셀에서 열었을 때 한글 깨짐을 줄이기 위해 사용
    df.to_csv(
        output_csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"[DONE] 프레임 단위 CSV 저장 완료: {output_csv_path}")
    print(f"[DONE] 저장된 프레임 수: {len(df)}")


# ============================================================
# 2. 프레임 단위 CSV -> 30초 단위 CSV 변환
# ============================================================

def convert_frame_csv_to_30sec_csv(
    frame_csv_path: str,
    output_csv_path: str,
    window_sec: int = 30
):
    """
    프레임 단위 CSV를 30초 단위 CSV로 변환하는 함수.

    핵심 목적:
        프레임마다 얻은 값을 그대로 학습에 쓰는 것이 아니라,
        30초 동안의 상태를 하나의 데이터로 요약한다.

    예:
        30fps 영상이면 30초 동안 약 900프레임이 있다.
        이 900개의 프레임 feature를 하나의 행으로 요약한다.

    이 함수에서 계산하는 주요 값:
        1. 각 feature의 평균, 표준편차, 최댓값, 최솟값
        2. 30초 동안 얼굴이 감지된 비율
        3. 30초 동안 눈을 감은 총 시간
        4. 30초 중 눈을 감고 있었던 비율

    변환 방식:
        timestamp_sec 기준으로 30초씩 묶는다.

        0초 이상 30초 미만:
            window_id = 0

        30초 이상 60초 미만:
            window_id = 1

        60초 이상 90초 미만:
            window_id = 2
    """

    # 출력 CSV 저장 폴더 생성
    check_parent_dir_exists(output_csv_path)

    # 프레임 단위 CSV 읽기
    df = pd.read_csv(frame_csv_path)

    # 이 함수가 동작하기 위해 반드시 필요한 컬럼들
    #
    # dt:
    #   눈 감은 총 시간을 계산할 때 필요
    #
    # is_eye_closed:
    #   어떤 프레임이 눈 감은 상태인지 판단할 때 필요
    required_cols = [
        "video_name",
        "frame_idx",
        "sample_idx",
        "timestamp_sec",
        "dt",
        "face_detected",
        "is_eye_closed",
        "label"
    ]

    # 필요한 컬럼이 없으면 에러 발생
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"CSV에 {col} 컬럼이 없습니다: {frame_csv_path}")

    # timestamp_sec 기준으로 30초 구간 번호 생성
    #
    # 예:
    # timestamp_sec = 0.0  -> window_id = 0
    # timestamp_sec = 29.9 -> window_id = 0
    # timestamp_sec = 30.0 -> window_id = 1
    # timestamp_sec = 61.2 -> window_id = 2
    df["window_id"] = (df["timestamp_sec"] // window_sec).astype(int)

    # 통계 계산에서 제외할 컬럼들
    #
    # dt와 is_eye_closed는 별도로 의미 있는 값을 계산하기 때문에
    # 여기서는 일반 feature 통계 계산 대상에서 제외한다.
    #
    # 원하면 is_eye_closed_mean을 추가로 써도 되지만,
    # 여기서는 eye_closed_ratio를 따로 계산하므로 제외한다.
    exclude_cols = [
        "video_name",
        "frame_idx",
        "sample_idx",
        "timestamp_sec",
        "dt",
        "face_detected",
        "is_eye_closed",
        "label",
        "window_id"
    ]

    # 실제 얼굴 feature 컬럼만 선택
    feature_cols = [
        col for col in df.columns
        if col not in exclude_cols
    ]

    # 30초 단위 결과 행들을 담을 리스트
    rows = []

    # 같은 영상의 같은 30초 구간끼리 묶는다.
    grouped = df.groupby(["video_name", "window_id"])

    # 각 30초 구간마다 반복
    for (video_name, window_id), group in grouped:

        # 구간 시작/종료 시간
        start_sec = float(group["timestamp_sec"].min())
        end_sec = float(group["timestamp_sec"].max())

        # 이 30초 구간에서 실제로 처리한 시간 길이 계산
        #
        # 기본적으로 dt를 모두 더하면,
        # 이 구간에서 분석한 프레임들이 대표하는 시간 길이가 된다.
        window_duration_sec = float(group["dt"].sum())

        # 만약 dt 합이 0이면 예외적으로 timestamp 범위로 계산
        #
        # 예:
        # 프레임이 1개뿐인 경우
        if window_duration_sec <= 0:
            window_duration_sec = max(end_sec - start_sec, 0.0)

        # 30초로 나누고 남은 시간(30초 이하 시간)은 버린다
        if window_duration_sec < window_sec * 0.8:
            continue

        # 30초 구간 안에서 눈을 감은 총 시간 계산
        #
        # is_eye_closed == 1인 프레임들의 dt를 더한다.
        #
        # 예:
        # 30초 동안 눈 감은 프레임들이 대표하는 시간이 총 5초라면
        # eye_closed_total_sec = 5.0
        eye_closed_total_sec = float(
            group.loc[group["is_eye_closed"] == 1, "dt"].sum()
        )

        # 30초 구간 중 눈을 감고 있었던 비율 계산
        #
        # 예:
        # eye_closed_total_sec = 6초
        # window_duration_sec = 30초
        # eye_closed_ratio = 6 / 30 = 0.2
        #
        # 즉, 30초 중 20% 동안 눈을 감고 있었다는 의미다.
        if window_duration_sec <= 0:
            eye_closed_ratio = 0.0
        else:
            eye_closed_ratio = eye_closed_total_sec / window_duration_sec

        # 비율은 0~1 사이가 정상 범위이므로 안전하게 제한한다.
        eye_closed_ratio = max(0.0, min(eye_closed_ratio, 1.0))

        # 30초 단위 CSV 한 줄 생성
        row = {
            # 영상 이름
            "video_name": video_name,

            # 몇 번째 30초 구간인지
            "window_id": int(window_id),

            # 구간 시작/종료 시간
            "start_sec": start_sec,
            "end_sec": end_sec,

            # 실제 계산에 사용한 구간 길이
            "window_duration_sec": window_duration_sec,

            # 원본 영상 기준 시작/끝 프레임 번호
            "start_frame_idx": int(group["frame_idx"].min()),
            "end_frame_idx": int(group["frame_idx"].max()),

            # CSV 저장 기준 시작/끝 샘플 번호
            "start_sample_idx": int(group["sample_idx"].min()),
            "end_sample_idx": int(group["sample_idx"].max()),

            # 이 구간에 포함된 프레임 수
            "frame_count": len(group),

            # 얼굴 감지 비율
            #
            # face_detected는 1 또는 0이므로 평균을 내면 비율이 된다.
            "face_detected_ratio": float(group["face_detected"].mean()),

            # 핵심 졸음 feature 1:
            # 30초 동안 눈을 감고 있었던 총 시간
            "eye_closed_total_sec": eye_closed_total_sec,

            # 핵심 졸음 feature 2:
            # 30초 중 눈을 감고 있었던 비율
            "eye_closed_ratio": eye_closed_ratio,

            # 해당 구간의 정답 라벨
            "label": group["label"].iloc[0]
        }

        # 각 얼굴 feature에 대해 통계값 계산
        #
        # 예:
        # eye_closed_score라는 feature가 있으면,
        # 아래 4개 컬럼이 생성된다.
        #
        # eye_closed_score_mean
        # eye_closed_score_std
        # eye_closed_score_max
        # eye_closed_score_min
        for col in feature_cols:
            row[f"{col}_mean"] = group[col].mean()
            row[f"{col}_std"] = group[col].std()
            row[f"{col}_max"] = group[col].max()
            row[f"{col}_min"] = group[col].min()

        # 완성된 30초 구간 데이터를 rows에 추가
        rows.append(row)

    # 리스트를 DataFrame으로 변환
    result_df = pd.DataFrame(rows)

    # 표준편차 계산 결과가 NaN이 되는 경우가 있다.
    # MLP 학습에서는 NaN을 사용할 수 없으므로 0으로 채운다.
    result_df = result_df.fillna(0)

    # 30초 단위 CSV 저장
    result_df.to_csv(
        output_csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"[DONE] {window_sec}초 단위 CSV 저장 완료: {output_csv_path}")
    print(f"[DONE] 총 window 수: {len(result_df)}")


# ============================================================
# 3. 폴더 안 모든 영상 처리
# ============================================================

def build_30sec_dataset_from_video_folder(
    video_dir: str,
    label: str,
    frame_csv_dir: str = "csv/frame",
    window_csv_dir: str = "csv/window30sec",
    window_sec: int = 30,
    skip_frame: int = 1
):
    """
    폴더 안에 있는 모든 영상을 자동으로 처리하는 함수.

    이 함수는 위의 두 함수를 순서대로 실행한다.

    처리 과정:
        1. video_dir 안의 모든 영상 파일을 찾는다.
        2. 각 영상마다 프레임 단위 CSV를 만든다.
        3. 생성된 프레임 CSV를 30초 단위 CSV로 변환한다.
        4. 변환된 CSV를 window_csv_dir에 저장한다.

    예:
        videos/normal/
            normal_01.mp4
            normal_02.mp4

        결과:
            csv/frame/
                frame_normal_normal_01.csv
                frame_normal_normal_02.csv

            csv/window30sec/
                window30sec_normal_normal_01.csv
                window30sec_normal_normal_02.csv
    """

    # 처리할 영상 확장자 목록
    video_extensions = ["mp4", "avi", "mov", "mkv"]

    # 찾은 영상 파일 경로를 담는 리스트
    video_files = []

    # 확장자별로 영상 파일 검색
    for ext in video_extensions:
        video_files.extend(
            glob.glob(os.path.join(video_dir, f"*.{ext}"))
        )

    # 처리 순서를 일정하게 하기 위해 정렬
    video_files = sorted(video_files)

    # 영상 파일이 없으면 에러 발생
    if len(video_files) == 0:
        raise FileNotFoundError(f"영상 파일이 없습니다: {video_dir}")

    print("====================================")
    print(f"[INFO] 영상 폴더: {video_dir}")
    print(f"[INFO] 총 영상 수: {len(video_files)}")
    print(f"[INFO] Label: {label}")
    print(f"[INFO] Window: {window_sec}초")
    print("====================================")

    # 폴더 안의 모든 영상 처리
    for video_path in video_files:
        # 영상 파일 이름에서 확장자 제거
        #
        # 예:
        # normal_01.mp4 -> normal_01
        base_name = os.path.splitext(os.path.basename(video_path))[0]

        # 프레임 단위 CSV 저장 경로
        frame_csv_path = os.path.join(
            frame_csv_dir,
            f"frame_{label}_{base_name}.csv"
        )

        # 30초 단위 CSV 저장 경로
        window_csv_path = os.path.join(
            window_csv_dir,
            f"window{window_sec}sec_{label}_{base_name}.csv"
        )

        # 1단계: 영상 -> 프레임 단위 CSV
        save_frame_csv_from_video(
            video_path=video_path,
            output_csv_path=frame_csv_path,
            label=label,
            skip_frame=skip_frame
        )

        # 2단계: 프레임 단위 CSV -> 30초 단위 CSV
        convert_frame_csv_to_30sec_csv(
            frame_csv_path=frame_csv_path,
            output_csv_path=window_csv_path,
            window_sec=window_sec
        )

    print("\n[DONE] 폴더 안 모든 영상 처리 완료")


# ============================================================
# 4. 여러 30초 CSV 합치기
# ============================================================

def merge_window_csv_files(
    window_csv_dir: str = "csv/window30sec",
    output_csv_path: str = "csv/window30sec_all.csv",
    pattern: str = "window30sec_*.csv"
):
    """
    여러 개의 30초 단위 CSV를 하나로 합치는 함수.

    왜 필요한가?
        MLP 학습은 보통 하나의 통합 CSV로 진행하는 것이 편하다.

    예:
        csv/window30sec/
            window30sec_normal_normal_01.csv
            window30sec_normal_normal_02.csv
            window30sec_drowsy_drowsy_01.csv

        위 파일들을 합쳐서:

            csv/window30sec_all.csv

        로 만든다.
    """

    # 출력 폴더 생성
    check_parent_dir_exists(output_csv_path)

    # pattern에 맞는 CSV 파일 찾기
    csv_files = sorted(
        glob.glob(os.path.join(window_csv_dir, pattern))
    )

    # 합칠 CSV가 없으면 에러 발생
    if len(csv_files) == 0:
        raise FileNotFoundError(f"합칠 CSV 파일이 없습니다: {window_csv_dir}/{pattern}")

    # 각 CSV의 DataFrame을 담을 리스트
    df_list = []

    print("[INFO] 30초 CSV 병합 시작")

    # CSV 파일들을 하나씩 읽기
    for csv_file in csv_files:
        print(f"[INFO] 읽는 중: {csv_file}")
        df = pd.read_csv(csv_file)
        df_list.append(df)

    # 여러 DataFrame을 세로 방향으로 합치기
    merged_df = pd.concat(df_list, ignore_index=True)

    # 병합 CSV 저장
    merged_df.to_csv(
        output_csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"[DONE] 병합 CSV 저장 완료: {output_csv_path}")
    print(f"[DONE] 병합된 파일 수: {len(csv_files)}")
    print(f"[DONE] 총 행 수: {len(merged_df)}")


# ============================================================
# 5. 실행 예시
# ============================================================

if __name__ == "__main__":
    r"""
    face_dataset.py를 직접 실행했을 때만 아래 코드가 실행된다.

    주의:
        이 코드는 폴더를 자동 생성하지 않는다.
        위 폴더들을 먼저 직접 만들어둔 뒤 실행해야 한다.
    """

    # 바탕화면 로컬 데이터 경로
    # 파일 구조 ↓
    #C:\Users\KCCISTC\Desktop\videos
    #C:\Users\KCCISTC\Desktop\videos\normal
    #C:\Users\KCCISTC\Desktop\videos\drowsy
    #C:\Users\KCCISTC\Desktop\csv
    # (파일 경로 각자 환경에 맞게 수정해주세요!!!!!!!!!!!!)
    # (파일 경로 각자 환경에 맞게 수정해주세요!!!!!!!!!!!!)
    # (파일 경로 각자 환경에 맞게 수정해주세요!!!!!!!!!!!!)
    # ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
    VIDEO_ROOT = r"C:\Users\KCCISTC\Desktop\videos"
    CSV_ROOT = r"C:\Users\KCCISTC\Desktop\csv"
    # ↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑
    # (파일 경로 수정하셨나요?)
    # (파일 경로 수정하셨나요?)
    # (파일 경로 수정하셨나요?)

    # 영상 입력 폴더
    NORMAL_VIDEO_DIR = os.path.join(VIDEO_ROOT, "normal")
    DROWSY_VIDEO_DIR = os.path.join(VIDEO_ROOT, "drowsy")

    # CSV 출력 폴더
    # 폴더 자동 생성을 하지 않기 위해 frame/window CSV 모두 CSV_ROOT에 바로 저장한다.
    FRAME_CSV_DIR = CSV_ROOT
    WINDOW_CSV_DIR = CSV_ROOT
    MERGED_CSV_PATH = os.path.join(CSV_ROOT, "window30sec_all.csv")

    build_30sec_dataset_from_video_folder(
        video_dir=NORMAL_VIDEO_DIR,
        label="normal",
        frame_csv_dir=FRAME_CSV_DIR,
        window_csv_dir=WINDOW_CSV_DIR,
        window_sec=30,
        skip_frame=1
    )
    print("normal 데이터셋 생성 완료")

    build_30sec_dataset_from_video_folder(
        video_dir=DROWSY_VIDEO_DIR,
        label="drowsy",
        frame_csv_dir=FRAME_CSV_DIR,
        window_csv_dir=WINDOW_CSV_DIR,
        window_sec=30,
        skip_frame=1
    )
    print("drowsy 데이터셋 생성 완료")

    merge_window_csv_files(
        window_csv_dir=WINDOW_CSV_DIR,
        output_csv_path=MERGED_CSV_PATH,
        pattern="window30sec_*.csv"
    )
