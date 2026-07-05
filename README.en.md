# B11 Auto Stop-Loss / Take-Profit + Position Sizing (Enhanced)

Automated stop-loss, take-profit, and single-name position-cap management for A-shares and futures. Supports next-day gap-up take-profit (+5%), next-day gap-down stop-loss (-3%), forced liquidation once holding spans ≥ 2 trading days, and reduce-to-cap when a single name's notional exceeds 10% of total equity. Emits the standard 8-field position adjustment order.

> This release is the **enhanced fix** of the previous 52/100 audited version, addressing all six identified defects (E1–E6). **v2 upgrades this BUILD to a hybrid type** — the shipped `production/trade.parquet` cache backs the trading calendar, and two new agent-facing APIs (`inspect_calendar()` / `refresh_calendar()`) let higher-level agents own the cache lifecycle.

## ⚠️ Disclaimer

- **Research & educational use only.** This skill is a quantitative research tool. It is **not** investment advice, financial advice, or a trading recommendation.
- **No profit guarantee.** Backtest or simulation results do not represent live performance. Past performance does not predict future results. Users bear all trading risk.
- **Risk boundaries.** The tool does not model liquidity, price limits (up/down), trading halts, slippage, or auction phases. The trading calendar defaults to the A-share convention (`panda_data` SH exchange); HK and US markets are not supported. Long-only.
- **Not officially endorsed.** This is a QuantSkills community project. It has not been audited or certified and must not be treated as a production-grade tool endorsed by QuantSkills.

## Layout

```
├── SKILL.md                                ← skill spec (metadata / decision rules / Agent SOP)
├── README.md                               ← Chinese version
├── README.en.md                            ← this file
├── LICENSE                                 ← GPL-3.0-only
├── INSTALL.md                              ← 5-platform install guide
├── requirements.txt                        ← dependency notes (panda_data required + pyarrow)
├── scripts/
│   ├── build.py                            ← main entry (run / validate_input / inspect_calendar / refresh_calendar)
│   ├── test.py                             ← self-test (62 cases)
│   ├── build_calendar.py                   ← standalone bootstrap: fetch calendar → write production/trade.parquet
│   └── _verify_prod.py                     ← production-path verifier
├── references/
│   └── api_guide.md                        ← API guide (with change log + Agent SOP)
└── production/
    └── trade.parquet                       ← trading calendar cache (today−3y → today+1y, snappy, ~18.5KB)
```

## Quick Start

```bash
# 1) Bootstrap the trading-calendar cache (first run only; needs PANDA_USERNAME/PANDA_PASSWORD)
python3 scripts/build_calendar.py

# 2) Unit tests (no external data required, 62 cases)
python3 scripts/test.py

# 3) Main entry demo
python3 scripts/build.py

# 4) Optional: production verifier (needs panda_data + env credentials)
python3 scripts/_verify_prod.py
```

## Agent Usage

v2 introduces two agent-facing APIs so higher-level agents can own calendar-cache lifecycle decisions:

```python
from scripts.build import inspect_calendar, refresh_calendar, run

# 1) Read-only inspection: cached range, day count, mtime
info = inspect_calendar()
# {'first_date': '2022-07-05', 'last_date': '2027-07-06', 'total_days': 971, 'mtime': '...'}

# 2) On-demand refresh: force=False skips when the range is still covered; True refetches
refresh_calendar(force=False)

# 3) Regular invocation
order = run(pos={"code": "600519", "entry_date": "2025-01-02", ...},
            config={"total_equity": 1_000_000})
```

Full 4-step SOP and 7-scenario decision table are in `SKILL.md` § Agent SOP.

## v2 Changelog

Seven changes since v1 (commit `ea1585e`):

