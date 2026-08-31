import json

import pytest
from app.contracts import (
    ContractError,
    Handedness,
    IngestFrameHeader,
    LandmarkPacket,
    Quality,
)
from app.vision.geometry import NUM_LANDMARKS, Point


def _landmarks():
    return [Point(0.1 * i, 0.2 * i, 0.0) for i in range(NUM_LANDMARKS)]


def test_absent_packet_serializes_nulls_for_hand_fields():
    packet = LandmarkPacket.absent(
        session_id="s1", seq=1, capture_ts=100, processed_ts=110, frame_w=640, frame_h=480
    )
    d = packet.to_dict()
    assert d["hand_present"] is False
    assert d["landmarks"] is None
    assert d["world_landmarks"] is None
    assert d["hand_scale"] is None
    assert d["handedness"] is None


def test_present_packet_requires_landmarks():
    with pytest.raises(ContractError):
        LandmarkPacket(
            session_id="s1",
            seq=1,
            capture_ts=100,
            processed_ts=110,
            hand_present=True,
            frame_w=640,
            frame_h=480,
        )


def test_absent_packet_rejects_landmarks():
    with pytest.raises(ContractError):
        LandmarkPacket(
            session_id="s1",
            seq=1,
            capture_ts=100,
            processed_ts=110,
            hand_present=False,
            frame_w=640,
            frame_h=480,
            landmarks=_landmarks(),
            world_landmarks=_landmarks(),
        )


def test_present_packet_round_trips_through_json():
    packet = LandmarkPacket.present(
        session_id="s1",
        seq=42,
        capture_ts=100,
        processed_ts=120,
        frame_w=640,
        frame_h=480,
        handedness=Handedness("Right", 0.98),
        landmarks=_landmarks(),
        world_landmarks=_landmarks(),
        hand_scale=0.187,
        quality=Quality(near_edge=False, filtered=True, outlier_dropped=False),
    )
    d = json.loads(packet.to_json())
    assert d["hand_present"] is True
    assert len(d["landmarks"]) == NUM_LANDMARKS
    assert d["handedness"] == {"label": "Right", "score": 0.98}
    assert d["hand_scale"] == pytest.approx(0.187)
    assert d["frame"] == {"w": 640, "h": 480}


def test_ingest_header_parses_valid_json():
    # Container A(containers/web/app.py)가 실제로 보내는 헤더 형식.
    raw = json.dumps(
        {
            "schema_version": "1.0",
            "session_id": "abc123",
            "frame_id": "f-1",
            "seq": 7,
            "captured_at_ms": 1735891234567,
            "width": 640,
            "height": 480,
            "channels": 3,
            "dtype": "uint8",
            "color_order": "BGR",
            "byte_length": 640 * 480 * 3,
            "rotation": 90,
            "mirrored": True,
        }
    )
    header = IngestFrameHeader.from_json(raw)
    assert header.session_id == "abc123"
    assert header.capture_ts == 1735891234567
    assert header.pixel_format == "bgr8"
    assert header.expected_payload_size == 640 * 480 * 3
    assert header.rotation == 90
    assert header.mirrored is True


def _base_a_header(**overrides):
    base = {
        "schema_version": "1.0",
        "session_id": "abc",
        "frame_id": "f-1",
        "seq": 1,
        "captured_at_ms": 0,
        "width": 10,
        "height": 10,
        "channels": 3,
        "dtype": "uint8",
        "color_order": "BGR",
        "byte_length": 300,
    }
    base.update(overrides)
    return base


def test_ingest_header_maps_rgb_color_order():
    header = IngestFrameHeader.from_json(json.dumps(_base_a_header(color_order="RGB")))
    assert header.pixel_format == "rgb8"


def test_ingest_header_defaults_rotation_and_mirrored():
    header = IngestFrameHeader.from_json(json.dumps(_base_a_header()))
    assert header.rotation == 0
    assert header.mirrored is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"color_order": "YUV"},
        {"dtype": "float32"},
        {"channels": 4},
        {"rotation": 45},
        {"width": 0},
    ],
)
def test_ingest_header_rejects_invalid_values(overrides):
    with pytest.raises(ContractError):
        IngestFrameHeader.from_json(json.dumps(_base_a_header(**overrides)))


def test_ingest_header_rejects_missing_field():
    with pytest.raises(ContractError):
        IngestFrameHeader.from_json(json.dumps({"seq": 1}))


def test_ingest_header_rejects_malformed_json():
    with pytest.raises(ContractError):
        IngestFrameHeader.from_json("not json")
