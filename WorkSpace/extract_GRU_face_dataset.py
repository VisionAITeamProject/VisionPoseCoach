import pandas as pd
import numpy as np
import os

# =====================================================================
# ⚙️ 하이퍼파라미터 설정 (이 부분만 수정하시면 됩니다)
# =====================================================================
WINDOW_SIZE = 60
STRIDE_DROWSY = 5
OUTPUT_CSV = r"C:\Users\KCCISTC\Desktop\csv(final)\최종 병합\60프레임_stride_5\final_GRU_window60_stride5.csv"

# 파일 경로 설정
DROWSY_ORIG_PATH = r"C:\Users\KCCISTC\Desktop\csv(final)\졸음 feature 저장\drowsy_4features_calibrated_label1.csv"
DROWSY_FLIP_PATH = r"C:\Users\KCCISTC\Desktop\csv(final)\졸음 feature 저장\drowsy_flipped_4features_calibrated_label1.csv"
OPENSOURCE_PATH = r"C:\Users\KCCISTC\Desktop\csv(final)\정상 보정값\normal_4features_calibrated_label0.csv"

# 두 데이터셋의 공통 피처 컬럼명 (순서 일치)
FEATURE_COLS = ['eyeBlinkLeft', 'eyeBlinkRight', 'eyeClosed', 'jawOpen']

# =====================================================================
# 1. 졸음(Drowsy, 라벨 1) 데이터 처리
# =====================================================================
print("🔄 졸음 데이터 로드 및 시퀀스 변환 중...")

if os.path.exists(DROWSY_ORIG_PATH) and os.path.exists(DROWSY_FLIP_PATH):
    # 졸음 데이터 로드 및 병합
    df_drowsy_orig = pd.read_csv(DROWSY_ORIG_PATH)
    df_drowsy_flip = pd.read_csv(DROWSY_FLIP_PATH)
    df_drowsy_all = pd.concat([df_drowsy_orig, df_drowsy_flip], ignore_index=True)
else:
    raise FileNotFoundError("❌ 졸음 데이터셋 파일 경로를 확인해주세요.")

# 졸음 데이터 슬라이딩 윈도우 생성
drowsy_samples = []
num_drowsy_frames = len(df_drowsy_all)

for idx in range(0, num_drowsy_frames - WINDOW_SIZE + 1, STRIDE_DROWSY):
    window = df_drowsy_all.iloc[idx : idx + WINDOW_SIZE]
    window_features = window[FEATURE_COLS].values
    flattened = window_features.flatten()
    drowsy_samples.append(np.append(flattened, 1)) # 졸음 라벨 1 추가

total_drowsy_count = len(drowsy_samples)
print(f"✅ 졸음(1) 샘플 생성 완료: {total_drowsy_count:,} 개")


# =====================================================================
# 2. 정상(Normal, 라벨 0) 데이터 처리 & 1:1 매칭
# =====================================================================
print("\n🔄 오픈소스 데이터에서 정상(0) 데이터 추출 및 1:1 비율 맞춤 중...")

if os.path.exists(OPENSOURCE_PATH):
    # 오픈소스 데이터 로드 (이제 졸음 데이터와 컬럼 순서가 동일함)
    df_open = pd.read_csv(OPENSOURCE_PATH)
else:
    raise FileNotFoundError(f"❌ 오픈소스 파일이 없습니다: {OPENSOURCE_PATH}")

# 라벨이 0인 정상 프레임만 필터링
df_normal = df_open[df_open['label'] == 0].reset_index(drop=True)
num_normal_frames = len(df_normal)

# 1:1 균형을 위한 정상 데이터용 Stride 자동 계산
if total_drowsy_count > 0:
    stride_normal = max(1, int((num_normal_frames - WINDOW_SIZE) / total_drowsy_count))
    print(f"📊 1:1 균형을 위한 정상 데이터 Stride 자동 계산값: {stride_normal}")
else:
    raise ValueError("❌ 생성된 졸음 데이터가 0개입니다. 졸음 CSV 파일을 확인해주세요.")

normal_samples = []
idx = 0

# 계산된 스트라이드로 정상 데이터 윈도우 추출
while idx <= num_normal_frames - WINDOW_SIZE and len(normal_samples) < total_drowsy_count:
    window = df_normal.iloc[idx : idx + WINDOW_SIZE]
    window_features = window[FEATURE_COLS].values
    flattened = window_features.flatten()
    normal_samples.append(np.append(flattened, 0)) # 정상 라벨 0 추가
    idx += stride_normal

# 최종 개수 경계 정제 (Trimming)
normal_samples = normal_samples[:total_drowsy_count]
print(f"✅ 정상(0) 샘플 생성 완료: {len(normal_samples):,} 개")


# =====================================================================
# 3. 데이터셋 통합 및 최종 저장
# =====================================================================
print("\n💾 데이터셋 통합 및 최종 셔플 작업 중...")

final_dataset = drowsy_samples + normal_samples

# 저장용 컬럼명 자동 생성 (ebL_t1, ebR_t1, ebClosed_t1, jaw_t1 ... label)
cols = []
for t in range(1, WINDOW_SIZE + 1):
    cols.extend([f"ebL_t{t}", f"ebR_t{t}", f"ebClosed_t{t}", f"jaw_t{t}"])
cols.append("label")

df_final = pd.DataFrame(final_dataset, columns=cols)

# 모델이 편향되지 않도록 데이터 무작위 셔플
df_final = df_final.sample(frac=1, random_state=42).reset_index(drop=True)

df_final.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

print("=" * 60)
print(f"✨ GRU 학습용 데이터셋 정제 완료 (열 순서 일치 버젼)!")
print(f"📁 파일 저장 위치: {os.path.abspath(OUTPUT_CSV)}")
print(f"📊 최종 데이터셋 전체 행 수: {len(df_final):,} rows")
print(f"🟢 Normal (0) 시퀀스 수: {len(df_final[df_final['label']==0]):,} sets")
print(f"🔴 Drowsy (1) 시퀀스 수: {len(df_final[df_final['label']==1]):,} sets")
print("=" * 60)