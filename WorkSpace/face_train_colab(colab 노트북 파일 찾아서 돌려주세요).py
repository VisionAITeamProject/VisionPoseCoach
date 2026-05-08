# ============================================================
# 0. 라이브러리 설치 및 import
# ============================================================

!pip install -q joblib

import os
import json
import random
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from google.colab import files

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_score,
    recall_score,
    f1_score
)
from sklearn.utils.class_weight import compute_class_weight

import tensorflow as tf
from tensorflow.keras import layers, models, callbacks, regularizers


# ============================================================
# 1. 랜덤 시드 고정
# ============================================================

SEED = 42

random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

# ============================================================
# 2. CSV 업로드
# ============================================================

uploaded = files.upload()

csv_path = list(uploaded.keys())[0]
print("업로드된 CSV:", csv_path)

df = pd.read_csv(csv_path)

print("CSV 크기:", df.shape)
display(df.head())

print("\n라벨 분포")
print(df["label"].value_counts())

# ============================================================
# 3. 기본 설정
# ============================================================

TARGET_COL = "label"

LABEL_MAP = {
    "normal": 0,
    "drowsy": 1
}

INV_LABEL_MAP = {
    0: "normal",
    1: "drowsy"
}

# 라벨 숫자로 변환
df["target"] = df[TARGET_COL].map(LABEL_MAP)

if df["target"].isna().any():
    raise ValueError("label 컬럼에 normal 또는 drowsy 이외의 값이 있습니다.")

print("라벨 변환 확인")
display(df[[TARGET_COL, "target"]].head())

# ============================================================
# 4. 학습에서 제외할 컬럼 지정
# ============================================================
# 중요:
# 아래 컬럼들은 모델이 졸음 특징을 배우는 데 필요한 값이 아니라
# 영상 이름, 시간, 프레임 위치 같은 메타데이터이다.
#
# 이런 값을 학습에 넣으면 모델이 실제 졸음 패턴이 아니라
# 데이터셋 구조를 외울 위험이 있다.

DROP_COLS = [
    "video_name",
    "label",
    "target",

    # window 위치 정보
    "window_id",
    "start_sec",
    "end_sec",
    "window_duration_sec",

    # 프레임 / 샘플 인덱스 정보
    "start_frame_idx",
    "end_frame_idx",
    "start_sample_idx",
    "end_sample_idx",
    "frame_count"
]

# 실제 존재하는 컬럼만 제거
drop_cols_existing = [col for col in DROP_COLS if col in df.columns]

# 숫자형 컬럼만 feature 후보로 사용
feature_cols = [
    col for col in df.columns
    if col not in drop_cols_existing
    and pd.api.types.is_numeric_dtype(df[col])
]

X_df = df[feature_cols].copy()

# inf, NaN 처리
X_df = X_df.replace([np.inf, -np.inf], np.nan)
X_df = X_df.fillna(0)

# 모든 값이 같은 컬럼 제거
# 예: 모든 window에서 yawn_count가 0이면 학습 정보가 없으므로 제거
constant_cols = [
    col for col in X_df.columns
    if X_df[col].nunique() <= 1
]

X_df = X_df.drop(columns=constant_cols)

feature_cols = X_df.columns.tolist()

X = X_df.values.astype(np.float32)
y = df["target"].values.astype(np.int32)

print("최종 feature 수:", len(feature_cols))
print("제거된 상수 컬럼 수:", len(constant_cols))
print("X shape:", X.shape)
print("y shape:", y.shape)

print("\n사용 feature 목록")
for col in feature_cols:
    print("-", col)

# ============================================================
# 5. 학습 / 검증 / 테스트 데이터 분리
# ============================================================
# 전체 데이터를 다음과 같이 나눈다.
#
# train : 실제 학습용
# val   : 학습 중 성능 확인, threshold 결정용
# test  : 최종 성능 평가용
#
# 권장 비율:
# train 64%
# val   16%
# test  20%

label_counts = pd.Series(y).value_counts()
print("클래스별 개수")
print(label_counts)

min_class_count = label_counts.min()

if min_class_count < 5:
    print("\n[주의] 클래스별 데이터가 너무 적습니다.")
    print("현재 코드는 실행은 가능하지만, 실제 성능 평가는 신뢰하기 어렵습니다.")
    print("나중에 window 수를 충분히 늘린 뒤 이 코드를 그대로 사용하세요.\n")

