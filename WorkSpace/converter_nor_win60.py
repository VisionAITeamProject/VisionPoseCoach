import os
import pandas as pd


# ============================================================
# 0. 경로 설정
# ============================================================

INPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 정상\60프레임_stride_5\normal_GRU_window60_stride5.csv"

OUTPUT_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 정상\60프레임_stride_5_변환"
OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 정상\60프레임_stride_5_변환\normal_GRU_window60_stride5_reordered.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# 1. 설정값
# ============================================================

WINDOW_SIZE = 60

FEATURE_ORDER = [
    "leftEyeBlink",
    "rightEyeBlink",
    "eyeClosed",
    "jawOpen"
]


# ============================================================
# 2. 원하는 feature 컬럼 순서 만들기
# ============================================================

feature_columns = []

for t in range(WINDOW_SIZE):
    for feature_name in FEATURE_ORDER:
        col_name = f"t{t:02d}_{feature_name}"
        feature_columns.append(col_name)


# ============================================================
# 3. CSV 불러오기
# ============================================================

df = pd.read_csv(INPUT_CSV, low_memory=False)

print("원본 shape:", df.shape)
print("원본 앞쪽 컬럼:")
print(df.columns[:10].tolist())


# ============================================================
# 4. 필요한 컬럼 존재 확인
# ============================================================

missing_cols = []

for col in feature_columns:
    if col not in df.columns:
        missing_cols.append(col)

if "label" not in df.columns:
    missing_cols.append("label")

if missing_cols:
    print("누락된 컬럼이 있습니다:")
    for col in missing_cols:
        print("-", col)
    raise ValueError("필요한 컬럼이 누락되어 변환을 중단합니다.")


# ============================================================
# 5. feature 240개 + label 구조로 재정렬
# ============================================================

output_columns = feature_columns + ["label"]

df_reordered = df[output_columns].copy()


# ============================================================
# 6. 저장
# ============================================================

df_reordered.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

print("변환 완료")
print("저장 위치:", OUTPUT_CSV)
print("변환 후 shape:", df_reordered.shape)
print("변환 후 앞쪽 컬럼:")
print(df_reordered.columns[:10].tolist())
print("변환 후 마지막 컬럼:")
print(df_reordered.columns[-5:].tolist())