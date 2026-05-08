# ============================================================
# 새 window30sec CSV 예측 코드
# ============================================================

import json
import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from google.colab import files

MODEL_DIR = "drowsy_mlp_model"

model = tf.keras.models.load_model(f"{MODEL_DIR}/drowsy_mlp.keras")
scaler = joblib.load(f"{MODEL_DIR}/scaler.pkl")

with open(f"{MODEL_DIR}/feature_columns.json", "r", encoding="utf-8") as f:
    feature_cols = json.load(f)

with open(f"{MODEL_DIR}/threshold.json", "r", encoding="utf-8") as f:
    threshold_info = json.load(f)

threshold = threshold_info["best_threshold"]

uploaded = files.upload()
new_csv_path = list(uploaded.keys())[0]

new_df = pd.read_csv(new_csv_path)

# 학습 때 사용한 feature가 새 CSV에 없으면 0으로 채움
for col in feature_cols:
    if col not in new_df.columns:
        new_df[col] = 0

X_new = new_df[feature_cols].copy()
X_new = X_new.replace([np.inf, -np.inf], np.nan)
X_new = X_new.fillna(0)

X_new_scaled = scaler.transform(X_new.values.astype(np.float32))

probs = model.predict(X_new_scaled).ravel()
preds = (probs >= threshold).astype(int)

result_df = new_df.copy()
result_df["drowsy_probability"] = probs
result_df["prediction"] = np.where(preds == 1, "drowsy", "normal")

display(result_df[[
    "video_name",
    "window_id",
    "drowsy_probability",
    "prediction"
]])