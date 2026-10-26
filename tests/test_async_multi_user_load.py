from scripts.load.async_multi_user import _elapsed_ms, _percentile


def test_percentile_interpolates_small_load_samples() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert _percentile(values, 0.5) == 25.0
    assert _percentile(values, 0.95) == 38.5
    assert _percentile([], 0.95) is None


def test_elapsed_ms_requires_both_timestamps() -> None:
    from datetime import UTC, datetime, timedelta

    started = datetime.now(UTC)

    assert _elapsed_ms(started, started + timedelta(seconds=1.25)) == 1250.0
    assert _elapsed_ms(started, None) is None
