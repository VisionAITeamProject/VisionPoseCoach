import os
import pandas as pd


# ============================================================
# 0. 경로 설정
# ============================================================

NORMAL_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 정상\60프레임_stride_5\normal_GRU_window60_stride5.csv"
DROWSY_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\GRU 졸음\60프레임_stride_5\final_drowsy_GRU_window60_stride5.csv"

OUTPUT_DIR = r"C:\Users\KCCISTC\Desktop\csv(final)\최종 병합\60프레임_stride_5_1"
OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\최종 병합\60프레임_stride_5_1\final_GRU_window60_stride5.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# 1. 설정값
# ============================================================

WINDOW_SIZE = 60
FEATURE_SIZE = 4
TOTAL_FEATURE_COUNT = WINDOW_SIZE * FEATURE_SIZE  # 240
SEED = 42

# 입력 CSV에 컬럼명이 있을 경우 사용할 기존 컬럼명
INPUT_FEATURE_ORDER = [
    "leftEyeBlink",
    "rightEyeBlink",
    "eyeClosed",
    "jawOpen",
]

# 최종적으로 맞출 feature 순서
# 실제 저장할 때는 header=False라서 이 이름들은 저장되지 않음
OUTPUT_FEATURE_ORDER = [
    "왼쪽눈",
    "오른쪽눈",
    "양쪽눈",
    "턱",
]


# ============================================================
# 2. 최종 컬럼 순서 만들기
#    왼쪽눈0, 오른쪽눈0, 양쪽눈0, 턱0,
#    왼쪽눈1, 오른쪽눈1, 양쪽눈1, 턱1 ...
# ============================================================

output_feature_columns = []

for t in range(WINDOW_SIZE):
    for feature in OUTPUT_FEATURE_ORDER:
        output_feature_columns.append(f"{feature}{t}")

output_columns = output_feature_columns + ["label"]


# 입력 CSV가 t00_leftEyeBlink 형태일 때 찾을 컬럼명
input_named_columns = []

for t in range(WINDOW_SIZE):
    for feature in INPUT_FEATURE_ORDER:
        input_named_columns.append(f"t{t:02d}_{feature}")


# ============================================================
# 3. GRU CSV 정리 함수
# ============================================================

def prepare_gru_csv(csv_path, label_value):
    print("=" * 60)
    print("불러오는 파일:", csv_path)

    # --------------------------------------------------------
    # 1차 시도: 컬럼명이 있는 CSV인지 확인
    # --------------------------------------------------------
    df_header = pd.read_csv(
        csv_path,
        skip_blank_lines=True,
        low_memory=False
    )

    df_header = df_header.dropna(how="all").reset_index(drop=True)

    has_named_columns = all(col in df_header.columns for col in input_named_columns)

    if has_named_columns:
        print("컬럼명 있는 GRU CSV로 인식됨")

        df = df_header[input_named_columns].copy()

    else:
        # ----------------------------------------------------
        # 2차 시도: 컬럼명이 없는 CSV로 읽기
        # ----------------------------------------------------
        print("컬럼명 없음 또는 컬럼명 형식 다름")

        df_no_header = pd.read_csv(
            csv_path,
            header=None,
            skip_blank_lines=True,
            low_memory=False
        )

        # 완전히 비어 있는 행 제거
        df_no_header = df_no_header.dropna(how="all").reset_index(drop=True)

        print("header=None으로 읽은 shape:", df_no_header.shape)

        col_count = df_no_header.shape[1]

        # case 1: 240개 feature만 있는 경우
        if col_count == TOTAL_FEATURE_COUNT:
            print("240개 feature만 있는 CSV로 인식됨")
            df = df_no_header.iloc[:, :TOTAL_FEATURE_COUNT].copy()

        # case 2: 240개 feature + 기존 label = 241개인 경우
        elif col_count == TOTAL_FEATURE_COUNT + 1:
            print("240개 feature + 기존 label 포함 CSV로 인식됨")

            # 기존 label은 버리고, 우리가 지정한 label로 다시 고정
            df = df_no_header.iloc[:, :TOTAL_FEATURE_COUNT].copy()

        else:
            print("현재 CSV 컬럼 수:", col_count)
            print("예상 컬럼 수: 240 또는 241")
            raise ValueError(
                f"CSV 구조가 예상과 다릅니다. "
                f"현재 컬럼 수: {col_count}, 예상: 240 또는 241"
            )

    # --------------------------------------------------------
    # 최종 컬럼명 부여
    # 왼쪽눈0, 오른쪽눈0, 양쪽눈0, 턱0 ...
    # --------------------------------------------------------
    df.columns = output_feature_columns

    # --------------------------------------------------------
    # 숫자가 아닌 행 제거
    # 예: 잘못 들어간 header row, 빈 행, 깨진 행 제거
    # --------------------------------------------------------
    before_count = len(df)

    for col in output_feature_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=output_feature_columns).reset_index(drop=True)

    after_count = len(df)

    if before_count != after_count:
        print(f"제거된 비정상/빈 행 개수: {before_count - after_count}")

    # label 추가
    df["label"] = int(label_value)

    # 최종 컬럼 순서 고정
    df = df[output_columns]

    print("정리 후 shape:", df.shape)
    return df


# ============================================================
# 4. 정상 / 졸음 CSV 불러오기
# ============================================================

normal_df = prepare_gru_csv(NORMAL_CSV, label_value=0)
drowsy_df = prepare_gru_csv(DROWSY_CSV, label_value=1)

print("=" * 60)
print("원본 정상 개수:", len(normal_df))
print("원본 졸음 개수:", len(drowsy_df))


# ============================================================
# 5. 라벨별 5:5 비율 맞추기
# ============================================================

min_count = min(len(normal_df), len(drowsy_df))

if min_count == 0:
    raise ValueError("정상 또는 졸음 데이터 개수가 0개입니다. CSV 내용을 확인하세요.")

normal_balanced = normal_df.sample(
    n=min_count,
    random_state=SEED
).reset_index(drop=True)

drowsy_balanced = drowsy_df.sample(
    n=min_count,
    random_state=SEED
).reset_index(drop=True)

print("맞춘 정상 개수:", len(normal_balanced))
print("맞춘 졸음 개수:", len(drowsy_balanced))


# ============================================================
# 6. 병합
#    정상 데이터 다음에 졸음 데이터가 붙음
#    중간에 빈 행 없음
# ============================================================

merged_df = pd.concat(
    [normal_balanced, drowsy_balanced],
    ignore_index=True
)

# 혹시 모를 빈 행 최종 제거
merged_df = merged_df.dropna(how="all").reset_index(drop=True)

# 최종 컬럼 순서 다시 고정
merged_df = merged_df[output_columns]

print("=" * 60)
print("최종 병합 개수:", len(merged_df))
print("최종 shape:", merged_df.shape)

print("최종 라벨 개수 확인:")
print(merged_df["label"].value_counts().sort_index())


# ============================================================
# 7. 저장
#    header=False → 맨 위 feature명 제거
#    index=False  → 인덱스 제거
# ============================================================

merged_df.to_csv(
    OUTPUT_CSV,
    index=False,
    header=False,
    encoding="utf-8-sig",
    lineterminator="\n"
)

print("=" * 60)
print("최종 5:5 balanced GRU CSV 저장 완료")
print(OUTPUT_CSV)