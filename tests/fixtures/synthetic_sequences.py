"""Deterministic synthetic landmark sequences (refactoring.md 2.4).

No camera, no video file, no MediaPipe runtime. Every sequence is produced by a
closed-form formula (or a fixed-seed RNG) so re-running this module byte-for-byte
reproduces the same coordinates every time.

Two coordinate spaces are used, matching how the real pipeline actually splits work:

- ``"normalized_image"``: values roughly in [0, 1], the space MediaPipe's
  ``hand_landmarks`` / ``LandmarkPacket.landmarks`` use. Consumed by
  ``containers/2-vision-analysis/app/one_euro_filter.py`` (smoothing) and
  ``app/geometry.py`` (hand_scale / is_near_edge / max_displacement).
- ``"world_meters"``: metric, camera-distance-invariant coordinates, the space
  ``hand_world_landmarks`` / ``LandmarkPacket.world_landmarks`` use. Consumed by
  ``containers/3-pattern-command/gesture_classifier.py`` and ``index_finger.py``.

refactoring.md's ยง2.4 table was written against a generic "single pinch-distance
threshold" PRD template. The gesture engine actually implemented here has no such
pinch state; the closest real analogs are documented on each generator below and
the mapping is summarized in docs/00_baseline.md ("2.4 characterization mapping").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

SEED = 20260831
NUM_LANDMARKS = 21


@dataclass(frozen=True)
class Landmark:
    """Minimal (x, y, z) point. Structurally compatible with both
    ``app.geometry.Point`` (a NamedTuple) and container 3's ``Landmark`` Protocol —
    both only ever read ``.x``/``.y``/``.z``.
    """

    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True)
class Frame:
    frame_id: int
    timestamp_ms: int
    landmarks: Optional[List[Landmark]]  # None == hand not detected this frame


@dataclass(frozen=True)
class SyntheticSequence:
    name: str
    space: str  # "normalized_image" | "world_meters"
    description: str
    frames: List[Frame] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# world_meters helpers (drives containers/3-pattern-command)
# --------------------------------------------------------------------------- #

# Fixed synthetic palm skeleton. Values are plausible adult-hand metric offsets
# (meters, roughly matching PRD 8.1's world-landmark scale) — not a real capture.
_WRIST = Landmark(0.000, 0.000, 0.0)
_INDEX_MCP = Landmark(0.020, 0.090, 0.0)
_MIDDLE_MCP = Landmark(0.000, 0.095, 0.0)
_RING_MCP = Landmark(-0.020, 0.090, 0.0)
_PINKY_MCP = Landmark(-0.038, 0.078, 0.0)
# Thumb CMC/MCP/IP (landmarks 1-3) are not read by any formula in
# gesture_classifier.py / index_finger.py (only landmarks[4] "thumb tip" is used).
# Fixed placeholders here only so every frame carries the required 21 landmarks.
_THUMB_CMC = Landmark(0.010, 0.020, 0.0)
_THUMB_MCP = Landmark(0.018, 0.040, 0.0)
_THUMB_IP = Landmark(0.024, 0.060, 0.0)
# "Inactive" thumb tip: close to the index MCP so
# distance(thumb_tip, index_mcp) / palm_width stays well under thumb_active_ratio
# (default 0.65) and does not accidentally arm zoom evaluation.
_THUMB_TIP_INACTIVE = Landmark(0.010, 0.070, 0.0)

_FINGER_SEG_LEN = 0.035
_FINGER_UP = (0.0, 1.0)


def _dist(a: Landmark, b: Landmark) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _rotate2d(vx: float, vy: float, angle_deg: float) -> tuple[float, float]:
    theta = math.radians(angle_deg)
    c, s = math.cos(theta), math.sin(theta)
    return (vx * c - vy * s, vx * s + vy * c)


def _finger(mcp: Landmark, direction: tuple[float, float], curl_deg: float) -> List[Landmark]:
    """Builds [MCP, PIP, DIP, TIP] for one finger.

    The finger is straight (extends along `direction`) when curl_deg=0 and folds
    toward the palm as curl_deg grows. `index_finger.joint_angle` measures the
    angle at the PIP vertex between rays to MCP and to DIP; by construction that
    angle equals exactly `180 - curl_deg`. Since IndexFingerClassifier's default
    open_pip_angle_deg is 120.0, curl_deg <= 60 reads as OPEN and curl_deg > 60
    reads as CLOSED.
    """
    dx, dy = direction
    pip = Landmark(mcp.x + dx * _FINGER_SEG_LEN, mcp.y + dy * _FINGER_SEG_LEN, mcp.z)
    bx, by = _rotate2d(dx, dy, curl_deg)
    dip = Landmark(pip.x + bx * _FINGER_SEG_LEN, pip.y + by * _FINGER_SEG_LEN, pip.z)
    tip = Landmark(dip.x + bx * _FINGER_SEG_LEN, dip.y + by * _FINGER_SEG_LEN, dip.z)
    return [mcp, pip, dip, tip]


def _hand_frame(
    *,
    index_curl_deg: float,
    other_curl_deg: float = 110.0,
    thumb_mode: str = "inactive",
    spacing_ratio: float = 1.0,
) -> List[Landmark]:
    """Builds one full 21-landmark world-space hand pose.

    thumb_mode="inactive": thumb tucked near the palm (thumb_extension_ratio well
    below the 0.65 default threshold) so DRAW/ERASE evaluate without zoom arming.

    thumb_mode="spacing": thumb tip placed exactly `spacing_ratio * palm_width`
    away from the (already-posed) index fingertip, along the wrist->index-tip
    ray. This lets a sequence dial thumb_index_spacing_ratio to an exact target
    value every frame, which is what gesture_classifier.py compares against
    zoom_start_closed_ratio (0.80) / zoom_start_open_ratio (1.00) by default.
    """
    index = _finger(_INDEX_MCP, _FINGER_UP, index_curl_deg)
    middle = _finger(_MIDDLE_MCP, _FINGER_UP, other_curl_deg)
    ring = _finger(_RING_MCP, _FINGER_UP, other_curl_deg)
    pinky = _finger(_PINKY_MCP, _FINGER_UP, other_curl_deg)

    if thumb_mode == "inactive":
        thumb_tip = _THUMB_TIP_INACTIVE
    elif thumb_mode == "spacing":
        palm_width = _dist(_INDEX_MCP, _PINKY_MCP)
        index_tip = index[3]
        away_x, away_y = index_tip.x - _WRIST.x, index_tip.y - _WRIST.y
        norm = math.hypot(away_x, away_y) or 1.0
        away_x, away_y = away_x / norm, away_y / norm
        thumb_tip = Landmark(
            index_tip.x + away_x * spacing_ratio * palm_width,
            index_tip.y + away_y * spacing_ratio * palm_width,
            0.0,
        )
    else:
        raise ValueError(f"unknown thumb_mode: {thumb_mode}")

    landmarks: List[Optional[Landmark]] = [None] * NUM_LANDMARKS
    landmarks[0] = _WRIST
    landmarks[1], landmarks[2], landmarks[3], landmarks[4] = (
        _THUMB_CMC,
        _THUMB_MCP,
        _THUMB_IP,
        thumb_tip,
    )
    landmarks[5:9] = index
    landmarks[9:13] = middle
    landmarks[13:17] = ring
    landmarks[17:21] = pinky
    assert all(lm is not None for lm in landmarks)
    return landmarks  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# normalized_image helpers (drives containers/2-vision-analysis)
# --------------------------------------------------------------------------- #

# A fixed, roughly hand-shaped set of 21 relative (dx, dy) offsets (not a real
# capture) — landmark 0 at the shape's origin, spreading upward like an open
# hand. Scaled small enough that a centroid of (0.5, 0.5) keeps every point
# inside [0, 1] with margin to spare.
_IMAGE_SHAPE_OFFSETS: List[tuple[float, float]] = [
    (0.000, 0.000),   # 0 wrist
    (0.030, -0.020), (0.055, -0.045), (0.075, -0.065), (0.095, -0.080),  # thumb 1-4
    (0.040, -0.090), (0.045, -0.150), (0.048, -0.195), (0.050, -0.230),  # index 5-8
    (0.010, -0.100), (0.012, -0.170), (0.013, -0.215), (0.014, -0.250),  # middle 9-12
    (-0.020, -0.095), (-0.022, -0.155), (-0.023, -0.195), (-0.024, -0.225),  # ring 13-16
    (-0.048, -0.085), (-0.052, -0.135), (-0.054, -0.170), (-0.056, -0.195),  # pinky 17-20
]
assert len(_IMAGE_SHAPE_OFFSETS) == NUM_LANDMARKS


def _image_frame(cx: float, cy: float, noise: Optional[np.ndarray] = None) -> List[Landmark]:
    """Rigidly translates the fixed hand shape so landmark 0 sits at (cx, cy).

    `noise`, if given, is an (21, 2) array added to (x, y) per landmark — used
    only by static_jitter for deterministic Gaussian jitter.
    """
    out = []
    for i, (dx, dy) in enumerate(_IMAGE_SHAPE_OFFSETS):
        nx, ny = (noise[i, 0], noise[i, 1]) if noise is not None else (0.0, 0.0)
        out.append(Landmark(cx + dx + float(nx), cy + dy + float(ny), 0.0))
    return out


# --------------------------------------------------------------------------- #
# The 6 required sequences
# --------------------------------------------------------------------------- #


def pinch_approach_release() -> SyntheticSequence:
    """Real analog: thumb-index "zoom lock" in GestureClassifier, the only place
    the current code compares a thumb-index distance against two distinct
    thresholds (zoom_start_closed_ratio=0.80 / zoom_start_open_ratio=1.00) —
    the closest thing this codebase has to refactoring.md's generic
    "pinch_enter/pinch_exit" model. thumb_index_spacing_ratio ramps
    1.20 -> 0.60 (approach, crossing the "closed" lock threshold) -> 1.20
    (separate, testing the locked zoom-direction command), then the index
    finger curls shut to exercise release_confirm_frames-based release.
    """
    frames: List[Frame] = []
    fid = 0
    # Phase A: approach (spacing_ratio descends through the closed-lock band).
    for r in np.linspace(1.20, 0.60, 20):
        lm = _hand_frame(index_curl_deg=30.0, thumb_mode="spacing", spacing_ratio=float(r))
        frames.append(Frame(fid, fid * 33, lm))
        fid += 1
    # Phase B: separate again while locked (drives zoom motion commands).
    for r in np.linspace(0.60, 1.20, 20):
        lm = _hand_frame(index_curl_deg=30.0, thumb_mode="spacing", spacing_ratio=float(r))
        frames.append(Frame(fid, fid * 33, lm))
        fid += 1
    # Phase C: release — index curls shut for release_confirm_frames (default 3).
    for _ in range(20):
        lm = _hand_frame(index_curl_deg=110.0, thumb_mode="spacing", spacing_ratio=1.20)
        frames.append(Frame(fid, fid * 33, lm))
        fid += 1
    return SyntheticSequence(
        name="pinch_approach_release",
        space="world_meters",
        description="Thumb-index spacing ratio sweeps through the zoom-lock thresholds, then the index finger releases.",
        frames=frames,
    )


def threshold_chatter() -> SyntheticSequence:
    """Real analog: IndexFingerClassifier's raw PIP-angle threshold (120 deg
    default) chattering frame-to-frame, exercising its window/vote debounce
    (window_size=5, required_open_votes=4) rather than a two-threshold
    hysteresis (the current finger classifier has only one threshold; the
    two-threshold case is covered by pinch_approach_release's zoom lock).
    curl_deg alternates 57/63 deg, i.e. pip_angle alternates 123/117 deg —
    straddling the 120 deg boundary every single frame.
    """
    frames: List[Frame] = []
    for fid in range(40):
        curl = 57.0 if fid % 2 == 0 else 63.0
        lm = _hand_frame(index_curl_deg=curl, thumb_mode="inactive")
        frames.append(Frame(fid, fid * 33, lm))
    return SyntheticSequence(
        name="threshold_chatter",
        space="world_meters",
        description="Index PIP angle oscillates +-3 deg around the 120 deg OPEN/CLOSED threshold every frame.",
        frames=frames,
    )


def hand_lost_midway() -> SyntheticSequence:
    """Real analog: the hand-presence gap that containers/3-pattern-command's
    SessionState.handle_packet reacts to by calling classifier.reset() when
    `packet["hand_present"]` is false. That dispatch line is orchestration
    (websocket-bound), not a pure function — this fixture reproduces just the
    branch condition ("landmarks is None => the driver calls reset() instead
    of update()") so the pure GestureClassifier state machine can be
    characterized without a live session.
    """
    frames: List[Frame] = []
    fid = 0
    for _ in range(10):
        frames.append(Frame(fid, fid * 33, _hand_frame(index_curl_deg=30.0, thumb_mode="inactive")))
        fid += 1
    for _ in range(20):
        frames.append(Frame(fid, fid * 33, None))
        fid += 1
    for _ in range(10):
        frames.append(Frame(fid, fid * 33, _hand_frame(index_curl_deg=30.0, thumb_mode="inactive")))
        fid += 1
    return SyntheticSequence(
        name="hand_lost_midway",
        space="world_meters",
        description="20 frames of hand_present=false in the middle of an otherwise steady DRAW pose.",
        frames=frames,
    )


def fast_swipe() -> SyntheticSequence:
    """Real analog: HandLandmarksFilter (One Euro Filter) lag under a large
    per-frame displacement, and geometry.max_displacement's outlier signal.
    The whole hand translates from x=0.15 to x=0.85 (normalized) over just 6
    frames at ~30fps, then holds — a swipe far faster than a real hand can
    move within one frame interval.
    """
    frames: List[Frame] = []
    fid = 0
    for cx in np.linspace(0.15, 0.85, 6):
        frames.append(Frame(fid, fid * 33, _image_frame(float(cx), 0.55)))
        fid += 1
    for _ in range(10):
        frames.append(Frame(fid, fid * 33, _image_frame(0.85, 0.55)))
        fid += 1
    return SyntheticSequence(
        name="fast_swipe",
        space="normalized_image",
        description="Hand centroid jumps from x=0.15 to x=0.85 in 6 frames, then holds.",
        frames=frames,
    )


def static_jitter() -> SyntheticSequence:
    """Real analog: One Euro Filter jitter suppression on a hand held still.
    Centroid fixed at (0.5, 0.5); each landmark gets independent, fixed-seed
    Gaussian noise (sigma=0.004 normalized units) every frame.
    """
    rng = np.random.default_rng(SEED)
    frames: List[Frame] = []
    for fid in range(60):
        noise = rng.normal(loc=0.0, scale=0.004, size=(NUM_LANDMARKS, 2))
        frames.append(Frame(fid, fid * 33, _image_frame(0.5, 0.5, noise=noise)))
    return SyntheticSequence(
        name="static_jitter",
        space="normalized_image",
        description="Hand held still at (0.5, 0.5) plus fixed-seed per-landmark Gaussian noise (sigma=0.004).",
        frames=frames,
    )


def out_of_bounds() -> SyntheticSequence:
    """Real analog: geometry.is_near_edge / unletterbox_point when the hand
    exits the frame. Per contracts.py's rule 6.2-2, output coordinates are
    explicitly NOT clamped — this sequence pushes the centroid to (-0.20,
    1.25), well outside [0, 1], to record that current (non-clamping)
    behavior as the baseline.
    """
    frames: List[Frame] = []
    fid = 0
    for t in np.linspace(0.0, 1.0, 25):
        cx = 0.5 + t * (-0.20 - 0.5)
        cy = 0.5 + t * (1.25 - 0.5)
        frames.append(Frame(fid, fid * 33, _image_frame(float(cx), float(cy))))
        fid += 1
    return SyntheticSequence(
        name="out_of_bounds",
        space="normalized_image",
        description="Hand centroid slides from (0.5, 0.5) to (-0.20, 1.25), off-frame in both axes.",
        frames=frames,
    )


ALL_SEQUENCES = (
    pinch_approach_release,
    threshold_chatter,
    hand_lost_midway,
    fast_swipe,
    static_jitter,
    out_of_bounds,
)


def build_all() -> dict[str, SyntheticSequence]:
    return {fn.__name__: fn() for fn in ALL_SEQUENCES}
