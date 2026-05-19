import os
import csv
import json
import time

import numpy as np
import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

# label, ear_l, ear_r, ear_avg, jaw_open 형태의 CSV
INPUT_BLENDSHAPE_CSV = r"C:\Users\KCCISTC\Downloads\GRU 학습 new\JH\face_frame_features_only_add.csv"

OUTPUT_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)"
CALIBRATION_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)\보정값 저장소\정상"

NORMAL_4FEATURES_CSV = os.path.join(
    OUTPUT_DIR,
    "normal_4features_label0.csv"
)

CALIBRATION_CSV = os.path.join(
    CALIBRATION_DIR,
    "face_calibration_mean_from_normal.csv"
)

CALIBRATION_JSON = os.path.join(
    CALIBRATION_DIR,
    "face_calibration_mean_from_normal.json"
)

NORMAL_CALIBRATED_CSV = os.path.join(
    OUTPUT_DIR,
    "normal_4features_calibrated_label0.csv"
)

NORMAL_GRU_CSV = os.path.join(
    OUTPUT_DIR,
    "final_normal_GRU_window60_stride5.csv"
)


# ============================================================
# 2. 설정값
# ============================================================

NORMAL_LABEL = 0

WINDOW_SIZE = 60
STRIDE = 5

# 최종적으로 맞출 피쳐 이름
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

# 원본 CSV 컬럼명 → 우리가 쓰는 컬럼명
COLUMN_MAP = {
    "ear_l": "eyeBlinkLeft",
    "ear_r": "eyeBlinkRight",
    "ear_avg": "eyeClosed",
    "jaw_open": "jawOpen",
}


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


def make_gru_header():
    header = []

    for t in range(WINDOW_SIZE):
        for feature_name in FEATURE_COLUMNS:
            header.append(f"t{t:03d}_{feature_name}")

    header.append("label")

    return header


# ============================================================
# 4. label == 0 정상 데이터만 추출 + 컬럼명 변환
# ============================================================

