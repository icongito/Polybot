# Polybot

An automated trading bot for Polymarket's rolling **five-minute crypto
"Up or Down"** markets — BTC, ETH, SOL, XRP, DOGE, BNB, HYPE.

Polybot does **not** trade the visible Polymarket percentage. It estimates
`P(closing Chainlink price >= opening Chainlink price)` from a conservative
ensemble of a volatility-diffusion model and an empirical model trained on
recorded history, walks the real order book to find an executable price, and
only trades when that price is materially below the estimated probability
after fees, slippage, execution delay, feed latency, and model uncertainty.
Leading exchange feeds (Binance, Coinbase, OKX) are used only to anticipate
the *next* Chainlink print — the market always settles against the market's
own declared Chainlink Data Stream, never against an exchange price.

Sports markets, political markets, and fixed-target Above/Below markets are
out of scope for v1.

## Why this design is cheap to run

- Every feed the bot uses by default is a **free, public** endpoint:
  Polymarket's RTDS relay (`crypto_prices_chainlink`), the Polymarket CLOB
  websocket, and public Binance/Coinbase/OKX market-data sockets. Direct paid
  Chainlink Data Streams credentials are entirely optional — set them and the
  bot switches feeds automatically; leave them unset and RTDS (which carries
  the exact same settlement price) is used instead.
- The terminal dashboard (`polybot tui`) does zero extra work: it only reads
  state the trading loop already computes and holds in memory. No additional
  API calls, no duplicate model evaluation.
- No cloud LLM calls anywhere in the trading path — the probability models
  are closed-form statistics (Black-Scholes-style diffusion) and a small
  hand-trained logistic regression, both cheap enough to evaluate every
  250ms on a laptop.
- Local: Postgres + Redis + Prometheus via Docker Compose, no managed
  services required.

## Safety model

The bot starts in **OBSERVE** mode and stays there until you explicitly
choose otherwise:

| Mode | Behavior |
|---|---|
| `observe` (default) | Feeds + discovery + signal generation only. No orders, real or simulated. |
| `paper` | Signals are executed against a simulated fill model (taker delay, stale-order cancellation, partial fills, fees, slippage) over the live book. |
| `shadow` | Builds and signs a real order and runs every validation, then stops **before** sending it. Used to measure real submission latency. |
| `live` | Submits real orders. **Disabled by default** — see below. |

LIVE mode requires *both*:
1. The environment variable `POLYBOT_LIVE_CONFIRM=I_UNDERSTAND_LIVE_TRADING_RISKS`, and
2. At least **1,000 completed, recorded five-minute markets** in the database.

Either condition missing silently downgrades the run to `shadow` (never to
`live`) and logs why. There is no leverage, no martingale/loss-chasing
sizing, no averaging down, and no unbounded retries anywhere in the code —
position sizing comes only from the fixed risk limits in
`polybot/risk/engine.py`. A kill switch (a Redis key or a local file) halts
new orders immediately.

## Architecture

```
polybot/
  discovery/    Gamma API market discovery, resolution-rule validation, interval scheduler
  feeds/        Chainlink Data Streams, RTDS, Binance/Coinbase/OKX, Polymarket CLOB (market + user)
  pricing/      realized vol, volatility-baseline model, empirical model, conservative ensemble
  strategy/     depth-walked edge calculation, endgame (final-seconds) gating
  risk/         every configured limit + kill switch + geo gate
  execution/    live (py-clob-client), shadow, paper backends + pre-submission recheck + delay measurement
  recording/    append-only NDJSON(.gz) capture of every event, one file per market interval
  replay/       deterministic tick-by-tick replay + paper execution, no lookahead
  reporting/    performance report (fill rate, accuracy, PnL, edge, latency, breakdowns)
  persistence/  SQLAlchemy 2.x models + Alembic migrations, Redis hot state
  tui/          live terminal dashboard (Textual)
  app.py        wires everything together for one running mode
  cli.py        polybot ... command entrypoints
```

Every market's resolution rules are fetched and validated individually
(`discovery/validation.py`) — the bot never assumes all markets share the
same tie-breaking or settlement conventions; a market that fails validation
is recorded but never traded.

## Setup

```bash
cp .env.example .env          # fill in credentials only when you need paper/shadow/live
docker compose up -d postgres redis prometheus
uv pip install -e ".[dev]"    # or: pip install -e ".[dev]"
alembic upgrade head
```

## Terminal UI

```bash
polybot record          # OBSERVE mode with the live dashboard (default)
polybot tui --mode paper
polybot run --mode shadow --no-tui   # headless, e.g. under systemd/Docker
```

The dashboard is read-only and adds no load of its own: a light (parchment,
not white) color theme, a live market table with a per-asset countdown that
turns amber inside the endgame window and red inside the hard cutoff, a
feed-health panel with colored status dots per source, a scrolling
trade/reject signal log, and an animated heartbeat in the header that is
also a genuine activity check — it goes from a green spinning pulse to a
static red "STALE" the moment feed messages actually stop arriving, not on
a fixed cosmetic timer.

Press `q` or `Ctrl+C` to quit (shuts the whole app down cleanly, feeds
included). Recommended terminal width: 150+ columns.

## CLI reference

```bash
polybot discover                       # Phase 1: print current/next market per asset
polybot record [--no-tui]              # Phase 2-3: feeds + discovery, OBSERVE mode
polybot replay <files-or-globs...>     # Phase 4: deterministic replay + paper execution
polybot train                          # Phase 5: fit the empirical model from recorded captures
polybot report [<files-or-globs...>]   # performance report over captures (default: everything recorded)
polybot run --mode {observe,paper,shadow,live} [--no-tui]   # Phase 6-7
polybot tui [--mode ...]               # alias for `run` with the dashboard forced on
```

All commands accept `--assets BTC,ETH,SOL` to scope to a subset, and
`--config path/to.yaml` to point at a config file other than
`config/default.yaml`.

## Recommended runbook (matches the spec's build order)

1. `polybot discover` — confirm markets resolve and validate for every asset.
2. `polybot record` — run OBSERVE for real, uninterrupted, until you have
   several hundred to 1,000+ complete markets captured under `data/capture/`.
3. `polybot replay data/capture/**/*.ndjson.gz` and `polybot report` — sanity
   check the deterministic replay/paper-fill model against what was recorded.
4. `polybot train` — fit the empirical model once you have enough samples
   (`model.empirical_min_training_samples`, default 500 feature rows).
5. `polybot run --mode shadow` — verify real submission latency and that
   every precheck passes, without ever sending an order.
6. Only after `polybot report` shows positive net expectancy on realistic
   fees/slippage/delay/failed-fill assumptions **and** the 1,000-market/​
   `POLYBOT_LIVE_CONFIRM` gate is satisfied: `polybot run --mode live`.

## Development

```bash
mypy src/                # strict mode
ruff check src/ tests/
ruff format --check src/ tests/
pytest
```

## Configuration

See `config/default.yaml` for every tunable (risk limits, endgame window,
feed URLs, per-asset exchange symbol maps) and `.env.example` for the
`POLYBOT_*` environment-variable overrides, including execution credentials
and the LIVE-mode confirmation variable.
