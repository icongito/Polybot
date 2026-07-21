"""Wires feeds, discovery, pricing, strategy, risk, execution, and recording
into one running application for OBSERVE / PAPER / SHADOW / LIVE modes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from polybot.bus import EventBus
from polybot.clock import Clock, DriftMonitor, WallClock
from polybot.config import (
    LIVE_CONFIRM_ENV,
    LIVE_CONFIRM_VALUE,
    MIN_RECORDED_MARKETS_FOR_LIVE,
    AppConfig,
)
from polybot.discovery.gamma import GammaDiscovery
from polybot.discovery.scheduler import IntervalState, MarketScheduler
from polybot.execution.base import ExecutionBackend
from polybot.execution.delay import DelayTracker
from polybot.execution.live import ClobExecutor, build_clob_client
from polybot.execution.paper import PaperExecutor, PaperFillParams
from polybot.execution.precheck import pre_submission_check
from polybot.feeds.base import WebSocketFeed
from polybot.feeds.chainlink_streams import ChainlinkStreamsFeed
from polybot.feeds.clob_market import ClobMarketFeed, TokenRef
from polybot.feeds.clob_user import ClobUserFeed
from polybot.feeds.exchanges import BinanceFeed, CoinbaseFeed, OkxFeed
from polybot.feeds.health import FeedHealthAggregator
from polybot.feeds.rtds_chainlink import RtdsChainlinkFeed
from polybot.models.core import (
    Asset,
    BookSnapshot,
    FeedSource,
    MarketResult,
    OrderIntent,
    OrderRecord,
    OrderStatus,
    Side,
    Signal,
    TradingMode,
)
from polybot.observability import metrics
from polybot.persistence.db import Database
from polybot.persistence.redis_state import RedisState
from polybot.persistence.repos import Repository
from polybot.pricing.baseline import BaselineModel
from polybot.pricing.empirical import EmpiricalModel
from polybot.pricing.ensemble import ConservativeEnsemble
from polybot.pricing.state import PriceStateTracker
from polybot.recording.writer import CaptureWriter
from polybot.risk.engine import GeoGate, KillSwitch, RiskEngine
from polybot.strategy.engine import StrategyEngine

logger = logging.getLogger(__name__)

EVAL_INTERVAL_S = 0.25


class PolybotApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.assets = config.assets
        self.bus = EventBus()
        self.clock: Clock = WallClock()
        self.drift = DriftMonitor(config.risk.max_clock_drift_s)

        self.db = Database(config.storage.database_url)
        self.redis = RedisState(config.storage.redis_url)

        self.tracker = PriceStateTracker(
            self.assets,
            vol_halflife_s=config.model.vol_ewma_halflife_s,
            vol_floor=config.model.vol_floor_per_sqrt_s,
            vol_min_ticks=config.model.vol_sample_min_ticks,
        )
        empirical = EmpiricalModel.load(
            config.model.empirical_model_path,
            min_samples=config.model.empirical_min_training_samples,
        )
        self.ensemble = ConservativeEnsemble(config.model, BaselineModel(config.model), empirical)

        self.health = FeedHealthAggregator(
            max_chainlink_age_s=config.risk.max_chainlink_age_s,
            max_exchange_age_s=config.risk.max_exchange_age_s,
        )
        self.kill_switch = KillSwitch(file_path=config.risk.kill_switch_file)
        self.geo = GeoGate(
            eligible=config.risk.geo_eligible, attestation=config.risk.geo_attestation
        )
        self.risk = RiskEngine(
            config=config.risk, drift=self.drift, kill_switch=self.kill_switch, geo=self.geo
        )
        self.delay_tracker = DelayTracker()

        self.mode = config.mode
        self.strategy = StrategyEngine(
            self.tracker,
            self.ensemble,
            self.risk,
            self.bus,
            risk_config=config.risk,
            endgame=config.endgame,
            model_config=config.model,
            mode=self.mode,
        )

        self._httpx = httpx.AsyncClient(
            base_url=config.discovery.gamma_base_url, timeout=config.discovery.request_timeout_s
        )
        self.discovery = GammaDiscovery(config.discovery, client=self._httpx)
        self.scheduler = MarketScheduler(
            config.discovery,
            self.discovery,
            self.bus,
            self.clock,
            self.assets,
            on_result=self._on_market_result,
        )

        self.feeds = self._build_feeds()
        for feed in self.feeds:
            self.health.register(feed.health)

        self.writer = CaptureWriter(
            self.bus,
            config.storage.capture_dir,
            resolve_open_slugs=self._open_slugs_for_asset,
            resolve_token=self._token_meta_for_capture,
            compress=config.storage.compress_captures,
        )

        self.execution: ExecutionBackend = self._build_execution_backend()

        self._tick_sub = self.bus.subscribe("state-ticks", maxsize=50_000)
        self._book_sub = self.bus.subscribe("state-books", maxsize=50_000)
        self._market_sub = self.bus.subscribe("state-markets", maxsize=1_000)
        self._opening_sub = self.bus.subscribe("state-openings", maxsize=1_000)
        self._tasks: list[asyncio.Task[None]] = []
        self._completed_markets_cache = 0

    # -------------------------------------------------------------- wiring

    def _build_feeds(self) -> list[WebSocketFeed]:
        cfg = self.config.feeds
        feeds: list[WebSocketFeed] = []
        common = dict(
            reconnect_initial_delay_s=cfg.reconnect_initial_delay_s,
            reconnect_max_delay_s=cfg.reconnect_max_delay_s,
            heartbeat_timeout_s=cfg.heartbeat_timeout_s,
        )
        if cfg.chainlink_streams_enabled:
            feeds.append(
                ChainlinkStreamsFeed(
                    self.bus,
                    cfg.chainlink_streams_ws_url,
                    cfg.chainlink_streams_api_key,
                    cfg.chainlink_streams_api_secret,
                    cfg.chainlink_stream_feed_ids,
                    **common,
                )
            )
        else:
            feeds.append(RtdsChainlinkFeed(self.bus, cfg.rtds_url, self.assets, **common))

        if cfg.binance_spot.enabled:
            symbols = {a: s for a, s in cfg.binance_spot.symbols.items() if a in self.assets}
            if symbols:
                feeds.append(
                    BinanceFeed(
                        self.bus,
                        cfg.binance_spot_ws,
                        symbols,
                        source=FeedSource.BINANCE_SPOT,
                        **common,
                    )
                )
        if cfg.binance_futures.enabled:
            symbols = {a: s for a, s in cfg.binance_futures.symbols.items() if a in self.assets}
            if symbols:
                feeds.append(
                    BinanceFeed(
                        self.bus,
                        cfg.binance_futures_ws,
                        symbols,
                        source=FeedSource.BINANCE_FUTURES,
                        **common,
                    )
                )
        if cfg.coinbase.enabled:
            symbols = {a: s for a, s in cfg.coinbase.symbols.items() if a in self.assets}
            if symbols:
                feeds.append(CoinbaseFeed(self.bus, cfg.coinbase_ws, symbols, **common))
        if cfg.okx.enabled:
            symbols = {a: s for a, s in cfg.okx.symbols.items() if a in self.assets}
            if symbols:
                feeds.append(OkxFeed(self.bus, cfg.okx_ws, symbols, **common))

        self.clob_market = ClobMarketFeed(self.bus, cfg.clob_ws_url, **common)
        feeds.append(self.clob_market)

        self.clob_user: ClobUserFeed | None = None
        if self.mode in (TradingMode.LIVE, TradingMode.SHADOW) and self.config.execution.api_key:
            self.clob_user = ClobUserFeed(
                self.bus,
                cfg.clob_ws_url,
                self.config.execution.api_key,
                self.config.execution.api_secret,
                self.config.execution.api_passphrase,
                token_meta=self.tracker.token_meta,
                on_order_ack=lambda order_id, ns: self.delay_tracker.on_acknowledged(order_id, ns),
                **common,
            )
            feeds.append(self.clob_user)
        return feeds

    def _build_execution_backend(self) -> ExecutionBackend:
        if self.mode in (TradingMode.LIVE, TradingMode.SHADOW):
            client = build_clob_client(self.config.execution)
            return ClobExecutor(
                client,
                self.config.execution,
                self.delay_tracker,
                shadow=self.mode is TradingMode.SHADOW,
            )
        # OBSERVE and PAPER both use the paper simulator; OBSERVE simply never
        # reaches submit() because the run loop below only calls execution in
        # PAPER/SHADOW/LIVE.
        params = PaperFillParams(fee_rate=self.config.risk.taker_fee_rate)
        return PaperExecutor(
            self.bus,
            params,
            book_at=self._live_book_at,
            market_end_ts=lambda intent: self.tracker.markets[intent.market_slug].market.end_ts,
            now_s=self.clock.now_s,
        )

    def _live_book_at(self, intent: OrderIntent, _arrival_ts: float) -> BookSnapshot | None:
        view = self.tracker.markets.get(intent.market_slug)
        return view.book(intent.side) if view is not None else None

    # ---------------------------------------------------------- resolvers

    def _open_slugs_for_asset(self, asset: Asset) -> list[str]:
        now_s = self.clock.now_s()
        return [
            v.market.slug
            for v in self.tracker.markets.values()
            if v.market.asset is asset and v.market.start_ts - 60 <= now_s <= v.market.end_ts + 15
        ]

    def _token_meta_for_capture(self, token_id: str) -> tuple[str, Asset] | None:
        meta = self.tracker.token_meta(token_id)
        if meta is None:
            return None
        slug, asset, _side = meta
        return slug, asset

    async def _on_market_result(self, result: MarketResult, state: IntervalState) -> None:
        async with self.db.session() as session:
            repo = Repository(session)
            await repo.save_market(state.market)
            await repo.save_result(result, complete=True)
            closed = self.writer.close_market(result.market_slug)
            if closed is not None:
                path, events = closed
                await repo.register_capture_file(result.market_slug, path, events, True)
        metrics.MARKETS_COMPLETED.labels(asset=result.asset.value).inc()
        self.writer.on_result(result)

    # -------------------------------------------------------------- runtime

    async def start(self) -> None:
        await self.db.create_all()
        async with self.db.session() as session:
            self._completed_markets_cache = await Repository(session).count_completed_markets()
        self._enforce_live_gate()

        self.drift.start()
        await self.drift.measure_once()
        self.scheduler.start()
        for feed in self.feeds:
            feed.start()
        self.writer.start()
        self._tasks.append(asyncio.create_task(self._state_pump(), name="state-pump"))
        self._tasks.append(asyncio.create_task(self._eval_loop(), name="eval-loop"))
        metrics.start_metrics_server(self.config.observability.metrics_port)

    def _enforce_live_gate(self) -> None:
        if self.mode is not TradingMode.LIVE:
            return
        confirmed = os.environ.get(LIVE_CONFIRM_ENV) == LIVE_CONFIRM_VALUE
        enough_history = self._completed_markets_cache >= MIN_RECORDED_MARKETS_FOR_LIVE
        if not (confirmed and enough_history):
            logger.error(
                "LIVE mode blocked (confirmed=%s, completed_markets=%d/%d); falling back to SHADOW",
                confirmed,
                self._completed_markets_cache,
                MIN_RECORDED_MARKETS_FOR_LIVE,
            )
            self.mode = TradingMode.SHADOW
            self.strategy.mode = TradingMode.SHADOW

    async def _state_pump(self) -> None:
        async def drain_ticks() -> None:
            async for event in self._tick_sub:
                self.tracker.on_tick(event)  # type: ignore[arg-type]
                self.scheduler.on_settlement_tick(event)  # type: ignore[arg-type]

        async def drain_books() -> None:
            async for event in self._book_sub:
                self.tracker.on_book(event)  # type: ignore[arg-type]

        async def drain_markets() -> None:
            async for event in self._market_sub:
                self.tracker.on_market(event)  # type: ignore[arg-type]
                refs = [
                    TokenRef(v.market.up_token_id, v.market.asset, Side.UP, v.market.tick_size)
                    for v in self.tracker.markets.values()
                    if v.market.up_token_id
                ] + [
                    TokenRef(v.market.down_token_id, v.market.asset, Side.DOWN, v.market.tick_size)
                    for v in self.tracker.markets.values()
                    if v.market.down_token_id
                ]
                self.clob_market.set_tokens(refs)

        async def drain_openings() -> None:
            async for event in self._opening_sub:
                self.tracker.on_opening(event)  # type: ignore[arg-type]

        await asyncio.gather(drain_ticks(), drain_books(), drain_markets(), drain_openings())

    async def _eval_loop(self) -> None:
        while True:
            now_s = self.clock.now_s()
            now_ns = self.clock.now_ns()
            health_report = self.health.report(now_ns)
            for asset in self.assets:
                outcome = self.strategy.evaluate_asset(
                    asset, now_s=now_s, now_ns=now_ns, health=health_report
                )
                if outcome is None:
                    continue
                signal, intent = outcome
                async with self.db.session() as session:
                    await Repository(session).save_signal(signal)
                if intent is None or self.mode is TradingMode.OBSERVE:
                    continue
                await self._try_execute(intent, signal)
            await asyncio.sleep(EVAL_INTERVAL_S)

    async def _try_execute(self, intent: OrderIntent, signal: Signal) -> None:
        view = self.tracker.markets.get(signal.market_slug)
        state = self.tracker.assets.get(intent.asset)
        if view is None or state is None:
            return
        now_s = self.clock.now_s()
        now_ns = self.clock.now_ns()
        precheck = pre_submission_check(
            intent,
            signal,
            view,
            state,
            now_s=now_s,
            now_ns=now_ns,
            exec_config=self.config.execution,
            risk_config=self.config.risk,
            fresh_probability=signal.probability,
        )
        if not precheck.ok:
            logger.info("precheck aborted order for %s: %s", signal.id, precheck.problems)
            record = OrderRecord(
                intent=intent,
                status=OrderStatus.ABORTED_PRECHECK,
                detail="; ".join(precheck.problems),
            )
            self.writer.on_order(record)
            return
        view.orders_submitted += 1
        record = await self.execution.submit(intent)
        self.writer.on_order(record)
        async with self.db.session() as session:
            await Repository(session).save_order(record)
        if record.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            view.stake_usd += intent.max_notional
            self.risk.record_fill(intent.max_notional)
        if record.order_id:
            self.delay_tracker.on_submitted(record.order_id, record.submitted_ns or time.time_ns())

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for feed in self.feeds:
            await feed.stop()
        await self.scheduler.stop()
        await self.writer.stop()
        await self.drift.stop()
        await self.discovery.close()
        await self._httpx.aclose()
        await self.redis.close()
        await self.db.close()
