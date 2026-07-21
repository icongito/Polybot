"""Polybot command-line entrypoint.

Subcommands map directly onto the spec's build-order phases:

    polybot discover            # Phase 1: print current/next markets per asset
    polybot record               # Phase 2-3: run feeds + discovery, OBSERVE mode
    polybot replay <files...>    # Phase 4: deterministic replay + paper execution
    polybot train                 # Phase 5: fit the empirical model from captures
    polybot report <files...>    # performance report over captures or a replay
    polybot run --mode <mode>    # Phase 6-7: full app in any trading mode
    polybot tui                  # live terminal dashboard (attaches to `run`)
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import signal
import sys
import time
from pathlib import Path

import numpy as np

from polybot.app import PolybotApp
from polybot.config import AppConfig, load_config
from polybot.discovery.gamma import GammaDiscovery, slug_for, window_start_ts
from polybot.discovery.validation import format_window
from polybot.models.core import Asset, TradingMode
from polybot.observability.logging import setup_logging
from polybot.pricing.empirical import train_logistic
from polybot.pricing.features import FEATURE_NAMES
from polybot.recording.reader import list_captures, open_capture
from polybot.replay.engine import ReplayEngine
from polybot.reporting.performance import build_report

logger = logging.getLogger(__name__)


def _parse_assets(value: str | None) -> list[Asset]:
    if not value:
        return list(Asset)
    return [Asset(a.strip().upper()) for a in value.split(",") if a.strip()]


async def cmd_discover(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    discovery = GammaDiscovery(config.discovery)
    assets = _parse_assets(args.assets)
    now = time.time()
    current_ts = window_start_ts(now, config.discovery.interval_seconds)
    next_ts = current_ts + config.discovery.interval_seconds
    try:
        for asset in assets:
            for label, ts in (("current", current_ts), ("next", next_ts)):
                market = await discovery.fetch_market(asset, ts)
                if market is None:
                    print(f"{asset.value:5s} {label:8s} slug={slug_for(asset, ts)} NOT FOUND")
                    continue
                print(
                    f"{asset.value:5s} {label:8s} {market.slug} "
                    f"tradable={market.tradable} window={format_window(market.start_ts, market.end_ts)} "
                    f"up_token={market.up_token_id[:12]}... down_token={market.down_token_id[:12]}..."
                )
                if not market.rules.valid:
                    print(f"      rule problems: {list(market.rules.problems)}")
    finally:
        await discovery.close()
    return 0


async def _run_app(config: AppConfig, *, with_tui: bool) -> int:
    app = PolybotApp(config)
    await app.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows

    try:
        if with_tui:
            from polybot.tui.dashboard import run_dashboard

            await run_dashboard(app, stop_event)
        else:
            await stop_event.wait()
    finally:
        await app.stop()
    return 0


async def cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    config.mode = TradingMode.OBSERVE
    if args.assets:
        config.assets = _parse_assets(args.assets)
    return await _run_app(config, with_tui=not args.no_tui)


async def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.mode:
        config.mode = TradingMode(args.mode)
    if args.assets:
        config.assets = _parse_assets(args.assets)
    return await _run_app(config, with_tui=not args.no_tui)


async def cmd_tui(args: argparse.Namespace) -> int:
    args.no_tui = False
    return await cmd_run(args)


async def cmd_replay(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    paths: list[str | Path] = []
    for pattern in args.files:
        matched = glob.glob(pattern)
        paths.extend(matched or [pattern])
    if not paths:
        print("no capture files matched", file=sys.stderr)
        return 1
    assets = _parse_assets(args.assets)
    engine = ReplayEngine(config, assets)
    result = await engine.run(paths)
    report = build_report(
        markets=result.results,
        signals=result.signals,
        orders=result.orders,
        fills=result.fills,
    )
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 0


async def cmd_report(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    paths: list[Path]
    if args.files:
        paths = [Path(p) for pattern in args.files for p in (glob.glob(pattern) or [pattern])]
    else:
        assets = [a.value.lower() for a in _parse_assets(args.assets)] if args.assets else None
        paths = []
        if assets:
            for asset in assets:
                paths.extend(list_captures(config.storage.capture_dir, asset))
        else:
            paths.extend(list_captures(config.storage.capture_dir))

    signals = []
    orders = []
    fills = []
    results = []
    from polybot.models.core import Fill, MarketResult, OrderRecord, Signal

    for path in paths:
        for env in open_capture(path):
            if env.t == "signal":
                signals.append(Signal.model_validate(env.data))
            elif env.t == "order":
                orders.append(OrderRecord.model_validate(env.data))
            elif env.t == "fill":
                fills.append(Fill.model_validate(env.data))
            elif env.t == "result":
                results.append(MarketResult.model_validate(env.data))

    report = build_report(markets=results, signals=signals, orders=orders, fills=fills)
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 0


async def cmd_train(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    assets = _parse_assets(args.assets)

    from polybot.models.core import BookSnapshot, MarketInfo, OpeningPrice, Tick
    from polybot.pricing.features import extract_features
    from polybot.pricing.state import PriceStateTracker

    all_paths: list[Path] = []
    for asset in assets:
        all_paths.extend(list_captures(config.storage.capture_dir, asset.value.lower()))
    if not all_paths:
        print("no captures found to train on", file=sys.stderr)
        return 1

    rows: list[list[float]] = []
    labels: list[float] = []

    for path in sorted(all_paths):
        envelopes = list(open_capture(path))
        winner = None
        for env in envelopes:
            if env.t == "result":
                from polybot.models.core import MarketResult

                result = MarketResult.model_validate(env.data)
                winner = result.winner
        if winner is None:
            continue
        label = 1.0 if winner.value == "up" else 0.0

        tracker = PriceStateTracker(
            assets,
            vol_halflife_s=config.model.vol_ewma_halflife_s,
            vol_floor=config.model.vol_floor_per_sqrt_s,
            vol_min_ticks=config.model.vol_sample_min_ticks,
        )
        market_view = None
        for env in envelopes:
            if env.t == "market":
                m = MarketInfo.model_validate(env.data)
                tracker.on_market(m)
                market_view = tracker.markets[m.slug]
            elif env.t == "opening":
                tracker.on_opening(OpeningPrice.model_validate(env.data))
            elif env.t == "tick":
                tracker.on_tick(Tick.model_validate(env.data))
                if market_view is not None and market_view.opening is not None:
                    asset_state = tracker.assets[market_view.market.asset]
                    now_s = env.recv_ns / 1e9
                    features = extract_features(
                        asset_state,
                        market_view,
                        now_s=now_s,
                        now_ns=env.recv_ns,
                        max_exchange_age_s=config.risk.max_exchange_age_s,
                    )
                    if features is not None:
                        rows.append(features.as_list())
                        labels.append(label)
            elif env.t == "book":
                tracker.on_book(BookSnapshot.model_validate(env.data))

    if len(rows) < config.model.empirical_min_training_samples:
        print(
            f"only {len(rows)} training samples (< {config.model.empirical_min_training_samples}); "
            "recording more markets before training.",
            file=sys.stderr,
        )
        return 1

    model = train_logistic(np.asarray(rows), np.asarray(labels))
    model.save(config.model.empirical_model_path)
    print(
        f"trained on {len(rows)} samples ({len(all_paths)} markets); saved to "
        f"{config.model.empirical_model_path}"
    )
    print(f"features: {list(FEATURE_NAMES)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polybot")
    parser.add_argument("--config", default=None, help="path to YAML config")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--no-json-logs", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="discover current/next markets per asset")
    p_discover.add_argument("--assets", default=None)
    p_discover.set_defaults(func=cmd_discover)

    p_record = sub.add_parser("record", help="run feeds + discovery in OBSERVE mode")
    p_record.add_argument("--assets", default=None)
    p_record.add_argument("--no-tui", action="store_true")
    p_record.set_defaults(func=cmd_record)

    p_run = sub.add_parser("run", help="run the full app in a given trading mode")
    p_run.add_argument("--mode", choices=[m.value for m in TradingMode], default=None)
    p_run.add_argument("--assets", default=None)
    p_run.add_argument("--no-tui", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_tui = sub.add_parser("tui", help="launch the live terminal dashboard (alias for `run`)")
    p_tui.add_argument("--mode", choices=[m.value for m in TradingMode], default=None)
    p_tui.add_argument("--assets", default=None)
    p_tui.set_defaults(func=cmd_tui)

    p_replay = sub.add_parser("replay", help="deterministic replay + paper execution over captures")
    p_replay.add_argument("files", nargs="+", help="capture file(s) or glob pattern(s)")
    p_replay.add_argument("--assets", default=None)
    p_replay.set_defaults(func=cmd_replay)

    p_report = sub.add_parser("report", help="performance report over recorded captures")
    p_report.add_argument(
        "files", nargs="*", help="capture files/globs (default: all under capture_dir)"
    )
    p_report.add_argument("--assets", default=None)
    p_report.set_defaults(func=cmd_report)

    p_train = sub.add_parser("train", help="fit the empirical probability model from captures")
    p_train.add_argument("--assets", default=None)
    p_train.set_defaults(func=cmd_train)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level, json_output=not args.no_json_logs)
    try:
        return int(asyncio.run(args.func(args)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
