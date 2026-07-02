import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


class SessionLogger:
    HEADER = [
        "timestamp",
        "state",
        "session_id",
        "elapsed_sec",
        "duration_sec",
        "remain_sec",
        "posture_label",
        "posture_confidence",
        "fatigue_label",
        "fatigue_probability",
        "pose_detected",
        "face_detected",
        "error",
        "stop_reason",
    ]

    def __init__(self, base_dir="data/session_log", report_dir="data/reports"):
        self.base_dir = Path(base_dir)
        self.report_dir = Path(report_dir)
        self._ensure_dirs()
        self._lock = RLock()
        self.active = False
        self.csv_path: str | None = None
        self.summary_path: str | None = None
        self.rows_written = 0
        self.last_error: str | None = None
        self.started_at: str | None = None
        self.measuring_started_at: str | None = None
        self.ended_at: str | None = None
        self.session_id: str | None = None
        self.duration_sec: int | None = None
        self._csv_file = None
        self._csv_writer = None
        self.posture_counts: dict[str, int] = {}
        self.fatigue_counts: dict[str, int] = {}
        self.total_posture_confidence = 0.0
        self.total_fatigue_probability = 0.0
        self.max_fatigue_probability = 0.0
        self._last_summary: dict | None = None

    def _ensure_dirs(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_session_id(self, session_id: str | None) -> str:
        if session_id is None:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id))

    def _to_float(self, value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def start(self, session_id: str | None, duration_sec: int | None, started_at: str | None):
        with self._lock:
            if self.active:
                self.finish("restarted")

            self.session_id = self._sanitize_session_id(session_id)
            self.duration_sec = duration_sec
            self.started_at = started_at
            self.measuring_started_at = None
            self.ended_at = None
            self.csv_path = str(self.base_dir / f"session_{self.session_id}.csv")
            self.summary_path = str(self.report_dir / f"report_summary_{self.session_id}.json")
            self.rows_written = 0
            self.last_error = None
            self.posture_counts = {}
            self.fatigue_counts = {}
            self.total_posture_confidence = 0.0
            self.total_fatigue_probability = 0.0
            self.max_fatigue_probability = 0.0

            self._csv_file = open(self.csv_path, mode="a", newline="", encoding="utf-8")
            self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self.HEADER)
            if self._csv_file.tell() == 0:
                self._csv_writer.writeheader()
            self.active = True

    def set_measuring_started_at(self, measuring_started_at: str | None):
        with self._lock:
            self.measuring_started_at = measuring_started_at

    def write_measurement(self, measurement: dict):
        with self._lock:
            if not self.active or self._csv_writer is None:
                return

            row = {key: measurement.get(key) for key in self.HEADER}
            if row.get("timestamp") is None:
                row["timestamp"] = datetime.now(timezone.utc).isoformat()
            if row.get("session_id") is None:
                row["session_id"] = self.session_id
            if row.get("duration_sec") is None:
                row["duration_sec"] = self.duration_sec

            self._csv_writer.writerow(row)
            self._csv_file.flush()

            self.rows_written += 1
            posture_label = row.get("posture_label") or "Unknown"
            fatigue_label = row.get("fatigue_label") or "Unknown"
            self.posture_counts[posture_label] = self.posture_counts.get(posture_label, 0) + 1
            self.fatigue_counts[fatigue_label] = self.fatigue_counts.get(fatigue_label, 0) + 1
            self.total_posture_confidence += self._to_float(row.get("posture_confidence"))
            fatigue_value = self._to_float(row.get("fatigue_probability"))
            self.total_fatigue_probability += fatigue_value
            self.max_fatigue_probability = max(self.max_fatigue_probability, fatigue_value)

    def finish(self, stop_reason: str):
        with self._lock:
            if not self.active:
                return

            self.ended_at = datetime.now(timezone.utc).isoformat()
            if self._csv_file is not None:
                try:
                    self._csv_file.close()
                except Exception:
                    pass
                self._csv_file = None
                self._csv_writer = None

            summary = {
                "session_id": self.session_id,
                "started_at": self.started_at,
                "session_started_at": self.started_at,
                "measuring_started_at": self.measuring_started_at,
                "ended_at": self.ended_at,
                "duration_sec": self.duration_sec,
                "session_total_elapsed_sec": self._calculate_actual_elapsed_sec(),
                "measurement_elapsed_sec": self._calculate_measurement_elapsed_sec(),
                "actual_elapsed_sec": self._calculate_actual_elapsed_sec(),
                "stop_reason": stop_reason,
                "row_count": self.rows_written,
                "posture_counts": dict(self.posture_counts),
                "fatigue_counts": dict(self.fatigue_counts),
                "avg_posture_confidence": self._calculate_average(self.total_posture_confidence),
                "avg_fatigue_probability": self._calculate_average(self.total_fatigue_probability),
                "max_fatigue_probability": self.max_fatigue_probability,
                "log_csv_path": self.csv_path,
            }

            try:
                with open(self.summary_path, mode="w", encoding="utf-8") as summary_file:
                    json.dump(summary, summary_file, ensure_ascii=False, indent=2)
                self._last_summary = summary
            except Exception as exc:
                self.last_error = str(exc)
                self._last_summary = summary

            self.active = False

    def _calculate_actual_elapsed_sec(self) -> int:
        if not self.started_at or not self.ended_at:
            return 0
        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at)
            return max(int((end - start).total_seconds()), 0)
        except ValueError:
            return 0

    def _calculate_measurement_elapsed_sec(self) -> int:
        if not self.measuring_started_at or not self.ended_at:
            return 0
        try:
            start = datetime.fromisoformat(self.measuring_started_at)
            end = datetime.fromisoformat(self.ended_at)
            return max(int((end - start).total_seconds()), 0)
        except ValueError:
            return 0

    def _calculate_average(self, total_value: float) -> float:
        if self.rows_written == 0:
            return 0.0
        return total_value / self.rows_written

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self.active,
                "csv_path": self.csv_path,
                "summary_path": self.summary_path if self._last_summary is not None else None,
                "rows_written": self.rows_written,
                "last_error": self.last_error,
            }

    def latest_report(self) -> dict | None:
        with self._lock:
            if self._last_summary is not None:
                return self._last_summary

        reports = sorted(
            self.report_dir.glob("report_summary_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not reports:
            return None

        try:
            with open(reports[0], mode="r", encoding="utf-8") as report_file:
                return json.load(report_file)
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def get_summary(self, session_id: str) -> dict | None:
        target = self.report_dir / f"report_summary_{self._sanitize_session_id(session_id)}.json"
        if not target.exists():
            return None
        try:
            with open(target, mode="r", encoding="utf-8") as report_file:
                return json.load(report_file)
        except Exception as exc:
            self.last_error = str(exc)
            return None
