from polybot.discovery.gamma import slug_for, window_start_ts
from polybot.models.core import Asset


def test_window_start_ts_aligns_to_interval() -> None:
    # 2024-01-01T00:07:23Z = 1704067643
    assert window_start_ts(1704067643, 300) == 1704067500
    assert 1704067643 - window_start_ts(1704067643, 300) < 300


def test_window_start_ts_exact_boundary_is_identity() -> None:
    assert window_start_ts(1704067500, 300) == 1704067500


def test_slug_for_matches_deterministic_scheme() -> None:
    assert slug_for(Asset.BTC, 1704067500) == "btc-updown-5m-1704067500"
    assert slug_for(Asset.HYPE, 1704067500) == "hype-updown-5m-1704067500"
