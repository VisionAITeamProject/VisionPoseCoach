import os
import json
import pickle
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import mediapipe as mp


# ============================================================
# 0. 경로 설정
# ============================================================

VIDEO_DIR = r"C:\Users\KCCISTC\Desktop\정상\정상 영상"

# face_landmarker.task 위치만 본인 환경에 맞게 수정
FACE_LANDMARKER_TASK = r"C:\Users\KCCISTC\Desktop\VisionPoseCoach\WorkSpace\tasks\face_landmarker.task"

OUTPUT_ROOT = r"C:\Users\KCCISTC\Desktop\정상\정상_GRU_처리결과"

RAW_BLENDSHAPE_DIR = os.path.join(OUTPUT_ROOT, "01_raw_blendshape_frame")
FEATURE_DIR = os.path.join(OUTPUT_ROOT, "02_feature_frame")
BASELINE_DIR = os.path.join(OUTPUT_ROOT, "03_baseline")
CALIBRATED_DIR = os.path.join(OUTPUT_ROOT, "04_calibrated_feature_frame")
GRU_DIR = os.path.join(OUTPUT_ROOT, "05_GRU_window60_stride5")

for d in [
    RAW_BLENDSHAPE_DIR,
    FEATURE_DIR,
    BASELINE_DIR,
    CALIBRATED_DIR,
    GRU_DIR,
]:
    os.makedirs(d, exist_ok=True)


# ============================================================
# 1. 설정값
# ============================================================

LABEL = 0  # 정상 영상이므로 label = 0

WINDOW_SIZE = 60
STRIDE = 5

FEATURE_COLUMNS = [
    "leftEyeBlink",
    "rightEyeBlink",
    "eyeClosed",
    "jawOpen",
]

VIDEO_EXTENSIONS = [
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv"
]

# MediaPipe FaceLandmarker blendshape 전체 목록
BLENDSHAPE_COLUMNS = [
    "_neutral",
    "browDownLeft", "browDownRight",
    "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff",
    "cheekSquintLeft", "cheekSquintRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight",
    "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose",
    "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft",
    "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight",
    "mouthPucker",
    "mouthRight",
    "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight",
    "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
    "noseSneerLeft", "noseSneerRight",
]


# ============================================================
# 2. 유틸 함수
# ============================================================

def safe_filename(name: str) -> str:
    return Path(name).stem.replace(" ", "_")


def find_video_files(video_dir: str):
    video_dir = Path(video_dir)
    video_files = []

    for ext in VIDEO_EXTENSIONS:
        video_files.extend(video_dir.rglob(f"*{ext}"))

    return sorted(video_files)


def create_face_landmarker():
    BaseOptions = mp.tasks.BaseOptions
    FaceLandmarker = mp.tasks.vision.FaceLandmarker
    FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=FACE_LANDMARKER_TASK),
        output_face_blendshapes=True,
        num_faces=1,
        running_mode=VisionRunningMode.IMAGE,
    )

    return FaceLandmarker.create_from_options(options)


# ============================================================
# 3. 프레임 단위 raw blendshape 추출
# ============================================================

def extract_raw_blendshape_from_video(video_path: Path, landmarker) -> pd.DataFrame:
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        print(f"영상 열기 실패: {video_path}")
        return pd.DataFrame()

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps is None or fps <= 0:
        fps = 0.0

    rows = []
    frame_idx = 0
    detected_count = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame,
        )

        result = landmarker.detect(mp_image)

        # 얼굴 미인식 프레임은 저장하지 않음
        if result.face_blendshapes:
            blendshapes = result.face_blendshapes[0]

            score_dict = {
                category.category_name: float(category.score)
                for category in blendshapes
            }

            row = {
                "video_name": video_path.name,
                "frame_idx": frame_idx,
                "timestamp_sec": frame_idx / fps if fps > 0 else np.nan,
                "label": LABEL,
            }

            for col in BLENDSHAPE_COLUMNS:
                row[col] = score_dict.get(col, 0.0)

            rows.append(row)
            detected_count += 1

        frame_idx += 1

    cap.release()

    print(
        f"[raw 추출 완료] {video_path.name} | "
        f"전체 프레임: {frame_idx}, 얼굴 인식 프레임: {detected_count}"
    )

    return pd.DataFrame(rows)


