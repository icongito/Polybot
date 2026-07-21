import pytest

from polybot.config import ModelConfig
from polybot.models.core import Asset, FeedSource, MarketInfo, OpeningPrice, ResolutionRules, Tick
from polybot.pricing.baseline import BaselineModel, BaselineResult, normal_cdf
from polybot.pricing.empirical import EmpiricalModel
from polybot.pricing.ensemble import ConservativeEnsemble
from polybot.pricing.features import FeatureVector
from polybot.pricing.state import AssetState, MarketView
from polybot.pricing.vol import RealizedVol

RULES = ResolutionRules(
    raw_description="up on tie",
    resolution_source="Chainlink",
    references_chainlink=True,
    up_wins_on_equal=True,
    interval_start_ts=0.0,
    interval_end_ts=300.0,
    valid=True,
)


def _market(start_ts: float = 0.0) -> MarketInfo:
    return MarketInfo(
        slug="btc-updown-5m-0",
        asset=Asset.BTC,
        condition_id="c",
        up_token_id="u",
        down_token_id="d",
        start_ts=start_ts,
        end_ts=start_ts + 300,
        tick_size=0.01,
        rules=RULES,
        discovered_at_ns=0,
    )


def _state_with_vol(sigma_per_sqrt_s: float) -> AssetState:
    vol = RealizedVol(halflife_s=60.0, floor_per_sqrt_s=sigma_per_sqrt_s, min_ticks=1)
    state = AssetState(Asset.BTC, vol)
    state.on_tick(
        Tick(
            source=FeedSource.RTDS_CHAINLINK,
            asset=Asset.BTC,
            symbol="btc/usd",
            provider_ts=0.0,
            local_recv_ns=0,
            last=100.0,
        )
    )
    return state


def _view_with_opening(price: float, verified: bool = True) -> MarketView:
    market = _market()
    view = MarketView(market=market)
    view.opening = OpeningPrice(
        asset=Asset.BTC,
        market_slug=market.slug,
        price=price,
        source=FeedSource.RTDS_CHAINLINK,
        provider_ts=0.0,
        local_recv_ns=0,
        verified=verified,
    )
    return view


def test_normal_cdf_matches_known_values() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert normal_cdf(1.959964) == pytest.approx(0.975, abs=1e-4)


def test_baseline_probability_is_half_when_price_unchanged() -> None:
    config = ModelConfig()
    model = BaselineModel(config)
    state = _state_with_vol(1e-3)
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=100.0,
        local_recv_ns=int(100e9),
        last=100.0,
    )
    view = _view_with_opening(100.0)

    result = model.probability_up(
        state, view, now_s=100.0, now_ns=int(100e9), max_exchange_age_s=5.0
    )
    assert result is not None
    assert result.p_up == pytest.approx(0.5, abs=0.01)


def test_baseline_probability_approaches_one_far_above_open_low_vol() -> None:
    config = ModelConfig(probability_clamp=1e-6)
    model = BaselineModel(config)
    state = _state_with_vol(1e-6)  # near-zero vol floor
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=250.0,
        local_recv_ns=int(250e9),
        last=110.0,  # +10% distance
    )
    view = _view_with_opening(100.0)

    result = model.probability_up(
        state, view, now_s=250.0, now_ns=int(250e9), max_exchange_age_s=5.0
    )
    assert result is not None
    assert result.p_up > 0.95


def test_baseline_probability_approaches_zero_far_below_open_low_vol() -> None:
    config = ModelConfig(probability_clamp=1e-6)
    model = BaselineModel(config)
    state = _state_with_vol(1e-6)
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=250.0,
        local_recv_ns=int(250e9),
        last=90.0,  # -10% distance
    )
    view = _view_with_opening(100.0)

    result = model.probability_up(
        state, view, now_s=250.0, now_ns=int(250e9), max_exchange_age_s=5.0
    )
    assert result is not None
    assert result.p_up < 0.05


def test_baseline_returns_none_when_opening_unverified() -> None:
    config = ModelConfig()
    model = BaselineModel(config)
    state = _state_with_vol(1e-3)
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=100.0,
        local_recv_ns=int(100e9),
        last=100.0,
    )
    view = _view_with_opening(100.0, verified=False)

    result = model.probability_up(
        state, view, now_s=100.0, now_ns=int(100e9), max_exchange_age_s=5.0
    )
    assert result is None


def test_ensemble_widens_uncertainty_on_model_disagreement() -> None:
    config = ModelConfig(disagreement_uncertainty_scale=0.5)

    class FixedBaseline(BaselineModel):
        def probability_up(
            self,
            state: AssetState,
            view: MarketView,
            *,
            now_s: float,
            now_ns: int,
            max_exchange_age_s: float,
        ) -> BaselineResult:
            return BaselineResult(
                p_up=0.9, anchor_price=100.0, stdev_remaining=0.01, p_no_more_updates=0.0
            )

    class StubEmpirical(EmpiricalModel):
        def __init__(self) -> None:
            pass

        def probability_up(self, features: FeatureVector) -> float:
            return 0.5

    ensemble_disagree = ConservativeEnsemble(config, FixedBaseline(config), StubEmpirical())
    state = _state_with_vol(1e-3)
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=100.0,
        local_recv_ns=int(100e9),
        last=100.0,
    )
    view = _view_with_opening(100.0)
    dummy_features = FeatureVector(
        z_distance=0.0,
        sqrt_tau=1.0,
        sigma=0.0,
        exchange_gap=0.0,
        momentum=0.0,
        dispersion=0.0,
        book_imbalance=0.0,
        spread=0.02,
        trade_intensity=0.0,
        update_cadence=0.0,
    )

    result = ensemble_disagree.probability_up(
        state, view, features=dummy_features, now_s=100.0, now_ns=int(100e9), max_exchange_age_s=5.0
    )
    assert result is not None
    # Disagreement of 0.4 between 0.9 and 0.5 should be reflected and shrink
    # the blended probability toward 0.5 relative to a naive 0.5/0.5 average.
    assert result.disagreement == pytest.approx(0.4, abs=1e-9)
    assert result.uncertainty > 0.0
    naive_average = 0.5 * 0.9 + 0.5 * 0.5
    assert result.p_up < naive_average