def extract_normal_4features():
    if not os.path.exists(INPUT_BLENDSHAPE_CSV):
        raise FileNotFoundError(f"입력 CSV가 없습니다: {INPUT_BLENDSHAPE_CSV}")

    print("\n============================================================")
    print("1단계: label == 0 정상 데이터 추출")
    print("입력 CSV:", INPUT_BLENDSHAPE_CSV)
    print("============================================================")

    df = pd.read_csv(INPUT_BLENDSHAPE_CSV, encoding="utf-8-sig")

    print("원본 shape:", df.shape)
    print("원본 컬럼:", df.columns.tolist())

    required_cols = ["label", "ear_l", "ear_r", "ear_avg", "jaw_open"]

    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"필수 컬럼이 없습니다: {missing_cols}")

    df["label"] = pd.to_numeric(df["label"], errors="coerce")

    normal_df = df[df["label"] == NORMAL_LABEL].copy()
    normal_df = normal_df.reset_index(drop=True)

    if len(normal_df) == 0:
        raise ValueError("label == 0 인 정상 데이터가 없습니다.")

    # 컬럼명 변환
    converted_df = pd.DataFrame()

    for old_col, new_col in COLUMN_MAP.items():
        converted_df[new_col] = pd.to_numeric(
            normal_df[old_col],
            errors="coerce"
        )

    converted_df["label"] = NORMAL_LABEL

    before_drop = len(converted_df)
    converted_df = converted_df.dropna().reset_index(drop=True)
    after_drop = len(converted_df)

    if before_drop != after_drop:
        print(f"NaN 포함 행 제거: {before_drop - after_drop}개")

    converted_df = converted_df[FINAL_COLUMNS].copy()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    converted_df.to_csv(
        NORMAL_4FEATURES_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n정상 4피쳐 CSV 저장 완료")
    print("저장 위치:", NORMAL_4FEATURES_CSV)
    print("shape:", converted_df.shape)
    print("컬럼:", converted_df.columns.tolist())
    print("\n미리보기:")
    print(converted_df.head())

    return converted_df


# ============================================================
# 5. 정상 4개 피쳐 평균으로 보정값 계산 및 저장
# ============================================================

def make_and_save_calibration(normal_feature_df: pd.DataFrame):
    print("\n============================================================")
    print("2단계: 정상 데이터 평균으로 보정값 계산")
    print("============================================================")

    calibration = {}

    for col in FEATURE_COLUMNS:
        calibration[col] = float(normal_feature_df[col].astype(float).mean())

    os.makedirs(CALIBRATION_DIR, exist_ok=True)

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

    calibration_json_data = {
        "method": "label0_feature_mean",
        "description": "label==0 정상 데이터의 ear_l, ear_r, ear_avg, jaw_open 평균을 보정값으로 사용",
        "source_csv": INPUT_BLENDSHAPE_CSV,
        "normal_frame_count": int(len(normal_feature_df)),
        "column_mapping": COLUMN_MAP,
        "features": FEATURE_COLUMNS,
        "calibration": calibration,
    }

    with open(CALIBRATION_JSON, mode="w", encoding="utf-8") as f:
        json.dump(calibration_json_data, f, ensure_ascii=False, indent=4)

    print("보정값 CSV 저장 완료:", CALIBRATION_CSV)
    print("보정값 JSON 저장 완료:", CALIBRATION_JSON)

    print("\n보정값:")
    for key, value in calibration.items():
        print(f"{key}: {value:.8f}")

    return calibration


# ============================================================
# 6. 정상 데이터에 보정 적용
# ============================================================

def apply_calibration_to_normal(normal_feature_df: pd.DataFrame, calibration: dict):
    print("\n============================================================")
    print("3단계: 정상 데이터 보정 적용")
    print("============================================================")

    calibrated_df = normal_feature_df.copy()

    for col in FEATURE_COLUMNS:
        calibrated_df[col] = (
            calibrated_df[col].astype(float) - float(calibration[col])
        )

    calibrated_df["label"] = NORMAL_LABEL
    calibrated_df = calibrated_df[FINAL_COLUMNS].copy()

    calibrated_df.to_csv(
        NORMAL_CALIBRATED_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("보정된 정상 CSV 저장 완료")
    print("저장 위치:", NORMAL_CALIBRATED_CSV)
    print("shape:", calibrated_df.shape)
    print("\n미리보기:")
    print(calibrated_df.head())

    return calibrated_df


# ============================================================
# 7. 보정된 정상 데이터를 GRU 60프레임 stride 5 CSV로 변환
# ============================================================

def save_gru_window_csv(calibrated_df: pd.DataFrame):
    print("\n============================================================")
    print("4단계: GRU window CSV 생성")
    print("============================================================")

    feature_df = calibrated_df[FEATURE_COLUMNS].copy()

    for col in FEATURE_COLUMNS:
        feature_df[col] = pd.to_numeric(feature_df[col], errors="coerce")

    before_drop = len(feature_df)
    feature_df = feature_df.dropna().reset_index(drop=True)
    after_drop = len(feature_df)

    if before_drop != after_drop:
        print(f"NaN 포함 행 제거: {before_drop - after_drop}개")

    total_frames = len(feature_df)

    print("사용 가능한 정상 프레임 수:", total_frames)

    if total_frames < WINDOW_SIZE:
        raise ValueError(
            f"프레임 수가 부족합니다. 현재 {total_frames}개, "
            f"필요 최소 {WINDOW_SIZE}개"
        )

    total_windows = ((total_frames - WINDOW_SIZE) // STRIDE) + 1

    print("WINDOW_SIZE:", WINDOW_SIZE)
    print("STRIDE:", STRIDE)
    print("FEATURE 개수:", len(FEATURE_COLUMNS))
    print("한 window 피쳐 수:", WINDOW_SIZE * len(FEATURE_COLUMNS))
    print("생성될 window 개수:", total_windows)

    features = feature_df[FEATURE_COLUMNS].values.astype(np.float32)

    header = make_gru_header()

    start_time = time.time()
    saved_windows = 0

    with open(NORMAL_GRU_CSV, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for start_idx in range(0, total_frames - WINDOW_SIZE + 1, STRIDE):
            end_idx = start_idx + WINDOW_SIZE

            window = features[start_idx:end_idx]  # [60, 4]

            row = window.reshape(-1).tolist()     # [240]
            row.append(NORMAL_LABEL)

            writer.writerow(row)

            saved_windows += 1

            if saved_windows % 1000 == 0 or saved_windows == total_windows:
                elapsed = time.time() - start_time
                progress = saved_windows / total_windows
                remain = elapsed / progress - elapsed if progress > 0 else 0

                print(
                    f"\r진행률: {progress * 100:6.2f}% "
                    f"({saved_windows}/{total_windows}) | "
                    f"남은 시간: {format_time(remain)}",
                    end=""
                )

    print("\n\nGRU 정상 CSV 저장 완료")
    print("저장 위치:", NORMAL_GRU_CSV)
    print("최종 window 개수:", saved_windows)
    print("최종 shape 예상:", (saved_windows, WINDOW_SIZE * len(FEATURE_COLUMNS) + 1))


# ============================================================
# 8. 메인 실행
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CALIBRATION_DIR, exist_ok=True)

    normal_feature_df = extract_normal_4features()

    calibration = make_and_save_calibration(normal_feature_df)

    normal_calibrated_df = apply_calibration_to_normal(
        normal_feature_df,
        calibration
    )

    save_gru_window_csv(normal_calibrated_df)

    print("\n============================================================")
    print("전체 작업 완료")
    print("1. 정상 4피쳐 CSV:", NORMAL_4FEATURES_CSV)
    print("2. 보정값 CSV:", CALIBRATION_CSV)
    print("3. 보정값 JSON:", CALIBRATION_JSON)
    print("4. 보정된 정상 CSV:", NORMAL_CALIBRATED_CSV)
    print("5. 최종 정상 GRU CSV:", NORMAL_GRU_CSV)
    print("============================================================")


if __name__ == "__main__":
    main()