import os
import pandas as pd


# ============================================================
# 1. 경로 설정
# ============================================================

NORMAL_GRU_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 정상\60프레임_stride_5\final_normal_GRU_window60_stride5.csv"

DROWSY_GRU_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 졸음\60프레임_stride_5\final_drowsy_GRU_window60_stride5.csv"

OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\최종 병합\60프레임_stride_5\final_GRU_window60_stride5.csv"


# ============================================================
# 2. CSV 로드 함수
# ============================================================

def load_gru_csv(csv_path, expected_label):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV 파일이 없습니다: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    print("\n로드 완료:", csv_path)
    print("shape:", df.shape)
    print("컬럼 개수:", len(df.columns))

    if "label" not in df.columns:
        raise ValueError(f"label 컬럼이 없습니다: {csv_path}")

    # 라벨을 확실하게 고정
    df["label"] = expected_label

    return df


# ============================================================
# 3. 컬럼 구조 확인 함수
# ============================================================

def check_and_align_columns(normal_df, drowsy_df):
    normal_cols = list(normal_df.columns)
    drowsy_cols = list(drowsy_df.columns)

    if normal_cols == drowsy_cols:
        print("\n컬럼 구조 확인 완료: 두 CSV의 컬럼이 동일합니다.")
        return normal_df, drowsy_df

    print("\n[경고] 두 CSV의 컬럼 순서 또는 이름이 다릅니다.")

    normal_set = set(normal_cols)
    drowsy_set = set(drowsy_cols)

    only_normal = normal_set - drowsy_set
    only_drowsy = drowsy_set - normal_set

    if only_normal:
        print("정상 CSV에만 있는 컬럼:", only_normal)

    if only_drowsy:
        print("졸음 CSV에만 있는 컬럼:", only_drowsy)

    # 컬럼 이름은 같고 순서만 다른 경우
    if normal_set == drowsy_set:
        print("컬럼 이름은 같지만 순서가 달라서 정상 CSV 기준으로 재정렬합니다.")
        drowsy_df = drowsy_df[normal_cols]
        return normal_df, drowsy_df

    raise ValueError("두 CSV의 컬럼 구성이 달라서 합칠 수 없습니다.")


# ============================================================
# 4. 메인 실행
# ============================================================

def main():
    # ------------------------------------------------------------
    # 1) CSV 로드
    # ------------------------------------------------------------
    normal_df = load_gru_csv(
        NORMAL_GRU_CSV,
        expected_label=0
    )

    drowsy_df = load_gru_csv(
        DROWSY_GRU_CSV,
        expected_label=1
    )

    # ------------------------------------------------------------
    # 2) 컬럼 구조 확인 및 정렬
    # ------------------------------------------------------------
    normal_df, drowsy_df = check_and_align_columns(
        normal_df,
        drowsy_df
    )

    # ------------------------------------------------------------
    # 3) 단순 병합
    # 정상 데이터가 먼저, 졸음 데이터가 뒤에 붙음
    # ------------------------------------------------------------
    merged_df = pd.concat(
        [normal_df, drowsy_df],
        axis=0,
        ignore_index=True
    )

    # ------------------------------------------------------------
    # 4) NaN 확인
    # ------------------------------------------------------------
    nan_count = merged_df.isna().sum().sum()

    if nan_count > 0:
        print(f"\n[경고] NaN 값이 총 {nan_count}개 있습니다.")
        print("NaN 포함 행은 제거하지 않고 그대로 저장합니다.")
    else:
        print("\nNaN 확인 완료: 결측값 없음")

    # ------------------------------------------------------------
    # 5) 저장 폴더 생성 후 저장
    # ------------------------------------------------------------
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    merged_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    # ------------------------------------------------------------
    # 6) 결과 출력
    # ------------------------------------------------------------
    print("\n============================================================")
    print("GRU CSV 단순 병합 완료")
    print("저장 위치:", OUTPUT_CSV)
    print("최종 shape:", merged_df.shape)
    print("컬럼 개수:", len(merged_df.columns))
    print("feature 컬럼 개수:", len(merged_df.columns) - 1)

    print("\n라벨 분포:")
    print(merged_df["label"].value_counts().sort_index())

    print("\n앞부분 미리보기:")
    print(merged_df.head())

    print("\n뒷부분 미리보기:")
    print(merged_df.tail())
    print("============================================================")


if __name__ == "__main__":
    main()