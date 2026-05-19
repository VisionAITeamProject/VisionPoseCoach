import os
import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

# 좌우반전한 졸음 4피쳐 CSV
FLIPPED_DROWSY_CSV = r"C:\Users\KCCISTC\Desktop\피곤\face_features_only_drowsy_flipped_frame_only.csv"

# 기존에 이미 보정 완료된 졸음 CSV
ORIGINAL_CALIBRATED_DROWSY_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\drowsy_4features_calibrated_label1.csv"

# 기존 보정값 CSV
CALIBRATION_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\보정값 저장소\face_calibration_mean.csv"

# 최종 저장 폴더
OUTPUT_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)"

# 좌우반전 CSV에 보정 적용한 중간 결과
FLIPPED_CALIBRATED_DROWSY_CSV = os.path.join(
    OUTPUT_DIR,
    "drowsy_flipped_4features_calibrated_label1.csv"
)

# 최종 졸음 CSV
FINAL_DROWSY_CSV = os.path.join(
    OUTPUT_DIR,
    "final_drowsy_4features_calibrated_merged.csv"
)


# ============================================================
# 2. 설정
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


# 좌우반전 CSV의 컬럼명 → 기존 피쳐명
FLIPPED_COLUMN_MAP = {
    "ear_l": "eyeBlinkLeft",
    "ear_r": "eyeBlinkRight",
    "ear_avg": "eyeClosed",
    "jaw_open": "jawOpen",
}


# ============================================================
# 3. 보정값 불러오기
# ============================================================

def load_calibration_mean(calibration_csv_path):
    if not os.path.exists(calibration_csv_path):
        raise FileNotFoundError(f"보정값 CSV가 없습니다: {calibration_csv_path}")

    cal_df = pd.read_csv(calibration_csv_path, encoding="utf-8-sig")

    print("보정값 CSV 컬럼:", cal_df.columns.tolist())
    print(cal_df)

    required_cols = ["feature", "calibration_mean"]

    missing_cols = [col for col in required_cols if col not in cal_df.columns]

    if missing_cols:
        raise ValueError(f"보정값 CSV에 필요한 컬럼이 없습니다: {missing_cols}")

    calibration = {}

    for _, row in cal_df.iterrows():
        feature_name = str(row["feature"])
        calibration_mean = float(row["calibration_mean"])
        calibration[feature_name] = calibration_mean

    missing_features = [col for col in FEATURE_COLUMNS if col not in calibration]

    if missing_features:
        raise ValueError(f"보정값에 없는 피쳐가 있습니다: {missing_features}")

    print("\n불러온 보정값:")
    for key in FEATURE_COLUMNS:
        print(f"{key}: {calibration[key]:.8f}")

    return calibration


# ============================================================
# 4. 좌우반전 졸음 CSV 컬럼명 변환
# ============================================================

def load_and_convert_flipped_drowsy_csv(flipped_csv_path):
    if not os.path.exists(flipped_csv_path):
        raise FileNotFoundError(f"좌우반전 졸음 CSV가 없습니다: {flipped_csv_path}")

    df = pd.read_csv(flipped_csv_path, encoding="utf-8-sig")

    print("\n좌우반전 CSV 원본 shape:", df.shape)
    print("좌우반전 CSV 원본 컬럼:", df.columns.tolist())

    missing_cols = [col for col in FLIPPED_COLUMN_MAP.keys() if col not in df.columns]

    if missing_cols:
        raise ValueError(f"좌우반전 CSV에 필요한 컬럼이 없습니다: {missing_cols}")

    converted_df = pd.DataFrame()

    for old_col, new_col in FLIPPED_COLUMN_MAP.items():
        converted_df[new_col] = df[old_col].astype(float)

    converted_df["label"] = DROWSY_LABEL

    converted_df = converted_df[FINAL_COLUMNS].copy()

    print("\n좌우반전 CSV 변환 후 shape:", converted_df.shape)
    print("변환 후 컬럼:", converted_df.columns.tolist())
    print(converted_df.head())

    return converted_df


# ============================================================
# 5. 보정 적용
# ============================================================

def apply_calibration(df, calibration):
    calibrated_df = df.copy()

    for col in FEATURE_COLUMNS:
        calibrated_df[col] = calibrated_df[col].astype(float) - float(calibration[col])

    calibrated_df["label"] = DROWSY_LABEL

    return calibrated_df[FINAL_COLUMNS].copy()


# ============================================================
# 6. 기존 보정 완료 졸음 CSV 로드
# ============================================================

def load_original_calibrated_drowsy_csv(csv_path):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"기존 보정 완료 졸음 CSV가 없습니다: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    print("\n기존 보정 완료 졸음 CSV shape:", df.shape)
    print("기존 보정 완료 졸음 CSV 컬럼:", df.columns.tolist())

    missing_cols = [col for col in FINAL_COLUMNS if col not in df.columns]

    if missing_cols:
        raise ValueError(f"기존 졸음 CSV에 필요한 컬럼이 없습니다: {missing_cols}")

    final_df = df[FINAL_COLUMNS].copy()

    for col in FEATURE_COLUMNS:
        final_df[col] = final_df[col].astype(float)

    final_df["label"] = DROWSY_LABEL

    return final_df


# ============================================================
# 7. 메인 실행
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1) 보정값 로드
    calibration = load_calibration_mean(CALIBRATION_CSV)

    # 2) 좌우반전 CSV 로드 후 기존 4피쳐명으로 변환
    flipped_df = load_and_convert_flipped_drowsy_csv(FLIPPED_DROWSY_CSV)

    # 3) 좌우반전 CSV에 보정 적용
    flipped_calibrated_df = apply_calibration(flipped_df, calibration)

    flipped_calibrated_df.to_csv(
        FLIPPED_CALIBRATED_DROWSY_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n좌우반전 보정 CSV 저장 완료")
    print("저장 위치:", FLIPPED_CALIBRATED_DROWSY_CSV)
    print("shape:", flipped_calibrated_df.shape)
    print(flipped_calibrated_df.head())

    # 4) 기존 보정 완료 졸음 CSV 로드
    original_calibrated_df = load_original_calibrated_drowsy_csv(
        ORIGINAL_CALIBRATED_DROWSY_CSV
    )

    # 5) 기존 졸음 + 좌우반전 졸음 합치기
    final_drowsy_df = pd.concat(
        [
            original_calibrated_df,
            flipped_calibrated_df,
        ],
        axis=0,
        ignore_index=True,
    )

    final_drowsy_df = final_drowsy_df[FINAL_COLUMNS].copy()

    final_drowsy_df.to_csv(
        FINAL_DROWSY_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n============================================================")
    print("최종 졸음 CSV 저장 완료")
    print("저장 위치:", FINAL_DROWSY_CSV)
    print("최종 shape:", final_drowsy_df.shape)
    print("라벨 분포:")
    print(final_drowsy_df["label"].value_counts().sort_index())
    print("============================================================")

    print("\n최종 미리보기:")
    print(final_drowsy_df.head())


if __name__ == "__main__":
    main()