---
name: skill-b11-auto-stop-loss-take-profit
description: 当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈、次日低开止损、持仓满2交易日强平、单票名义仓位上限控制。基于交易日历判定（非自然日）。
tags: [quant, skill, 止盈止损, 仓位管理, A股, 期货]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-b11-auto-stop-loss-take-profit
  repository_url: https://github.com/quantskills/skill-b11-auto-stop-loss-take-profit
  project_type: skill
  collection: quant
  license: GPL-3.0-only
---

## 维护者
- duanyong <hiduan@qq.com>
- 上游组织：QuantSkills (https://github.com/quantskills)

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现，过去的表现不预示未来结果。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束。交易日历默认 A 股口径，港美股暂不支持。所有交易决策责任由使用者自行承担。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。


# B11 自动止盈止损+仓位管理（增强版）

> 本版本为对 52/100 验收版的增强修复，修复 6 项缺陷（E1-E6）：交易日语义、仓位分母、代码分类、期货乘数、健壮性、测试补全。详见 `references/api_guide.md`。

## 工具定位
- 工具类型：交易执行辅助型（调用型 BUILD）
- 解决问题：按入场日期和开盘价自动判断止盈、止损、强平，以及单票名义仓位上限控制
- 使用对象：交易 agent / 人工辅助决策 / Alpha 信号

## 适用场景
- 每日开盘后检查持仓是否需要止盈/止损（基于交易日历的「次日」判定）
- 持仓满 2 个交易日自动平仓
- 单票名义仓位超总权益 10% 时自动减仓（A股按市值、期货按 名义价值=数量×价格×合约乘数）

## 支持品种（E3：先剥离 sh/sz 前缀，6位数字优先判 A股）

| 类别 | 识别规则 | 最小交易单位 | 合约乘数 |
|---|---|---|---|
| A_STOCK | 剥离 sh/sz/SH/SZ 前缀后为 6 位纯数字（含 600036 / sh600036 / SZ000001 / 688xxx / ETF） | 100 股 | 1 |
| FUTURE | 剥离前缀后仍含字母（如 IF2406 / rb2410 / cu2401） | 1 手 | 见内置乘数表，可由 `multiplier` 覆盖 |

## 决策规则（优先级从高到低）

| 优先级 | 条件 | 动作 |
|---|---|---|
| 0 | 守卫：today<entry（交易日） / 价格 NaN-inf / total_equity<=0 | hold（标注异常） |
| 1 | 次日（holding_trading_days==1）且 浮盈 ≥ +5% | 止盈全平 → target=0 |
| 2 | 次日 且 浮亏 ≤ -3% | 止损全平 → target=0 |
| 3 | 持仓满 2 个交易日（holding_trading_days ≥ 2） | 强制平仓 → target=0（不做手数下取整） |
| 4 | 单票名义仓位占总权益 > 10%（严格 >，==10% 不动） | 减仓至 ≤10% 最近整百股/整手；floor 后<1单位或 target≥current 则 hold（不清仓） |
| 5 | 其他 | hold |

### 交易日语义（E1，⭐ 用户决策）
- **入场当天 = 第 0 个交易日**；`holding_trading_days` 为持仓跨越的交易日数。
- **「次日」= holding_trading_days == 1**（entry 的下一个交易日），止盈/止损仅在该日有效。
- **「持仓 2 日强平」= holding_trading_days ≥ 2**（即 T+2 开盘）。
- 周五入场的「次日」是下周一（自然日差 3），由交易日历正确识别——这是对原自然日实现的核心修复。

### 名义价值与仓位比（E2/E4，⭐ 用户决策）
- 仓位比 = 名义价值 / `total_equity`（方案A：调用方传入的总权益，**不再用 available_cash**）。
- 名义价值 = `current_qty × open_price × multiplier`（A股 multiplier=1）。
- `total_equity ≤ 0` 短路返回 hold（防除零）。

## 交易日历来源（E1：可注入 / 可降级）

按优先级解析，满足「测试零依赖、生产可接入」：

1. `pos["holding_trading_days"]`（每条持仓直接传交易日数，**最轻量、零依赖**）
2. `config["calendar"]`（注入实现 `holding_trading_days()` / `is_next_day()` 的对象，用于测试 stub）
3. `pos["trade_days"]` / `config["trade_days"]`（传入交易日序列 `["YYYY-MM-DD", ...]`，零三方依赖）
4. `panda_data.get_trade_cal`（生产兜底，**对纯标准库约束的定向例外**；沙箱无库时抛 ImportError，应改用上述方式）

## 输入

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| code | str | 是 | 品种代码（A股/期货） |
| entry_price | numbers.Real | 是 | 入场价（>0，非 NaN/inf） |
| entry_date | str | 是 | 入场日期 YYYY-MM-DD |
| current_qty | numbers.Integral | 是 | 当前持仓数量（>=0，兼容 numpy 整数） |
| open_price | numbers.Real | 是 | 当日开盘价（>0，非 NaN/inf） |
| today | str | 是 | 当前交易日 YYYY-MM-DD（须 >= entry_date） |
| total_equity | numbers.Real | 是 | **总权益（仓位比分母，方案A）**，非 NaN/inf；<=0 时返回 hold |
| available_cash | numbers.Real | 否 | 可用现金（保留字段，**不作分母**） |
| multiplier | numbers.Real | 否 | 期货合约乘数；缺省时查内置表，未知品种未传则报错；A股忽略 |
| holding_trading_days | int | 否 | 直接指定持仓交易日数（零依赖路径） |
| trade_days | list[str] | 否 | 该条持仓的交易日序列 |

## 输出

标准 8 字段调仓指令：

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str | 品种代码 |
| pnl_pct | float | 浮盈亏（小数形式，0.05 = +5%） |
| current_qty | int | 当前总持仓 |
| time | str | 当前日期 |
| action | str | "sell" / "hold" / "buy"（本工具不产生 buy） |
| qty_change | int | 负=减仓，0=不动 |
| target_qty | int | 目标持仓 |
| reason | str | 触发原因，含 `[B11]` 前缀 |

## 调用方式

```python
from scripts.build import run

# 方式一：直接传 holding_trading_days（零依赖，推荐用于已知交易日数的管线）
result = run({
    "code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
    "current_qty": 800, "open_price": 10.55, "today": "2026-06-22",
    "total_equity": 1_000_000, "holding_trading_days": 1,
})

# 方式二：传交易日序列
cfg = {"trade_days": ["2026-06-18", "2026-06-19", "2026-06-22", "2026-06-23"]}
result = run({...}, config=cfg)

# 方式三（生产）：内部接入 panda_data.get_trade_cal（无需传 trade_days）
result = run({...})  # 需 panda_data 可用

# 批量
results = run([pos1, pos2, pos3], config=cfg)
```

## 可被 Alpha 调用
- 是
- 调用限制：需提供 total_equity；期货需可解析合约乘数（内置表或传 multiplier）
- 依赖数据：调用方传入标准结构化数据 + 交易日历（可注入/降级）

## 是否需要生产结果
- 是否生成 `数据库.parquet`：否（调用型）

## 依赖
- Python 标准库（math, numbers, re, datetime, bisect）
- **定向例外**：交易日历可选接入 `panda_data.get_trade_cal`（生产路径）；测试与零依赖路径不需要

## Known Limitations
1. 不区分涨停/跌停/停牌状态
2. 交易日历默认 A股口径（panda_data 的 SH 交易所）；港美股暂不支持
3. 仅支持多头持仓
4. 内置期货乘数表覆盖常见品种，未知品种须由调用方传 multiplier
