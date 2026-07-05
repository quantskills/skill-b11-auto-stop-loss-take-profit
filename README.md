# B11 自动止盈止损+仓位管理（增强版）

当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈（+5%）、次日低开止损（-3%）、持仓满 2 交易日强平、单票名义仓位上限（>10%）减仓，输出标准 8 字段调仓指令。

> 本版本为对 52/100 验收版的**增强修复**，全面落地 6 项缺陷改进（E1–E6），**v2 已升级为混合型 BUILD**——生产产物 `production/trade.parquet` 提供本地交易日历缓存，agent 侧新增 `inspect_calendar()` / `refresh_calendar()` 自主决策 API。

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现，过去的表现不预示未来结果。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点、集合竞价等实际交易约束。交易日历默认 A 股口径（`panda_data` 的 SH 交易所），港美股暂不支持；仅支持多头持仓。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不得视为 QuantSkills 官方背书的产品级工具。

## 目录结构

```
├── SKILL.md                                ← 技能设计书（含 metadata / 决策规则 / Agent 更新 SOP）
├── README.md                               ← 本文件
├── README.en.md                            ← English version
├── LICENSE                                 ← GPL-3.0-only
├── INSTALL.md                              ← 多平台安装指南（5 平台）
├── requirements.txt                        ← 依赖声明（panda_data 硬依赖 + pyarrow）
├── scripts/
│   ├── build.py                            ← 主入口（run / validate_input / inspect_calendar / refresh_calendar）
│   ├── test.py                             ← 自测脚本（62 用例）
│   ├── build_calendar.py                   ← 独立初始化：拉取交易日历 → 写 production/trade.parquet
│   └── _verify_prod.py                     ← 生产路径验证（panda_data 实测）
├── references/
│   └── api_guide.md                        ← 接口调用文档（含增强变更清单 + Agent 更新 SOP）
└── production/
    └── trade.parquet                       ← 交易日历缓存（今天-3年 → 今天+1年，snappy 压缩，~18.5KB）
```

## 快速开始

```bash
# 一：初始化交易日历缓存（首次使用必做，需 PANDA_USERNAME/PANDA_PASSWORD）
python3 scripts/build_calendar.py

# 二：单元测试（零外部数据依赖，62 用例）
python3 scripts/test.py

# 三：build 主入口示例
python3 scripts/build.py

# 四（可选）：生产路径实测（需 panda_data + env 凭据）
python3 scripts/_verify_prod.py
```

## Agent 使用示例

v2 新增两个 agent 侧公开 API，供上层 agent 自主决策日历更新时机：

```python
from scripts.build import inspect_calendar, refresh_calendar, run

# 1. 只读探查：查看当前缓存的日期范围、覆盖天数、最后更新时间
info = inspect_calendar()
# {'first_date': '2022-07-05', 'last_date': '2027-07-06', 'total_days': 971, 'mtime': '...'}

# 2. 按需刷新：force=False 时智能跳过（仍在覆盖范围内），True 强制重拉
refresh_calendar(force=False)

# 3. 正常调用主入口
order = run(pos={"code": "600519", "entry_date": "2025-01-02", ...},
            config={"total_equity": 1_000_000})
```

完整 4 步 SOP 与 7 种触发场景决策表见 `SKILL.md` § Agent 更新 SOP。

## v2 更新记录

相对 v1（commit `ea1585e`）的 7 项主要变更：

1. **交易日历硬依赖 panda_data**：删除 `config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]` 四个入口，唯一来源 = `panda_data.get_trade_cal`（消除口径分歧风险）。
2. **自动 env 登录**：`build.py` 首次调用交易日历时自动读 `PANDA_USERNAME` / `PANDA_PASSWORD` 并调 `init_token`；凭据缺失抛 `RuntimeError` 含引导链接。
3. **新增 `production/trade.parquet` 生产产物**：本 BUILD 从纯调用型升级为**混合型**——本地 parquet 缓存作为交易日历的持久层，避免每次调用都走网络。
4. **新增独立初始化脚本 `scripts/build_calendar.py`**：拉取今天−3年至今天+1年的交易日历，`snappy` 压缩写入 parquet 缓存（~18.5KB / 971 交易日）。
5. **新增 agent 侧公开 API**：`inspect_calendar()`（只读探查）+ `refresh_calendar(force=False)`（按需刷新），供 agent 自主决策日历生命周期。
6. **完整 schema 文档 + Agent 更新 SOP**：`SKILL.md` 详细列出 parquet 5 列 schema、日期格式约定、agent 更新四步流程、7 种触发场景决策表。
7. **测试从 49 → 62 例**：新增 parquet cache / inspect_calendar / refresh_calendar 全套用例，`pyarrow` 缺失时智能 skip。

