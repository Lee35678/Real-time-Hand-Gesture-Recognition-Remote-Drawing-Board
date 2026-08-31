"""bench_e2e_sink.py가 기록한 JSONL을 분석해 지연시간/FPS/드롭률을 계산한다.

사용 예:
    python scripts/bench_analyze.py docs/perf/run1.jsonl
"""

from __future__ import annotations

import argparse
import json

import numpy as np


def analyze(path: str) -> dict:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        raise SystemExit(f"no records in {path}")

    records.sort(key=lambda r: r["seq"])
    seqs = [r["seq"] for r in records]
    hand_present_count = sum(1 for r in records if r["hand_present"])

    e2e = np.array([r["processed_ts"] - r["capture_ts"] for r in records], dtype=float)

    seq_min, seq_max = min(seqs), max(seqs)
    expected_count = seq_max - seq_min + 1
    received_count = len(records)
    drop_rate = 1.0 - (received_count / expected_count) if expected_count > 0 else 0.0

    duration_s = (records[-1]["recv_ts_ms"] - records[0]["recv_ts_ms"]) / 1000.0
    processed_fps = received_count / duration_s if duration_s > 0 else 0.0

    return {
        "file": path,
        "received_count": received_count,
        "expected_count": expected_count,
        "drop_rate": drop_rate,
        "duration_s": duration_s,
        "processed_fps": processed_fps,
        "hand_present_rate": hand_present_count / received_count,
        "e2e_ms_p50": float(np.percentile(e2e, 50)),
        "e2e_ms_p95": float(np.percentile(e2e, 95)),
        "e2e_ms_p99": float(np.percentile(e2e, 99)),
        "e2e_ms_min": float(e2e.min()),
        "e2e_ms_max": float(e2e.max()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a bench_e2e_sink.py JSONL log")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    for path in args.paths:
        result = analyze(path)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
