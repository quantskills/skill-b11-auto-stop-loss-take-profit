# B11 API 接口文档

> 核心契约：① 仓位分母 = `total_equity`；② 期货按合约乘数计名义价值；③ 代码分类先剥离 sh/sz 前缀；④ **交易日历唯一来源 = `panda_data.get_trade_cal`（硬依赖）**；⑤ 健壮性加固（守卫/NaN/numpy 类型）。

## 前置依赖（必读）

本工具**强依赖 `panda_data`** 提供交易日历。使用前必须完成：

```bash
# 1. 安装
pip install panda_data

# 2. 配置环境变量（写入 ~/.zshrc / ~/.bashrc 后 source）
export PANDA_USERNAME=<your_username>
export PANDA_PASSWORD=<your_password>
```

`build.py` 首次调用交易日历时自动读取 env 并 `panda_data.init_token(username, password)` 登录，模块级标记幂等，同一进程内不重复登录。

### 依赖缺失错误消息

| 缺失项 | 错误类型 | 消息示例 |
|---|---|---|
| `panda_data` 包 | `RuntimeError` | `B11 需要 panda_data 提供交易日历。请先安装：pip install panda_data 再在环境变量中配置：export PANDA_USERNAME=... export PANDA_PASSWORD=...` |
| `PANDA_USERNAME` / `PANDA_PASSWORD` env | `RuntimeError` | `B11 需要 PANDA_USERNAME / PANDA_PASSWORD 环境变量以登录 panda_data。请在 shell 配置文件（如 ~/.zshrc / ~/.bashrc）中添加：export PANDA_USERNAME=... export PANDA_PASSWORD=... 然后重新打开终端或 source 该文件。` |

## 调用入口

```python
from scripts.build import run, validate_input
```

### `run(input_data)`

- **入参**：`dict`（单条）或 `list[dict]`（批量）
- **返回**：`dict`（单条）或 `list[dict]`（批量）
- **异常**：
  - `ValueError`（校验失败 / 未知期货品种乘数缺失）
  - `TypeError`（入参类型错误）
  - `RuntimeError`（`panda_data` 未装 / env 未配置）

> **入参已精简**：不再接受 `config` / `trade_days` / `holding_trading_days` 参数——交易日历由 `panda_data.get_trade_cal` 唯一提供。

### `validate_input(pos)`

- **入参**：`dict`
- **返回**：`(bool, str)` — (是否通过, 错误信息)

### `inspect_calendar(parquet_path=None)` ⭐ agent 侧探查

只读检查 `trade.parquet` 状态，供 agent 决定是否需要更新。

**入参**：`parquet_path`（可选）—— 自定义 parquet 位置；缺省用默认 `生产产物/trade.parquet`

**返回**：dict

| 字段 | 类型 | 说明 |
|---|---|---|
| `exists` | bool | 文件是否存在 |
| `path` | str | 检查的绝对路径 |
| `count` | int | 交易日数量（不存在时=0） |
| `date_min` | str\|None | 最早交易日 `YYYY-MM-DD` |
| `date_max` | str\|None | 最晚交易日 `YYYY-MM-DD` |
| `today` | str | 系统当前日期 `YYYY-MM-DD` |
| `covers_today` | bool | `date_max >= today` |
| `days_to_expiry` | int\|None | `date_max - today` 自然日数（负=过期） |
| `recommendation` | str | `"ok"` / `"refresh_recommended"` / `"refresh_required"` / `"missing"` |
| `reason` | str | 判定原因（人类可读） |

### `refresh_calendar(force=False, years_back=3, years_forward=1, exchange="SH", parquet_path=None)` ⭐ agent 侧更新

检查并按需刷新 `trade.parquet`。

**判定规则**（`force=False` 时）：
- 缺失/过期/`days_to_expiry < 30` → 自动刷新
- 否则跳过

**参数**：与 `build_calendar.py --years-back / --years-forward / --exchange / --output` 一致

**返回**：dict

| 字段 | 类型 | 说明 |
|---|---|---|
| `updated` | bool | 是否实际重跑 |
| `reason` | str | 判定原因 |
| `before` | dict | 更新前 `inspect_calendar` 结果 |
| `after` | dict\|None | 更新后 `inspect_calendar` 结果（未更新为 None） |
| `file_size` | int\|None | 新文件字节数 |

## 输入字段规范

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| code | str | 是 | A股代码 / 期货代码（可分类，否则报错） |
| entry_price | numbers.Real | 是 | > 0，非 NaN/inf（兼容 numpy.float） |
| entry_date | str | 是 | YYYY-MM-DD |
| current_qty | numbers.Integral | 是 | >= 0，非 bool（兼容 numpy.int） |
| open_price | numbers.Real | 是 | > 0，非 NaN/inf |
| today | str | 是 | YYYY-MM-DD，须 >= entry_date |
| total_equity | numbers.Real | 是 | 仓位比分母；非 NaN/inf；<=0 运行时返回 hold（校验放行，运行守卫） |
| available_cash | numbers.Real | 否 | 保留字段，不作分母；若提供须为有限实数 |
| multiplier | numbers.Real | 否 | 期货合约乘数（>0）；缺省查内置表；未知品种未传则报错；A股忽略 |

### 交易日历规则

- **唯一来源**：`TradingCalendar.from_panda_data(entry_date, today)` → `panda_data.get_trade_cal`
- **读盘优先**：若 `生产产物/trade.parquet` 存在且覆盖 today，直接读盘；否则实时拉取
- 首次调用自动 `_ensure_panda_logged_in()`（读 env → `init_token`）
- 后续调用命中模块级 `_PANDA_LOGIN_DONE = True` 与 `_CALENDAR_CACHE` 单例，不重复登录/构造
- 语义：entry 当天 = 第 0 个交易日；`holding_trading_days==1` 为「次日」；`>=2` 触发强平

### 生产产物：trade.parquet 缓存

| 项 | 值 |
|---|---|
| 路径 | `生产产物/trade.parquet`（相对 build.py 的 `../生产产物/`） |
| 生成命令 | `python3 scripts/build_calendar.py` |
| 默认覆盖 | 今天-3年 到 今天+1年（~971 交易日 / ~19 KB snappy） |
| Schema | 与 `panda_data.get_trade_cal` 一致；`build.py` 只用 `nature_date` 列 |
| 过期判定 | `max(nature_date) < today` → 视为过期，回退实时拉取 |
| 缓存单例 | 模块级 `_CALENDAR_CACHE`，同进程内不重复构造 |

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

## 使用示例

```python
import os
os.environ.setdefault("PANDA_USERNAME", "...")   # 建议在 shell 配置中 export
os.environ.setdefault("PANDA_PASSWORD", "...")

from scripts.build import run

# 首次调用触发 panda_data init_token 登录
result = run({
    "code": "600036",
    "entry_price": 10.0, "entry_date": "2026-06-19",   # 周五入场
    "current_qty": 800, "open_price": 10.55,
    "today": "2026-06-22",                              # 周一（真实交易日次日）
    "total_equity": 1_000_000,
})
# → {"action": "sell", "target_qty": 0, "reason": "[B11]次日高开止盈 ..."}
```