1. **Trading calendar is a hard `panda_data` dependency.** The four v1 fallback entries (`config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]`) are removed; `panda_data.get_trade_cal` is the single source of truth.
2. **Automatic env-based login.** `build.py` reads `PANDA_USERNAME` / `PANDA_PASSWORD` and calls `init_token` on first use; missing credentials raise `RuntimeError` with a guidance link.
3. **New production artifact `production/trade.parquet`.** The BUILD is now hybrid — a local parquet cache backs the calendar to avoid per-call network round-trips.
4. **New bootstrap script `scripts/build_calendar.py`.** Fetches today−3y through today+1y and writes a snappy-compressed parquet (~18.5KB / 971 trading days).
5. **New agent APIs.** `inspect_calendar()` (read-only) and `refresh_calendar(force=False)` (idempotent refresh) expose cache state to callers.
6. **Complete schema doc + Agent SOP.** `SKILL.md` documents the parquet's 5-column schema, date format, four-step update flow, and a 7-scenario decision table.
7. **Tests expanded 49 → 62.** New coverage for parquet cache, `inspect_calendar`, and `refresh_calendar`; `pyarrow` absence is skipped gracefully.

## Core Design

1. **Five-level decision priority**: `guard (invalid → hold) → next-day take-profit (+5%) → next-day stop-loss (-3%) → forced close on ≥ 2 trading-day holding → reduce when single-name notional > 10% of total equity → hold`.
2. **Trading-day semantics (E1).** Entry day = trading day 0; `holding_trading_days` counts trading days spanned. Next-day = `holding_trading_days == 1`, forced close = `holding_trading_days >= 2`. Friday entry's "next day" is the following Monday (3 calendar days) — correctly recognised by the calendar.
3. **Position denominator (E2).** Ratio = notional / `total_equity` (option A: caller-provided total equity, **not** `available_cash`). Notional = `current_qty × open_price × multiplier` (A-shares multiplier = 1).
4. **Code classification (E3).** Strip `sh/sz/SH/SZ` prefix first; 6-digit numeric → A-share, otherwise → futures.
5. **Futures contract multipliers (E4).** Built-in table covers IF/IC/IH/IM/rb/cu etc.; unknown symbols must be overridden by `multiplier`.
6. **Robustness (E5).** NaN/inf prices, `total_equity ≤ 0`, and `today < entry_date` are all short-circuited to `hold`.
7. **Calendar single source of truth (v2).** `panda_data.get_trade_cal` is a hard dependency; `production/trade.parquet` provides the local persistence layer. All four v1 fallback entries are removed to eliminate cross-source drift.
8. **Pure Python stdlib for business logic**: `math / numbers / re / datetime / bisect`. Only the cache layer depends on `panda_data` + `pyarrow`.

## Supported Runtimes

See `INSTALL.md` for Claude Code, Codex, Cursor, Hermes, and OpenClaw setups.

## Acceptance

- **Tests**: `scripts/test.py` — **62 / 62 passing** (happy path, edge cases, exceptional input, E1–E6, plus v2 parquet-cache / `inspect_calendar` / `refresh_calendar`).
- **Enhancements delivered**:
  - E1 trading-day semantics (`panda_data.get_trade_cal` as sole source) ✅
  - E2 denominator switched to `total_equity` ✅
  - E3 code classification strips `sh/sz` prefix first ✅
  - E4 futures multiplier table + `multiplier` override ✅
  - E5 hardened guards (NaN/inf, non-positive equity, time reversal) ✅
  - E6 test suite expanded to 62 cases covering v2 additions ✅
- **v2 hybrid artifact**: `production/trade.parquet` (971 trading days / snappy / ~18.5KB) ships with the repo.
- **Production verifier**: `scripts/_verify_prod.py` — passes against real `panda_data.get_trade_cal` with env credentials.
- `build.py` runs standalone; `validate_input` / `inspect_calendar` / `refresh_calendar` APIs are complete.

## Known Limitations

1. Trading calendar defaults to A-shares (SH exchange). HK / US not supported.
2. No awareness of price limits, halts, or auction states.
3. Long-only. No short, hedge, spread, or calendar combos.
4. Unknown futures symbols require an explicit `multiplier`.
5. No liquidity, slippage, or market-impact modelling.

## Maintainer

- duanyong <hiduan@qq.com>
- Upstream org: QuantSkills (<https://github.com/quantskills>)
- License: GPL-3.0-only (see `LICENSE`).
