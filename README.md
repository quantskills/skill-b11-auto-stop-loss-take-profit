# B11 自动止盈止损+仓位管理

panda-trading BUILD 技能 — 按入场日期和开盘价自动判断止盈、止损、强平，以及单票仓位上限控制。

## 目录结构

```
build-b11-auto-stop-loss-take-profit/
├── README.md                              ← 本文件
├── INSTALL_CLAUDE_CODE.md                 ← 安装指南
├── requirements.txt                       ← 依赖声明
└── build-b11-auto-stop-loss-take-profit/  ← 开发产物
    ├── SKILL.md                           ← 技能设计书
    ├── scripts/
    │   ├── build.py                       ← 主入口（run / validate_input）
    │   └── test.py                        ← 自测脚本
    └── references/
        └── api_guide.md                   ← 接口调用文档
```

## 快速开始

```bash
cd build-b11-auto-stop-loss-take-profit/scripts
python3 build.py
python3 test.py
```

## 核心设计要点

1. **四级优先级**：次日止盈（+5%）→ 次日止损（-3%）→ 持仓2日强平 → 单票>10%减仓
2. **持仓天数含入场日**：入场日 = 第1日，T+1 = 第2日触发强平
3. **A股 + 期货共用规则**：统一日期计算，品种仅区分最小交易单位（100股 vs 1手）
4. **纯 Python 零依赖**：仅标准库（datetime / re / json）

## 验收状态

- build.py 独立可运行 ✅
- validate_input 输入校验 ✅
- test.py 16/16 通过 ✅

## 局限

- 日期按自然日计算，非交易日可能误判
- 仅多头，不处理空头/双向
- 不感知涨跌停/停牌
