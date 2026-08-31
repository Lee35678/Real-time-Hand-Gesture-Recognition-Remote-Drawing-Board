from app.observability.metrics import MetricsCollector


def test_snapshot_reports_detection_rate():
    m = MetricsCollector(window_size=10)
    for present in [True, True, False, True]:
        m.record_inference(duration_ms=10.0, hand_present=present)

    snap = m.snapshot()
    assert snap.frames_total == 4
    assert snap.frames_hand_present == 3
    assert snap.detection_rate == 0.75


def test_snapshot_computes_percentiles():
    m = MetricsCollector(window_size=100)
    for ms in [10, 12, 11, 13, 100]:
        m.record_inference(duration_ms=ms, hand_present=True)

    snap = m.snapshot()
    assert snap.inference_ms_p50 < snap.inference_ms_p95


def test_large_spike_flagged_as_likely_palm_redetect():
    m = MetricsCollector(window_size=50)
    for _ in range(20):
        m.record_inference(duration_ms=10.0, hand_present=True)
    m.record_inference(duration_ms=30.0, hand_present=True)

    snap = m.snapshot()
    assert snap.palm_redetect_rate > 0


def test_empty_collector_snapshot_does_not_crash():
    m = MetricsCollector()
    snap = m.snapshot()
    assert snap.frames_total == 0
    assert snap.detection_rate == 0


def test_stage_latencies_reports_percentiles_per_stage():
    m = MetricsCollector(window_size=50)
    for ms in [1.0, 2.0, 3.0, 4.0, 5.0]:
        m.record_stage("preprocess", ms)
    for ms in [10.0, 20.0]:
        m.record_stage("smoothing", ms)

    latencies = m.stage_latencies()
    assert set(latencies) == {"preprocess", "smoothing"}
    assert latencies["preprocess"]["p50"] == 3.0
    assert latencies["smoothing"]["p50"] == 15.0


def test_snapshot_includes_stage_latencies():
    m = MetricsCollector(window_size=50)
    m.record_stage("total", 12.0)

    snap = m.snapshot()
    assert "total" in snap.stage_latencies_ms
    assert snap.to_dict()["stage_latencies_ms"]["total"]["p50"] == 12.0


def test_total_stage_over_budget_logs_a_warning(caplog):
    m = MetricsCollector(target_latency_budget_ms=50.0, stage_log_every_n_frames=1000)
    with caplog.at_level("WARNING"):
        m.record_stage("total", 75.0)

    assert any("exceeds budget" in r.message for r in caplog.records)


def test_total_stage_under_budget_does_not_warn(caplog):
    m = MetricsCollector(target_latency_budget_ms=50.0, stage_log_every_n_frames=1000)
    with caplog.at_level("WARNING"):
        m.record_stage("total", 10.0)

    assert not any("exceeds budget" in r.message for r in caplog.records)


def test_stage_snapshot_logged_every_n_frames(caplog):
    m = MetricsCollector(target_latency_budget_ms=1000.0, stage_log_every_n_frames=3)
    with caplog.at_level("INFO"):
        for _ in range(5):
            m.record_stage("total", 5.0)

    snapshot_logs = [r for r in caplog.records if "stage latency snapshot" in r.message]
    assert len(snapshot_logs) == 1  # only frame #3 out of 5 hits the every-3-frames boundary
