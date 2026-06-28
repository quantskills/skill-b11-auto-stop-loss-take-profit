# B11 自动止盈止损+仓位管理

当需要对 A 股和期货持仓做自动止盈止损与仓位管理时，使用此 skill。支持次日高开止盈、次日低开止损、持仓超期强平、单票仓位上限控制。

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 仅为量化交易研究工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：回测或模拟结果不代表实际交易表现。使用者应自行承担全部交易风险。
- **风险边界**：本工具不感知市场流动性、涨跌停、停牌、滑点等实际交易约束，日期按自然日计算可能在非交易日触发误判。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证。

## 目录结构

```
├── SKILL.md                                ← 技能设计书
├── README.md                               ← 本文件
├── README.en.md                            ← English version
├── LICENSE                                 ← GPL-3.0
├── INSTALL.md                              ← 多平台安装指南
├── requirements.txt                        ← 依赖声明
├── scripts/
│   ├── build.py                            ← 主入口（run / validate_input）
│   └── test.py                             ← 自测脚本
└── references/
    └── api_guide.md                        ← 接口调用文档
```

## 快速开始

```bash
cd scripts
python3 build.py
python3 test.py
```

## 核心设计要点

1. **四级优先级**：次日止盈（+5%）→ 次日止损（-3%）→ 持仓 ≥2 日强平 → 单票 >10% 减仓。数量向下取整到品种最小交易单位（A股 100 股、期货 1 手）。

2. **持仓天数含入场日**：入场日 = 第 1 日，T+1 = 第 2 日触发次日规则。

3. **A股 + 期货共用规则**：统一日期计算与盈亏判定逻辑，品种仅区分最小交易单位。

4. **纯 Python 零依赖**：仅使用标准库（datetime / re / json），无 pandas/numpy 等三方依赖。

## 支持的运行时平台

| 平台 | 安装指南 |
|---|---|
| Claude Code | `INSTALL.md` § Claude Code |
| Codex (OpenAI) | `INSTALL.md` § Codex |
| Cursor | `INSTALL.md` § Cursor |
| Hermes | `INSTALL.md` § Hermes |
| OpenClaw | `INSTALL.md` § OpenClaw |

## 验收状态

- build.py 独立可运行 ✅
- validate_input 输入校验 ✅
- test.py 覆盖正常输入、边界值、异常输入 ✅

## 局限与后续优化方向

| 局限 | 说明 | 后续 |
|---|---|---|
| 不感知涨跌停/停牌 | 触发日若无法交易，指令不可执行 | 接入行情状态标志 |
| 日期按自然日计算 | 非交易日可能误判持仓天数 | 接入交易日历 |
| 仅多头 | 不处理空头/双向持仓 | 后续扩展 |
| 不处理多币种 | 期货/A股汇率由调用方自行换算 | 接入汇率 |
