import os
import csv
import json
import time
from pathlib import Path

import cv2
import pandas as pd
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


# ============================================================
# 1. 경로 설정
# ============================================================

# 초기값 전용 정상 영상 폴더
INITIAL_VIDEO_DIR = r"C:\Users\KCCISTC\Desktop\정상\초기값 전용"

# 기존에 만들어둔 졸음 4피쳐 CSV
DROWSY_FEATURE_CSV = r"C:\Users\KCCISTC\Desktop\피곤\피곤_frame_4features_label1.csv"

# face_landmarker.task 경로
MODEL_PATH = r"C:\Users\KCCISTC\Desktop\VisionPoseCoach\WorkSpace\tasks\face_landmarker.task"

# 최종 저장 폴더
OUTPUT_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)"

# 저장 파일들
INITIAL_FEATURE_FRAME_CSV = os.path.join(
    OUTPUT_DIR,
    "initial_calibration_4features_frames.csv"
)

CALIBRATION_JSON = os.path.join(
    OUTPUT_DIR,
    "face_calibration_mean.json"
)

CALIBRATION_CSV = os.path.join(
    OUTPUT_DIR,
    "face_calibration_mean.csv"
)

FINAL_DROWSY_CALIBRATED_CSV = os.path.join(
    OUTPUT_DIR,
    "drowsy_4features_calibrated_label1.csv"
)


# ============================================================
# 2. 설정값
# ============================================================

DROWSY_LABEL = 1

FEATURE_COLUMNS = [
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeClosed",
    "jawOpen",
]

FINAL_COLUMNS = [
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeClosed",
    "jawOpen",
    "label",
]


# ============================================================
# 3. 유틸 함수
# ============================================================

def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


def get_video_files(video_dir: str):
    video_exts = [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"]

    video_files = []

    for path in Path(video_dir).rglob("*"):
        if path.suffix.lower() in video_exts:
            video_files.append(str(path))

    return sorted(video_files)


def create_face_landmarker():
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"face_landmarker.task 파일을 찾을 수 없습니다.\n"
            f"현재 설정된 경로: {MODEL_PATH}"
        )

    base_options = python.BaseOptions(model_asset_path=MODEL_PATH)

    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        output_face_blendshapes=True,
        num_faces=1,
    )

    return vision.FaceLandmarker.create_from_options(options)


# ============================================================
# 4. 초기값 전용 영상에서 4개 피쳐 추출
# ============================================================

def extract_initial_features_from_video(video_path: str):
    video_name = os.path.basename(video_path)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"\n[스킵] 영상을 열 수 없음: {video_path}")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        fps = 30.0

    frame_idx = 0
    saved_count = 0
    skipped_count = 0

    feature_rows = []

    start_time = time.time()

    print(f"\n처리 시작: {video_name}")
    print(f"총 프레임: {total_frames}, FPS: {fps:.2f}")

    # MediaPipe VIDEO 모드는 timestamp가 증가해야 하므로 영상마다 새로 생성
    with create_face_landmarker() as landmarker:
        while True:
            ret, frame = cap.read()

            if not ret:
                break

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb_frame,
            )

            timestamp_ms = int((frame_idx / fps) * 1000)

            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            if result.face_blendshapes and len(result.face_blendshapes) > 0:
                blendshape_dict = {
                    item.category_name: item.score
                    for item in result.face_blendshapes[0]
                }

                eye_blink_left = float(blendshape_dict.get("eyeBlinkLeft", 0.0))
                eye_blink_right = float(blendshape_dict.get("eyeBlinkRight", 0.0))
                jaw_open = float(blendshape_dict.get("jawOpen", 0.0))

                eye_closed = (eye_blink_left + eye_blink_right) / 2.0

                feature_rows.append({
                    "eyeBlinkLeft": eye_blink_left,
                    "eyeBlinkRight": eye_blink_right,
                    "eyeClosed": eye_closed,
                    "jawOpen": jaw_open,
                })

                saved_count += 1

            else:
                skipped_count += 1

            frame_idx += 1

            if total_frames > 0 and (frame_idx % 30 == 0 or frame_idx == total_frames):
                elapsed = time.time() - start_time
                progress = frame_idx / total_frames
                remain = elapsed / progress - elapsed if progress > 0 else 0

                print(
                    f"\r진행률: {progress * 100:6.2f}% "
                    f"({frame_idx}/{total_frames}) | "
                    f"저장: {saved_count} | "
                    f"스킵: {skipped_count} | "
                    f"남은 시간: {format_time(remain)}",
                    end="",
                )

    cap.release()

    print()
    print(f"완료: {video_name}")
    print(f"저장 프레임: {saved_count}, 얼굴 미인식 스킵: {skipped_count}")

    return feature_rows


