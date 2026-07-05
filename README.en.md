# B11 Auto Stop-Loss / Take-Profit + Position Sizing (Enhanced)

Automated stop-loss, take-profit, and single-name position-cap management for A-shares and futures. Supports next-day gap-up take-profit (+5%), next-day gap-down stop-loss (-3%), forced liquidation once holding spans ≥ 2 trading days, and reduce-to-cap when a single name's notional exceeds 10% of total equity. Emits the standard 8-field position adjustment order.

> This release is the **enhanced fix** of the previous 52/100 audited version, addressing all six identified defects (E1–E6) and adding a live production-path verifier.

## ⚠️ Disclaimer

- **Research & educational use only.** This skill is a quantitative research tool. It is **not** investment advice, financial advice, or a trading recommendation.
- **No profit guarantee.** Backtest or simulation results do not represent live performance. Past performance does not predict future results. Users bear all trading risk.
- **Risk boundaries.** The tool does not model liquidity, price limits (up/down), trading halts, slippage, or auction phases. The trading calendar defaults to the A-share convention (`panda_data` SH exchange); HK and US markets are not supported. Long-only.
- **Not officially endorsed.** This is a QuantSkills community project. It has not been audited or certified and must not be treated as a production-grade tool endorsed by QuantSkills.

## Layout

```
├── SKILL.md                                ← skill spec (metadata / decision rules)
├── README.md                               ← Chinese version
├── README.en.md                            ← this file
├── LICENSE                                 ← GPL-3.0-only
├── INSTALL.md                              ← 5-platform install guide
├── requirements.txt                        ← dependency notes (stdlib; panda_data optional)
├── scripts/
│   ├── build.py                            ← main entry (run / validate_input)
│   ├── test.py                             ← self-test (49 cases)
│   └── _verify_prod.py                     ← production-path verifier
└── references/
    └── api_guide.md                        ← API guide (with change log)
```

## Quick Start

```bash
# 1) Unit tests (zero-dependency)
python3 scripts/test.py

# 2) Main entry demo (zero-dependency)
python3 scripts/build.py

# 3) Optional: production verifier (needs panda_data + PANDA_USERNAME/PANDA_PASSWORD)
python3 scripts/_verify_prod.py
```

## Core Design

1. **Five-level decision priority**: `guard (invalid → hold) → next-day take-profit (+5%) → next-day stop-loss (-3%) → forced close on ≥ 2 trading-day holding → reduce when single-name notional > 10% of total equity → hold`.
2. **Trading-day semantics (E1).** Entry day = trading day 0; `holding_trading_days` counts trading days spanned. Next-day = `holding_trading_days == 1`, forced close = `holding_trading_days >= 2`. Friday entry's "next day" is the following Monday (3 calendar days) — correctly recognised by the calendar.
3. **Position denominator (E2).** Ratio = notional / `total_equity` (option A: caller-provided total equity, **not** `available_cash`). Notional = `current_qty × open_price × multiplier` (A-shares multiplier = 1).
4. **Code classification (E3).** Strip `sh/sz/SH/SZ` prefix first; 6-digit numeric → A-share, otherwise → futures.
5. **Futures contract multipliers (E4).** Built-in table covers IF/IC/IH/IM/rb/cu etc.; unknown symbols must be overridden by `multiplier`.
6. **Robustness (E5).** NaN/inf prices, `total_equity ≤ 0`, and `today < entry_date` are all short-circuited to `hold`.
7. **Layered calendar resolution (E1).** `pos["holding_trading_days"]` → `config["calendar"]` → `pos/config["trade_days"]` → `panda_data.get_trade_cal`. The first three are fully stdlib; the last is a scoped exception for production only.
8. **Pure Python standard library**: `math / numbers / re / datetime / bisect`. No pandas / numpy.

## Supported Runtimes

See `INSTALL.md` for Claude Code, Codex, Cursor, Hermes, and OpenClaw setups.

## Acceptance

- **Tests**: `scripts/test.py` — **49 / 49 passing** (happy path, edge cases, exceptional input, and all E1–E6 enhancements).
- **Enhancements delivered**:
  - E1 trading-day semantics with layered calendar fallback ✅
  - E2 denominator switched to `total_equity` ✅
  - E3 code classification strips `sh/sz` prefix first ✅
  - E4 futures multiplier table + `multiplier` override ✅
  - E5 hardened guards (NaN/inf, non-positive equity, time reversal) ✅
  - E6 test suite expanded to 49 cases covering new fields and edges ✅
- **Production verifier**: `scripts/_verify_prod.py` — passes against real `panda_data.get_trade_cal` with configured credentials.
- `build.py` runs standalone; `validate_input` performs schema-level checks.

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