# 1차 분리: train_val / test
X_train_val, X_test, y_train_val, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=SEED,
    stratify=y
)

# 2차 분리: train / val
X_train, X_val, y_train, y_val = train_test_split(
    X_train_val,
    y_train_val,
    test_size=0.2,
    random_state=SEED,
    stratify=y_train_val
)

print("Train:", X_train.shape, y_train.shape)
print("Val  :", X_val.shape, y_val.shape)
print("Test :", X_test.shape, y_test.shape)

# ============================================================
# 6. StandardScaler 적용
# ============================================================
# MLP는 입력 feature들의 스케일에 민감하다.
#
# 예:
# eye_closed_ratio는 0~1 사이
# eye_closed_total_sec는 초 단위
# frame_count는 수백 단위
#
# 값의 범위가 다르면 학습이 불안정해질 수 있으므로
# StandardScaler로 평균 0, 표준편차 1 근처로 맞춘다.

scaler = StandardScaler()

X_train_scaled = scaler.fit_transform(X_train)
X_val_scaled = scaler.transform(X_val)
X_test_scaled = scaler.transform(X_test)

print("스케일링 완료")

# ============================================================
# 7. MLP 모델 정의
# ============================================================

def build_mlp(input_dim):
    model = models.Sequential([
        layers.Input(shape=(input_dim,)),

        layers.Dense(
            64,
            activation="relu",
            kernel_regularizer=regularizers.l2(0.001)
        ),
        layers.BatchNormalization(),
        layers.Dropout(0.3),

        layers.Dense(
            32,
            activation="relu",
            kernel_regularizer=regularizers.l2(0.001)
        ),
        layers.BatchNormalization(),
        layers.Dropout(0.25),

        layers.Dense(
            16,
            activation="relu",
            kernel_regularizer=regularizers.l2(0.001)
        ),
        layers.Dropout(0.2),

        layers.Dense(1, activation="sigmoid")
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss="binary_crossentropy",
        metrics=[
            "accuracy",
            tf.keras.metrics.Precision(name="precision"),
            tf.keras.metrics.Recall(name="recall")
        ]
    )

    return model


model = build_mlp(input_dim=X_train_scaled.shape[1])
model.summary()

# ============================================================
# 8. 클래스 불균형 처리
# ============================================================
# 나중에 normal 데이터가 drowsy보다 많거나,
# drowsy 데이터가 normal보다 적을 수 있다.
#
# class_weight를 사용하면 데이터가 적은 클래스를 더 중요하게 학습시킬 수 있다.

classes = np.unique(y_train)

class_weights_array = compute_class_weight(
    class_weight="balanced",
    classes=classes,
    y=y_train
)

class_weights = {
    int(cls): float(weight)
    for cls, weight in zip(classes, class_weights_array)
}

print("class_weights:", class_weights)

# ============================================================
# 9. 모델 학습
# ============================================================

early_stopping = callbacks.EarlyStopping(
    monitor="val_loss",
    patience=30,
    restore_best_weights=True
)

reduce_lr = callbacks.ReduceLROnPlateau(
    monitor="val_loss",
    factor=0.5,
    patience=10,
    min_lr=1e-6
)

history = model.fit(
    X_train_scaled,
    y_train,
    validation_data=(X_val_scaled, y_val),
    epochs=300,
    batch_size=16,
    class_weight=class_weights,
    callbacks=[early_stopping, reduce_lr],
    verbose=1
)

# ============================================================
# 10. 학습 그래프 확인
# ============================================================

plt.figure(figsize=(8, 5))
plt.plot(history.history["loss"], label="train_loss")
plt.plot(history.history["val_loss"], label="val_loss")
plt.xlabel("Epoch")
plt.ylabel("Loss")
plt.title("Training / Validation Loss")
plt.legend()
plt.grid(True)
plt.show()

plt.figure(figsize=(8, 5))
plt.plot(history.history["accuracy"], label="train_accuracy")
plt.plot(history.history["val_accuracy"], label="val_accuracy")
plt.xlabel("Epoch")
plt.ylabel("Accuracy")
plt.title("Training / Validation Accuracy")
plt.legend()
plt.grid(True)
plt.show()

# ============================================================
# 11. Validation 데이터로 threshold 찾기
# ============================================================
# sigmoid 출력은 0~1 확률이다.
#
# 기본 threshold는 0.5지만,
# 졸음 감지에서는 drowsy를 놓치지 않는 것이 중요할 수 있다.
#
# 그래서 validation set에서 F1-score가 가장 좋은 threshold를 찾는다.

val_probs = model.predict(X_val_scaled).ravel()

thresholds = np.arange(0.1, 0.91, 0.01)

best_threshold = 0.5
best_f1 = -1

results = []

for th in thresholds:
    val_preds = (val_probs >= th).astype(int)

    acc = accuracy_score(y_val, val_preds)
    precision = precision_score(y_val, val_preds, zero_division=0)
    recall = recall_score(y_val, val_preds, zero_division=0)
    f1 = f1_score(y_val, val_preds, zero_division=0)

    results.append([th, acc, precision, recall, f1])

    if f1 > best_f1:
        best_f1 = f1
        best_threshold = th

threshold_df = pd.DataFrame(
    results,
    columns=["threshold", "accuracy", "precision", "recall", "f1"]
)

display(threshold_df.sort_values("f1", ascending=False).head(10))

print("Best threshold:", best_threshold)
print("Best validation F1:", best_f1)

# ============================================================
# 12. Test 데이터 최종 평가
# ============================================================

test_probs = model.predict(X_test_scaled).ravel()
test_preds = (test_probs >= best_threshold).astype(int)

print("Test Accuracy :", accuracy_score(y_test, test_preds))
print("Test Precision:", precision_score(y_test, test_preds, zero_division=0))
print("Test Recall   :", recall_score(y_test, test_preds, zero_division=0))
print("Test F1-score :", f1_score(y_test, test_preds, zero_division=0))

print("\nClassification Report")
print(classification_report(
    y_test,
    test_preds,
    target_names=["normal", "drowsy"],
    zero_division=0
))

print("Confusion Matrix")
cm = confusion_matrix(y_test, test_preds)
print(cm)

# ============================================================
# 13. 예측 결과 직접 확인
# ============================================================

result_df = pd.DataFrame({
    "true_label": [INV_LABEL_MAP[int(v)] for v in y_test],
    "pred_label": [INV_LABEL_MAP[int(v)] for v in test_preds],
    "drowsy_probability": test_probs
})

display(result_df.head(30))

# ============================================================
# 14. 최종 모델 저장
# ============================================================

SAVE_DIR = "drowsy_mlp_model"
os.makedirs(SAVE_DIR, exist_ok=True)

model_path = os.path.join(SAVE_DIR, "drowsy_mlp.keras")
scaler_path = os.path.join(SAVE_DIR, "scaler.pkl")
feature_cols_path = os.path.join(SAVE_DIR, "feature_columns.json")
label_map_path = os.path.join(SAVE_DIR, "label_map.json")
threshold_path = os.path.join(SAVE_DIR, "threshold.json")

model.save(model_path)
joblib.dump(scaler, scaler_path)

with open(feature_cols_path, "w", encoding="utf-8") as f:
    json.dump(feature_cols, f, ensure_ascii=False, indent=2)

with open(label_map_path, "w", encoding="utf-8") as f:
    json.dump(LABEL_MAP, f, ensure_ascii=False, indent=2)

with open(threshold_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "best_threshold": float(best_threshold)
        },
        f,
        ensure_ascii=False,
        indent=2
    )

print("저장 완료")
print("model:", model_path)
print("scaler:", scaler_path)
print("feature columns:", feature_cols_path)
print("threshold:", threshold_path)

# ============================================================
# 15. TFLite 변환
# ============================================================
# 라즈베리파이에서 가볍게 추론하려면 TFLite로 변환하는 것이 좋다.

converter = tf.lite.TFLiteConverter.from_keras_model(model)
tflite_model = converter.convert()

tflite_path = os.path.join(SAVE_DIR, "drowsy_mlp.tflite")

with open(tflite_path, "wb") as f:
    f.write(tflite_model)

print("TFLite 저장 완료:", tflite_path)

# ============================================================
# 16. 압축 후 다운로드
# ============================================================

!zip -r drowsy_mlp_model.zip drowsy_mlp_model

files.download("drowsy_mlp_model.zip")

