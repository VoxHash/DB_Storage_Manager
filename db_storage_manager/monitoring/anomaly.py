"""Anomaly alerts from a local sample history.

Samples stay on this machine (``metric-samples/<connection>.json``, mode
``0600``). Nothing is uploaded. A metric is judged only when the latest
sample and at least five earlier numeric values exist, so one poll cannot
fire an alert.

Compared with the median of the earlier samples:

- connections: latest is at least double the median and at least five above it
- cache hit ratio: a drop of 15 points or more, and the latest value is at
  most 90%
- growth: database size is at least 25% above the median and at least 10 MiB
  larger
- slow queries: ``queryTime`` (milliseconds of the slowest active statement)
  is at least 1000 ms and at least double the median
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MIN_PRIOR_SAMPLES = 5
MAX_SAMPLES = 200
_GROWTH_BYTES = 10 * 1024 * 1024
_NUMERIC_KEYS = (
    "activeConnections",
    "cacheHitRatio",
    "databaseSize",
    "queryTime",
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def sample_from_metrics(metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Keep the numeric fields anomaly detection reads. Drop SQL and secrets."""
    sample: Dict[str, Any] = {
        "timestamp": str(metrics.get("timestamp") or datetime.now().isoformat())
    }
    for key in _NUMERIC_KEYS:
        if key not in metrics or metrics.get(key) is None:
            continue
        try:
            sample[key] = float(metrics[key])
        except (TypeError, ValueError):
            continue
    if len(sample) == 1:
        return None
    return sample


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def _series(rows: List[Dict[str, Any]], key: str) -> List[float]:
    values: List[float] = []
    for row in rows:
        if key not in row or row.get(key) is None:
            continue
        try:
            values.append(float(row[key]))
        except (TypeError, ValueError):
            continue
    return values


def detect_anomalies(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return anomaly records. Does not read a database or the disk."""
    if len(history) < MIN_PRIOR_SAMPLES + 1:
        return []
    latest = history[-1]
    prior = history[:-1]
    found: List[Dict[str, Any]] = []

    connections = _series(prior, "activeConnections")
    if len(connections) >= MIN_PRIOR_SAMPLES and "activeConnections" in latest:
        current = float(latest["activeConnections"])
        baseline = _median(connections)
        jump = current - baseline
        if current >= 5 and jump >= 5 and current >= max(baseline * 2.0, baseline + 5):
            critical = current >= baseline * 3.0 or jump >= 50
            found.append(
                _record(
                    "connections",
                    "critical" if critical else "warning",
                    "Connection count jumped",
                    (
                        f"Active connections are {current:.0f}; the median of "
                        f"the local history is {baseline:.0f}."
                    ),
                    current,
                    baseline,
                )
            )

    ratios = _series(prior, "cacheHitRatio")
    if len(ratios) >= MIN_PRIOR_SAMPLES and "cacheHitRatio" in latest:
        current = float(latest["cacheHitRatio"])
        baseline = _median(ratios)
        drop = baseline - current
        if drop >= 15 and current <= 90:
            critical = drop >= 30 or current <= 60
            found.append(
                _record(
                    "cache_hit_ratio",
                    "critical" if critical else "warning",
                    "Cache hit ratio dropped",
                    (
                        f"Cache hit ratio is {current:.1f}%; the median of "
                        f"the local history is {baseline:.1f}%."
                    ),
                    current,
                    baseline,
                )
            )

    sizes = _series(prior, "databaseSize")
    if len(sizes) >= MIN_PRIOR_SAMPLES and "databaseSize" in latest:
        current = float(latest["databaseSize"])
        baseline = _median(sizes)
        if (
            baseline > 0
            and current >= baseline * 1.25
            and current - baseline >= _GROWTH_BYTES
        ):
            critical = current >= baseline * 2.0
            found.append(
                _record(
                    "growth",
                    "critical" if critical else "warning",
                    "Database size grew",
                    (
                        f"Database size is {current:.0f} bytes; the median of "
                        f"the local history is {baseline:.0f} bytes."
                    ),
                    current,
                    baseline,
                )
            )

    times = _series(prior, "queryTime")
    if len(times) >= MIN_PRIOR_SAMPLES and "queryTime" in latest:
        current = float(latest["queryTime"])
        baseline = _median(times)
        if current >= 1000 and (baseline <= 0 or current >= baseline * 2.0):
            critical = current >= 5000
            found.append(
                _record(
                    "slow_queries",
                    "critical" if critical else "warning",
                    "Slow query",
                    (
                        f"Slowest active statement is {current:.0f} ms; the "
                        f"median of the local history is {baseline:.0f} ms."
                    ),
                    current,
                    baseline,
                )
            )
    return found


def _record(
    metric: str,
    severity: str,
    title: str,
    message: str,
    latest: float,
    baseline: float,
) -> Dict[str, Any]:
    return {
        "metric": metric,
        "severity": severity,
        "title": title,
        "message": message,
        "latest": latest,
        "baseline": baseline,
        "source": "anomaly",
    }


def _safe_connection_id(connection_id: str) -> str:
    cleaned = _SAFE_ID.sub("_", str(connection_id or "default")).strip("._")
    return (cleaned or "default")[:80]


def samples_path(connection_id: str, directory: Optional[Path] = None) -> Path:
    root = directory if directory is not None else _default_directory()
    return root / f"{_safe_connection_id(connection_id)}.json"


def _default_directory() -> Path:
    from ..config import USER_DATA_DIR

    return Path(USER_DATA_DIR) / "metric-samples"


def load_samples(connection_id: str, directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = samples_path(connection_id, directory)
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [row for row in loaded if isinstance(row, dict)]


def append_sample(
    connection_id: str,
    metrics: Dict[str, Any],
    *,
    directory: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Append one sample and return the stored history (capped)."""
    sample = sample_from_metrics(metrics)
    history = load_samples(connection_id, directory)
    if sample is None:
        return history
    history.append(sample)
    if len(history) > MAX_SAMPLES:
        history = history[-MAX_SAMPLES:]
    path = samples_path(connection_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)
    return history


def record_and_detect(
    connection_id: str,
    metrics: Dict[str, Any],
    *,
    directory: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Persist the sample locally, then evaluate anomalies."""
    history = append_sample(connection_id, metrics, directory=directory)
    return detect_anomalies(history)
