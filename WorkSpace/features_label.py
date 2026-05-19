import os
import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

INPUT_CSV = r"C:\Users\KCCISTC\Desktop\피곤\피곤_raw_blendshape_label1.csv"

OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\피곤\피곤_frame_4features_label1.csv"

DEFAULT_LABEL = 1


# ============================================================
# 2. CSV 로드
# ============================================================

df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

print("원본 CSV shape:", df.shape)
print("원본 컬럼:")
print(df.columns.tolist())


# ============================================================
# 3. 필요한 컬럼 확인
# ============================================================

required_cols = [
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "jawOpen",
]

missing_cols = [col for col in required_cols if col not in df.columns]

if missing_cols:
    raise ValueError(f"필수 컬럼이 없습니다: {missing_cols}")


# ============================================================
# 4. eyeClosed 계산
# ============================================================

df["eyeClosed"] = (
    df["eyeBlinkLeft"].astype(float) + df["eyeBlinkRight"].astype(float)
) / 2.0


# ============================================================
# 5. label 처리
# ============================================================

if "label" not in df.columns:
    df["label"] = DEFAULT_LABEL
else:
    df["label"] = df["label"].fillna(DEFAULT_LABEL).astype(int)


# ============================================================
# 6. 최종 4개 feature + label만 추출
# ============================================================

final_df = df[
    [
        "eyeBlinkLeft",
        "eyeBlinkRight",
        "eyeClosed",
        "jawOpen",
        "label",
    ]
].copy()


# ============================================================
# 7. 저장
# ============================================================

os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

final_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")


# ============================================================
# 8. 결과 확인
# ============================================================

print("\n저장 완료")
print("저장 위치:", OUTPUT_CSV)
print("최종 CSV shape:", final_df.shape)
print("최종 컬럼:")
print(final_df.columns.tolist())

print("\n미리보기:")
print(final_df.head())