## 核心设计要点

1. **五级决策优先级**：`守卫(异常返回 hold) → 次日止盈(+5%) → 次日止损(-3%) → 持仓 ≥2 交易日强平 → 单票名义仓位 >10% 减仓 → hold`。
2. **交易日语义（E1）**：入场当天 = 第 0 个交易日；`holding_trading_days` 为跨越的交易日数。次日 = `holding_trading_days == 1`，强平 = `holding_trading_days >= 2`。周五入场的「次日」是下周一（自然日差 3），由交易日历正确识别。
3. **仓位分母（E2）**：仓位比 = 名义价值 / `total_equity`（方案 A：调用方传入的**总权益**，不再用 available_cash）。名义价值 = `current_qty × open_price × multiplier`（A 股 multiplier=1）。
4. **代码分类（E3）**：先剥离 `sh/sz/SH/SZ` 前缀再判定，6 位纯数字为 A 股，含字母为期货。
5. **期货合约乘数（E4）**：内置乘数表覆盖 IF/IC/IH/IM/rb/cu 等常见品种，未知品种可通过 `multiplier` 显式覆盖。
6. **健壮性（E5）**：入场价/开盘价 NaN/inf、`total_equity ≤ 0`、`today < entry` 等异常统一返回 hold。
7. **交易日历唯一来源（v2）**：`panda_data.get_trade_cal` 硬依赖，本地 `production/trade.parquet` 提供持久缓存。删除 v1 的 4 个降级入口（`config["calendar"]` / `pos["trade_days"]` / `config["trade_days"]` / `pos["holding_trading_days"]`）以消除口径分歧。
8. **纯 Python 标准库（业务层）**：`math / numbers / re / datetime / bisect`，无 pandas/numpy。仅数据缓存层依赖 `panda_data` + `pyarrow`。

## 支持的运行时平台

| 平台 | 安装指南 |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## 验收状态

- **测试**：`scripts/test.py` — **62 / 62 用例通过**（正常流、边界值、异常输入、增强项 E1–E6、v2 parquet cache / inspect / refresh 全覆盖）。
- **增强改进落地**：
  - E1 交易日语义（`panda_data.get_trade_cal` 唯一来源） ✅
  - E2 仓位分母改为 `total_equity` ✅
  - E3 代码分类先剥离 sh/sz 前缀 ✅
  - E4 期货合约乘数（内置表 + `multiplier` 覆盖） ✅
  - E5 健壮性（NaN/inf、非法权益、时间倒流守卫） ✅
  - E6 测试补全（62 用例，覆盖 v2 新增字段与边界） ✅
- **v2 混合型产物**：`production/trade.parquet`（971 交易日 / snappy 压缩 / ~18.5KB）已随仓库发布。
- **生产路径验证**：`scripts/_verify_prod.py` — `panda_data.get_trade_cal` **实测通过**（PANDA_USERNAME/PANDA_PASSWORD 环境变量自动读取）。
- `build.py` 独立可运行、`validate_input` / `inspect_calendar` / `refresh_calendar` API 完备。

## Known Limitations

1. **交易日历默认 A 股口径**（`panda_data` SH 交易所），港美股暂不支持。
2. **不区分涨停/跌停/停牌**——触发日若无法交易，指令不可执行。
3. **仅支持多头持仓**——不处理空头、双向、套利、跨期组合。
4. **未知期货品种需传 multiplier**——内置表未覆盖时调用方必须显式提供合约乘数。
5. 不感知市场流动性、滑点、冲击成本——大单执行可能偏离预期价格。

## 维护者

- duanyong <hiduan@qq.com>
- 上游组织：QuantSkills (<https://github.com/quantskills>)
- License：GPL-3.0-only（详见 `LICENSE`）
