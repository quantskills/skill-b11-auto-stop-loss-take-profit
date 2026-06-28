# B11 Auto Stop-Loss / Take-Profit + Position Sizing

Use this skill when you need automated stop-loss, take-profit, and position sizing for A-shares and futures positions. Supports next-day gap-up take-profit, next-day gap-down stop-loss, forced liquidation on holding timeout, and single-stock position cap.

## ⚠️ Disclaimer

- **Research & Educational Use Only**: This skill is a quantitative trading research tool and does NOT constitute investment advice, financial advice, or trading recommendations of any kind.
- **No Guaranteed Returns**: Backtest or simulation results do not represent actual trading performance. Users assume all trading risks.
- **Risk Boundaries**: This tool does not account for market liquidity, price limits, trading halts, or slippage. Dates are calculated as calendar days and may misjudge holding periods on non-trading days.
- **No Official Endorsement**: This is a QuantSkills community project. It has not been professionally audited or certified by any regulatory body.

## Directory Structure

```
├── SKILL.md                                ← Skill specification
├── README.md                               ← Chinese README
├── README.en.md                            ← This file
├── LICENSE                                 ← GPL-3.0
├── INSTALL.md                              ← Multi-platform install guide
├── requirements.txt                        ← Dependency declaration
├── scripts/
│   ├── build.py                            ← Main entry point (run / validate_input)
│   └── test.py                             ← Self-test script
└── references/
    └── api_guide.md                        ← API reference
```

## Quick Start

```bash
cd scripts
python3 build.py
python3 test.py
```

## Core Design

1. **Four-level Priority**: Next-day take-profit (+5%) → Next-day stop-loss (-3%) → Held ≥2 days force close → Single-stock >10% reduce. Quantities are rounded down to the asset's minimum trading unit (100 shares for A-shares, 1 contract for futures).

2. **Holding Days Include Entry Date**: Entry date = Day 1, T+1 = Day 2 triggers next-day rules.

3. **Shared A-share + Futures Logic**: Unified date calculation and P&L determination; asset classes differ only in minimum trading unit.

4. **Pure Python, Zero Dependencies**: Uses only the Python standard library (datetime, re, json). No pandas, numpy, or other third-party packages.

## Supported Runtimes

| Platform | Install Guide |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## Verification Status

- build.py runs independently ✅
- validate_input checks ✅
- test.py covers normal inputs, edge cases, and error conditions ✅

## Limitations & Future Work

| Limitation | Detail | Plan |
|---|---|---|
| No circuit breaker / halt awareness | Orders may be unexecutable on trigger day | Integrate market status flags |
| Calendar day calculation | May misjudge holding days on non-trading days | Integrate trading calendar |
| Long-only | No short / hedge positions | Future extension |
| Single currency per asset | Caller handles FX conversion | Integrate FX rates |
