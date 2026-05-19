import os
import csv
import time

import pandas as pd
import numpy as np


# ============================================================
# 1. 경로 설정
# ============================================================

INPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\졸음 보정값\final_drowsy_4features_calibrated_merged.csv"

OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 졸음\final_drowsy_GRU_window60_stride5.csv"


# ============================================================
# 2. GRU 설정
# ============================================================

WINDOW_SIZE = 60
STRIDE = 5
DROWSY_LABEL = 1

FEATURE_COLUMNS = [
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeClosed",
    "jawOpen",
]


# ============================================================
# 3. 헤더 생성
# ============================================================

def make_gru_header():
    header = []

    for t in range(WINDOW_SIZE):
        for feature_name in FEATURE_COLUMNS:
            header.append(f"t{t:03d}_{feature_name}")

    header.append("label")

    return header


# ============================================================
# 4. 시간 표시 함수
# ============================================================

def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


# ============================================================
# 5. GRU window CSV 생성
# ============================================================

def main():
    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"입력 CSV가 없습니다: {INPUT_CSV}")

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    print("입력 CSV 로드 중...")
    print("입력:", INPUT_CSV)

    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    print("원본 shape:", df.shape)
    print("원본 컬럼:", df.columns.tolist())

    # ------------------------------------------------------------
    # 필수 컬럼 확인
    # ------------------------------------------------------------
    missing_cols = [col for col in FEATURE_COLUMNS if col not in df.columns]

    if missing_cols:
        raise ValueError(f"필수 피쳐 컬럼이 없습니다: {missing_cols}")

    # ------------------------------------------------------------
    # 필요한 컬럼만 사용
    # ------------------------------------------------------------
    feature_df = df[FEATURE_COLUMNS].copy()

    for col in FEATURE_COLUMNS:
        feature_df[col] = pd.to_numeric(feature_df[col], errors="coerce")

    before_drop = len(feature_df)

    # NaN 제거
    feature_df = feature_df.dropna().reset_index(drop=True)

    after_drop = len(feature_df)

    if before_drop != after_drop:
        print(f"NaN 포함 행 제거: {before_drop - after_drop}개")

    total_frames = len(feature_df)

    print("사용 가능한 프레임 수:", total_frames)

    if total_frames < WINDOW_SIZE:
        raise ValueError(
            f"프레임 수가 부족합니다. 현재 {total_frames}개, "
            f"필요 최소 {WINDOW_SIZE}개"
        )

    # ------------------------------------------------------------
    # 예상 window 개수
    # ------------------------------------------------------------
    total_windows = ((total_frames - WINDOW_SIZE) // STRIDE) + 1

    print("\nGRU 변환 설정")
    print("WINDOW_SIZE:", WINDOW_SIZE)
    print("STRIDE:", STRIDE)
    print("FEATURE 개수:", len(FEATURE_COLUMNS))
    print("한 window당 피쳐 수:", WINDOW_SIZE * len(FEATURE_COLUMNS))
    print("생성될 window 개수:", total_windows)

    features = feature_df[FEATURE_COLUMNS].values.astype(np.float32)

    header = make_gru_header()

    start_time = time.time()
    saved_windows = 0

    with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for window_id, start_idx in enumerate(range(0, total_frames - WINDOW_SIZE + 1, STRIDE)):
            end_idx = start_idx + WINDOW_SIZE

            window = features[start_idx:end_idx]

            # [60, 4] -> [240]
            row = window.reshape(-1).tolist()

            # label은 맨 마지막
            row.append(DROWSY_LABEL)

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

    print("\n\nGRU CSV 저장 완료")
    print("저장 위치:", OUTPUT_CSV)
    print("최종 window 개수:", saved_windows)
    print("최종 CSV 구조:")
    print(f"{WINDOW_SIZE}프레임 × {len(FEATURE_COLUMNS)}피쳐 = {WINDOW_SIZE * len(FEATURE_COLUMNS)}개 + label")
    print("최종 shape 예상:", (saved_windows, WINDOW_SIZE * len(FEATURE_COLUMNS) + 1))


if __name__ == "__main__":
    main()