# ============================================================
# 4. raw blendshape -> 필요한 4개 feature 변환
# ============================================================

def convert_raw_to_features(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    feature_df = pd.DataFrame()

    feature_df["video_name"] = raw_df["video_name"]
    feature_df["frame_idx"] = raw_df["frame_idx"]
    feature_df["timestamp_sec"] = raw_df["timestamp_sec"]
    feature_df["label"] = raw_df["label"]

    feature_df["leftEyeBlink"] = raw_df["eyeBlinkLeft"].astype(float)
    feature_df["rightEyeBlink"] = raw_df["eyeBlinkRight"].astype(float)

    # 양쪽 눈 감김 정도
    feature_df["eyeClosed"] = (
        feature_df["leftEyeBlink"] + feature_df["rightEyeBlink"]
    ) / 2.0

    feature_df["jawOpen"] = raw_df["jawOpen"].astype(float)

    return feature_df


# ============================================================
# 5. 정상 영상 feature 평균으로 baseline 계산
# ============================================================

def calculate_baseline(feature_all_df: pd.DataFrame) -> dict:
    baseline = {}

    for col in FEATURE_COLUMNS:
        baseline[col] = float(feature_all_df[col].mean())

    return baseline


def save_baseline(baseline: dict):
    baseline_csv_path = os.path.join(BASELINE_DIR, "face_baseline_normal_mean.csv")
    baseline_json_path = os.path.join(BASELINE_DIR, "face_baseline_normal_mean.json")
    baseline_pkl_path = os.path.join(BASELINE_DIR, "face_baseline.pkl")

    pd.DataFrame([baseline]).to_csv(
        baseline_csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    with open(baseline_json_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=4)

    with open(baseline_pkl_path, "wb") as f:
        pickle.dump(baseline, f)

    print("baseline 저장 완료")
    print("CSV :", baseline_csv_path)
    print("JSON:", baseline_json_path)
    print("PKL :", baseline_pkl_path)


# ============================================================
# 6. baseline 기준으로 feature 보정
# ============================================================

def apply_baseline_calibration(feature_df: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    if feature_df.empty:
        return pd.DataFrame()

    calibrated_df = feature_df.copy()

    for col in FEATURE_COLUMNS:
        calibrated_df[col] = calibrated_df[col].astype(float) - baseline[col]

    return calibrated_df


# ============================================================
# 7. 보정된 feature CSV -> GRU window CSV 생성
# ============================================================

def make_gru_windows(calibrated_all_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    window_id_global = 0

    for video_name, group in calibrated_all_df.groupby("video_name"):
        group = group.sort_values("frame_idx").reset_index(drop=True)

        if len(group) < WINDOW_SIZE:
            print(f"[GRU 제외] {video_name} | 유효 프레임 {len(group)}개")
            continue

        window_id_in_video = 0

        for start in range(0, len(group) - WINDOW_SIZE + 1, STRIDE):
            end = start + WINDOW_SIZE
            window = group.iloc[start:end]

            row = {
                "window_id": window_id_global,
                "video_name": video_name,
                "video_window_id": window_id_in_video,
                "start_frame_idx": int(window.iloc[0]["frame_idx"]),
                "end_frame_idx": int(window.iloc[-1]["frame_idx"]),
                "frame_count": WINDOW_SIZE,
                "label": LABEL,
            }

            # GRU 입력: 60프레임 × 4피쳐 = 240개 값
            for t in range(WINDOW_SIZE):
                for feature_name in FEATURE_COLUMNS:
                    col_name = f"t{t:02d}_{feature_name}"
                    row[col_name] = float(window.iloc[t][feature_name])

            rows.append(row)

            window_id_global += 1
            window_id_in_video += 1

        print(
            f"[GRU 생성 완료] {video_name} | "
            f"유효 프레임 {len(group)}개, window {window_id_in_video}개"
        )

    return pd.DataFrame(rows)


# ============================================================
# 8. 전체 실행
# ============================================================

def main():
    video_files = find_video_files(VIDEO_DIR)

    if len(video_files) == 0:
        print("영상 파일이 없습니다.")
        print("확인 경로:", VIDEO_DIR)
        return

    if not os.path.exists(FACE_LANDMARKER_TASK):
        print("face_landmarker.task 파일을 찾을 수 없습니다.")
        print("확인 경로:", FACE_LANDMARKER_TASK)
        return

    print("총 영상 개수:", len(video_files))

    raw_dfs = []
    feature_dfs = []

    with create_face_landmarker() as landmarker:
        for idx, video_path in enumerate(video_files, start=1):
            print("=" * 70)
            print(f"[{idx}/{len(video_files)}] 처리 중: {video_path.name}")

            video_stem = safe_filename(video_path.name)

            # 1) raw blendshape 추출
            raw_df = extract_raw_blendshape_from_video(video_path, landmarker)

            if raw_df.empty:
                print(f"얼굴 인식 결과 없음: {video_path.name}")
                continue

            raw_csv_path = os.path.join(
                RAW_BLENDSHAPE_DIR,
                f"raw_blendshape_normal_{video_stem}.csv",
            )

            raw_df.to_csv(
                raw_csv_path,
                index=False,
                encoding="utf-8-sig",
            )

            raw_dfs.append(raw_df)

            # 2) 필요한 4개 feature로 변환
            feature_df = convert_raw_to_features(raw_df)

            feature_csv_path = os.path.join(
                FEATURE_DIR,
                f"feature_normal_{video_stem}.csv",
            )

            feature_df.to_csv(
                feature_csv_path,
                index=False,
                encoding="utf-8-sig",
            )

            feature_dfs.append(feature_df)

    if len(feature_dfs) == 0:
        print("생성된 feature CSV가 없습니다.")
        return

    # 전체 raw 병합 저장
    raw_all_df = pd.concat(raw_dfs, ignore_index=True)
    raw_all_path = os.path.join(RAW_BLENDSHAPE_DIR, "raw_blendshape_normal_all.csv")
    raw_all_df.to_csv(raw_all_path, index=False, encoding="utf-8-sig")

    # 전체 feature 병합 저장
    feature_all_df = pd.concat(feature_dfs, ignore_index=True)
    feature_all_path = os.path.join(FEATURE_DIR, "feature_normal_all.csv")
    feature_all_df.to_csv(feature_all_path, index=False, encoding="utf-8-sig")

    print("=" * 70)
    print("전체 feature 병합 완료")
    print("저장:", feature_all_path)

    # 3) 정상 feature 평균으로 baseline 계산
    baseline = calculate_baseline(feature_all_df)

    print("=" * 70)
    print("계산된 baseline")
    for k, v in baseline.items():
        print(f"{k}: {v:.6f}")

    save_baseline(baseline)

    # 4) baseline 기준으로 보정 CSV 생성
    calibrated_dfs = []

    for video_name, group in feature_all_df.groupby("video_name"):
        calibrated_df = apply_baseline_calibration(group, baseline)

        video_stem = safe_filename(video_name)

        calibrated_csv_path = os.path.join(
            CALIBRATED_DIR,
            f"calibrated_feature_normal_{video_stem}.csv",
        )

        calibrated_df.to_csv(
            calibrated_csv_path,
            index=False,
            encoding="utf-8-sig",
        )

        calibrated_dfs.append(calibrated_df)

    calibrated_all_df = pd.concat(calibrated_dfs, ignore_index=True)

    calibrated_all_path = os.path.join(
        CALIBRATED_DIR,
        "calibrated_feature_normal_all.csv",
    )

    calibrated_all_df.to_csv(
        calibrated_all_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("=" * 70)
    print("보정 feature CSV 저장 완료")
    print("저장:", calibrated_all_path)

    # 5) 60프레임 stride 5 기준 GRU window 생성
    gru_df = make_gru_windows(calibrated_all_df)

    if gru_df.empty:
        print("생성된 GRU window가 없습니다.")
        return

    gru_csv_path = os.path.join(
        GRU_DIR,
        "normal_GRU_window60_stride5.csv",
    )

    gru_df.to_csv(
        gru_csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("=" * 70)
    print("GRU CSV 생성 완료")
    print("저장:", gru_csv_path)
    print("GRU window 개수:", len(gru_df))
    print("GRU 입력 feature 수:", WINDOW_SIZE * len(FEATURE_COLUMNS))


if __name__ == "__main__":
    main()