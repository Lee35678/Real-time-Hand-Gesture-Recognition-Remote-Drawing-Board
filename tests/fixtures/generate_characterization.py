"""One-shot generator for tests/fixtures/characterization.json (refactoring.md 2.4 Step 2).

Feeds the 6 synthetic sequences in synthetic_sequences.py through the CURRENT
(pre-refactor) pure logic — HandLandmarksFilter + geometry helpers from
containers/vision-analysis, and GestureClassifier from
containers/pattern-command — and dumps every frame's output. No camera, no
video file, no MediaPipe runtime is touched.

Run again (`python tests/fixtures/generate_characterization.py`) only to
deliberately refresh the snapshot after a behavior change has been reviewed and
accepted; during Phase 1+ refactoring this file must keep reproducing the
existing characterization.json byte-for-byte (mismatches are regressions).

Tolerance for a future comparison test: coordinates atol=1e-6, every other
field (command, mode, labels, booleans, None-ness) must match exactly.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VISION_APP_DIR = REPO_ROOT / "containers" / "vision-analysis"
PATTERN_COMMAND_DIR = REPO_ROOT / "containers" / "pattern-command"

# containers/pattern-command/app.py would otherwise shadow the `app` package
# in containers/vision-analysis ('app' resolves to whichever is earlier on
# sys.path) — import everything from the `app` package before adding
# PATTERN_COMMAND_DIR to sys.path.
sys.path.insert(0, str(VISION_APP_DIR))
from app.geometry import hand_scale, is_near_edge, max_displacement  # noqa: E402
from app.one_euro_filter import HandLandmarksFilter  # noqa: E402

sys.path.insert(0, str(PATTERN_COMMAND_DIR))
from gesture_classifier import GestureClassifier  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_sequences import (  # noqa: E402
    Landmark,
    build_all,
)

NEAR_EDGE_MARGIN_DEFAULT = 0.03  # config/vision-analysis.yaml: pipeline.near_edge_margin


def _landmark_to_dict(lm: Landmark) -> dict:
    return {"x": lm.x, "y": lm.y, "z": lm.z}


def _run_world_sequence(seq) -> list[dict]:
    """Drives GestureClassifier() with default thresholds (matches
    containers/pattern-command/config.py's current defaults).

    On a None-landmarks frame this calls classifier.reset(), mirroring
    containers/pattern-command/app.py's SessionState.handle_packet branch for
    hand_present=false (that branch itself is not pure/importable headless).
    """
    classifier = GestureClassifier()
    out = []
    for frame in seq.frames:
        if frame.landmarks is None:
            classifier.reset()
            out.append({"frame_id": frame.frame_id, "hand_present": False, "state": None})
            continue
        state = classifier.update(frame.landmarks)
        out.append(
            {
                "frame_id": frame.frame_id,
                "hand_present": True,
                "state": dataclasses.asdict(state),
            }
        )
    return out


def _run_image_sequence(seq) -> list[dict]:
    """Drives HandLandmarksFilter() with its class defaults (min_cutoff=1.0,
    beta=0.3, d_cutoff=1.0 — identical to config/vision-analysis.yaml's
    one_euro.* defaults) plus the geometry helpers used by
    containers/vision-analysis/app/pipeline.py::_handle_result.
    """
    filt = HandLandmarksFilter()
    out = []
    prev_filtered = None
    for frame in seq.frames:
        filtered = filt.apply(frame.landmarks, timestamp_ms=frame.timestamp_ms)
        scale = hand_scale(filtered)
        near_edge = is_near_edge(filtered, margin=NEAR_EDGE_MARGIN_DEFAULT)
        displacement = max_displacement(prev_filtered, filtered) if prev_filtered is not None else None
        out.append(
            {
                "frame_id": frame.frame_id,
                "hand_present": True,
                "filtered_landmarks": [_landmark_to_dict(p) for p in filtered],
                "hand_scale": scale,
                "is_near_edge": near_edge,
                "max_displacement_from_prev": displacement,
            }
        )
        prev_filtered = filtered
    return out


_RUNNERS = {
    "pinch_approach_release": ("world_meters", "gesture_classifier.GestureClassifier", _run_world_sequence),
    "threshold_chatter": ("world_meters", "gesture_classifier.GestureClassifier", _run_world_sequence),
    "hand_lost_midway": ("world_meters", "gesture_classifier.GestureClassifier", _run_world_sequence),
    "fast_swipe": ("normalized_image", "app.one_euro_filter.HandLandmarksFilter + app.geometry", _run_image_sequence),
    "static_jitter": ("normalized_image", "app.one_euro_filter.HandLandmarksFilter + app.geometry", _run_image_sequence),
    "out_of_bounds": ("normalized_image", "app.one_euro_filter.HandLandmarksFilter + app.geometry", _run_image_sequence),
}


def main() -> None:
    sequences = build_all()
    result = {
        "schema_note": "Phase 0 characterization snapshot (refactoring.md 2.4). See docs/00_baseline.md.",
        "tolerance": {"coordinates_atol": 1e-6, "other_fields": "exact_match"},
        "sequences": {},
    }

    for name, seq in sequences.items():
        space, source, runner = _RUNNERS[name]
        assert seq.space == space, f"{name}: expected space {space!r}, got {seq.space!r}"
        result["sequences"][name] = {
            "description": seq.description,
            "space": space,
            "source": source,
            "frame_count": len(seq.frames),
            "frames": runner(seq),
        }

    out_path = Path(__file__).resolve().parent / "characterization.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
