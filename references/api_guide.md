# B11 API 接口文档（增强版）

> 本版本修复 6 项缺陷（E1-E6）。核心契约变更：① 仓位分母改为 `total_equity`；② 期货按合约乘数计名义价值；③ 代码分类先剥离 sh/sz 前缀；④ 交易日历替代自然日；⑤ 健壮性加固（守卫/NaN/numpy 类型）。

## 调用入口

```python
from scripts.build import run, validate_input
```

### `run(input_data, config=None)`

- **入参**：`dict`（单条）或 `list[dict]`（批量）
- **config**（可选 dict）：
  - `config["calendar"]`：注入交易日历对象（实现 `holding_trading_days(entry,today)` 与 `is_next_day(entry,today)`）
  - `config["trade_days"]`：全局交易日序列 `["YYYY-MM-DD", ...]`
- **返回**：`dict`（单条）或 `list[dict]`（批量）
- **异常**：`ValueError`（校验失败 / 未知期货品种乘数缺失）、`TypeError`（入参类型错误）、`ImportError`（生产路径需 panda_data 但不可用）

### `validate_input(pos)`

- **入参**：`dict`
- **返回**：`(bool, str)` — (是否通过, 错误信息)

## 输入字段规范

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| code | str | 是 | A股代码 / 期货代码（可分类，否则报错） |
| entry_price | numbers.Real | 是 | > 0，非 NaN/inf（兼容 numpy.float） |
| entry_date | str | 是 | YYYY-MM-DD |
| current_qty | numbers.Integral | 是 | >= 0，非 bool（兼容 numpy.int） |
| open_price | numbers.Real | 是 | > 0，非 NaN/inf |
| today | str | 是 | YYYY-MM-DD，须 >= entry_date |
| **total_equity** | numbers.Real | **是** | 仓位比分母（方案A）；非 NaN/inf；**<=0 运行时返回 hold**（校验放行，运行守卫） |
| available_cash | numbers.Real | 否 | 保留字段，**不作分母**；若提供须为有限实数 |
| multiplier | numbers.Real | 否 | 期货合约乘数（>0）；缺省查内置表；未知品种未传则报错；A股忽略 |
| holding_trading_days | int | 否 | 直接指定持仓交易日数（零依赖路径，优先级最高） |
| trade_days | list[str] | 否 | 该条持仓交易日序列 |

### 交易日历解析优先级（E1）

1. `pos["holding_trading_days"]`（显式传入，零依赖）
2. `config["calendar"]`（注入对象）
3. `pos["trade_days"]`（该条交易日序列）
4. `config["trade_days"]`（全局交易日序列）
5. `panda_data.get_trade_cal`（生产兜底，定向例外）

> 交易日语义：entry 当天 = 第 0 个交易日；`holding_trading_days==1` 为「次日」；`>=2` 触发强平。

## 输出字段规范

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str | 品种代码（原样返回） |
| pnl_pct | float | 浮盈亏（小数，0.05 = +5%） |
| current_qty | int | 当前总持仓 |
| time | str | 当前日期 |
| action | str | `"sell"` / `"hold"`（不产生 buy） |
| qty_change | int | 调仓变化量（负=卖出，0=不动） |
| target_qty | int | 目标持仓数量 |
| reason | str | 触发原因，格式 `[B11]<规则名> <详情>` |

## reason 前缀说明

| 前缀 | 含义 |
|---|---|
| `[B11]次日高开止盈` | 次日（交易日）浮盈 ≥ +5% |
| `[B11]次日低开止损` | 次日浮亏 ≤ -3% |
| `[B11]持仓N个交易日≥2强制平仓` | 持仓满 2 交易日 |
| `[B11]单票仓位X%>10% 减仓至...` | 名义仓位超限 |
| `[B11]hold 仓位X%超限但减仓后不足1单位/无需减` | 超限但减仓会退化清仓 → 保持原仓（E5） |
| `[B11]hold 总权益非正...` | total_equity<=0 守卫（E2） |
| `[B11]hold today 早于 entry_date...` | today<entry 守卫（E5） |
| `[B11]hold 价格为 NaN/inf...` | 价格异常守卫（E5） |
| `[B11]hold 持仓N交易日 pnl=... 仓位X%` | 无触发 |

## 品种识别规则（E3）

| 类型 | 匹配规则 | 最小单位 | 乘数 | 示例 |
|---|---|---|---|---|
| A股 | 剥离 sh/sz/SH/SZ 前缀后 6 位纯数字 | 100 | 1 | `600036`, `sh600036`, `SZ000001`, `688981`, `510300` |
| 期货 | 剥离前缀后仍含字母 + 数字月份 | 1 | 内置表/传入 | `IF2406`, `rb2410`, `cu2401` |

> 修复点：原 `^[a-z]{1,3}\d+$` 会把 `sh600036` 误判期货并产出 909 股等非整百委托；现先归一化前缀、6 位数字优先判 A股，确保整百委托。

## 期货合约乘数表（E4，内置，可由 multiplier 覆盖）

| 品种前缀 | 乘数 | 说明 |
|---|---|---|
| IF / IH | 300 | 沪深300 / 上证50 股指 |
| IC / IM | 200 | 中证500 / 中证1000 股指 |
| rb / hc | 10 | 螺纹钢 / 热卷（吨/手） |
| cu / al / zn / pb | 5 | 铜/铝/锌/铅 |
| au | 1000 | 黄金 |
| ag | 15 | 白银 |
| ...（见 build.py FUTURE_MULTIPLIER） | | 覆盖 50+ 常见品种 |

> 未知品种且未传 `multiplier` → 抛 `ValueError`（不静默用 1，避免仓位上限失效）。

## 名义价值与仓位比（E2/E4）

```
名义价值 = current_qty × open_price × multiplier   # A股 multiplier=1
仓位比   = 名义价值 / total_equity                 # 分子分母同口径
触发减仓 = 仓位比 > 10%（严格大于；==10% 不动）
减仓目标 = floor(total_equity × 10% / (open_price × multiplier)) 到最近整百股/整手
保护     = 目标 floor 后 <1单位 或 目标 >= current → hold（不退化清仓，E5）
```