def extract_initial_calibration_features():
    video_files = get_video_files(INITIAL_VIDEO_DIR)

    if len(video_files) == 0:
        raise FileNotFoundError(
            f"초기값 전용 영상 폴더에 영상이 없습니다: {INITIAL_VIDEO_DIR}"
        )

    print("\n============================================================")
    print("초기값 전용 영상 4개 피쳐 추출 시작")
    print(f"입력 폴더: {INITIAL_VIDEO_DIR}")
    print(f"찾은 영상 개수: {len(video_files)}")
    print("============================================================")

    all_rows = []

    whole_start = time.time()

    for idx, video_path in enumerate(video_files, start=1):
        print(f"\n[{idx}/{len(video_files)}]")

        rows = extract_initial_features_from_video(video_path)
        all_rows.extend(rows)

        elapsed = time.time() - whole_start
        avg_per_file = elapsed / idx
        remain_files = len(video_files) - idx
        remain_time = avg_per_file * remain_files

        print(
            f"전체 진행: {idx}/{len(video_files)} | "
            f"누적 피쳐 프레임: {len(all_rows)} | "
            f"전체 남은 예상 시간: {format_time(remain_time)}"
        )

    if len(all_rows) == 0:
        raise RuntimeError("초기값 전용 영상에서 얼굴 인식된 프레임이 없습니다.")

    initial_df = pd.DataFrame(all_rows, columns=FEATURE_COLUMNS)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    initial_df.to_csv(
        INITIAL_FEATURE_FRAME_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n초기값 전용 4피쳐 프레임 CSV 저장 완료")
    print("저장 위치:", INITIAL_FEATURE_FRAME_CSV)
    print("shape:", initial_df.shape)

    return initial_df


# ============================================================
# 5. 캘리브레이션 평균값 저장
# ============================================================

def make_and_save_calibration(initial_df: pd.DataFrame):
    calibration = {}

    for col in FEATURE_COLUMNS:
        calibration[col] = float(initial_df[col].astype(float).mean())

    calibration_json_data = {
        "method": "initial_video_feature_mean",
        "description": "초기값 전용 정상 영상에서 추출한 4개 피쳐 평균값",
        "source_video_dir": INITIAL_VIDEO_DIR,
        "frame_count": int(len(initial_df)),
        "features": FEATURE_COLUMNS,
        "calibration": calibration,
    }

    with open(CALIBRATION_JSON, mode="w", encoding="utf-8") as f:
        json.dump(calibration_json_data, f, ensure_ascii=False, indent=4)

    calibration_df = pd.DataFrame([
        {
            "feature": feature_name,
            "calibration_mean": calibration[feature_name],
        }
        for feature_name in FEATURE_COLUMNS
    ])

    calibration_df.to_csv(
        CALIBRATION_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n캘리브레이션 값 저장 완료")
    print("JSON 저장 위치:", CALIBRATION_JSON)
    print("CSV 저장 위치:", CALIBRATION_CSV)

    print("\n캘리브레이션 평균값:")
    for key, value in calibration.items():
        print(f"{key}: {value:.8f}")

    return calibration


# ============================================================
# 6. 기존 졸음 4피쳐 CSV에 보정 적용
# ============================================================

def apply_calibration_to_drowsy_csv(calibration: dict):
    if not os.path.exists(DROWSY_FEATURE_CSV):
        raise FileNotFoundError(f"졸음 4피쳐 CSV가 없습니다: {DROWSY_FEATURE_CSV}")

    df = pd.read_csv(DROWSY_FEATURE_CSV, encoding="utf-8-sig")

    print("\n============================================================")
    print("졸음 CSV 보정 시작")
    print("입력 CSV:", DROWSY_FEATURE_CSV)
    print("원본 shape:", df.shape)
    print("============================================================")

    required_base_cols = [
        "eyeBlinkLeft",
        "eyeBlinkRight",
        "jawOpen",
    ]

    missing_cols = [col for col in required_base_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"졸음 CSV에 필수 컬럼이 없습니다: {missing_cols}")

    df["eyeBlinkLeft"] = df["eyeBlinkLeft"].astype(float)
    df["eyeBlinkRight"] = df["eyeBlinkRight"].astype(float)
    df["jawOpen"] = df["jawOpen"].astype(float)

    # eyeClosed가 없으면 새로 계산
    if "eyeClosed" not in df.columns:
        df["eyeClosed"] = (
            df["eyeBlinkLeft"] + df["eyeBlinkRight"]
        ) / 2.0
    else:
        df["eyeClosed"] = df["eyeClosed"].astype(float)

    calibrated_df = df.copy()

    # 핵심 보정:
    # 보정된 값 = 현재 피쳐값 - 초기값 전용 정상 영상 평균
    for col in FEATURE_COLUMNS:
        calibrated_df[col] = calibrated_df[col] - float(calibration[col])

    # 졸음 CSV이므로 label은 1로 고정
    calibrated_df["label"] = DROWSY_LABEL

    calibrated_df = calibrated_df[FINAL_COLUMNS].copy()

    calibrated_df.to_csv(
        FINAL_DROWSY_CALIBRATED_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n졸음 보정 CSV 저장 완료")
    print("저장 위치:", FINAL_DROWSY_CALIBRATED_CSV)
    print("최종 shape:", calibrated_df.shape)
    print("최종 컬럼:", calibrated_df.columns.tolist())
    print("\n라벨 분포:")
    print(calibrated_df["label"].value_counts().sort_index())

    print("\n미리보기:")
    print(calibrated_df.head())

    return calibrated_df


# ============================================================
# 7. 메인 실행
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    initial_df = extract_initial_calibration_features()

    calibration = make_and_save_calibration(initial_df)

    apply_calibration_to_drowsy_csv(calibration)

    print("\n============================================================")
    print("전체 작업 완료")
    print("보정값 JSON:", CALIBRATION_JSON)
    print("보정값 CSV:", CALIBRATION_CSV)
    print("최종 졸음 보정 CSV:", FINAL_DROWSY_CALIBRATED_CSV)
    print("============================================================")


if __name__ == "__main__":
    main()