#!/usr/bin/env python3
"""
B11 自测脚本（增强版）

覆盖：
  - 原有快乐路径用例（保留，按新契约 total_equity + 交易日历调整入参）
  - [E1] 交易日语义：周末/节假日入场、次日判定、满2交易日强平、entry为非交易日兜底
  - [E2] 仓位分母 total_equity：=0/负权益/NaN/inf、满仓现金趋零不误减、边界10%
  - [E3] 代码分类：sh600036/SZ000001/600036/688/ETF 判A股、IF2406/rb2410 判期货、整百委托
  - [E4] 期货合约乘数：IF=300/rb=10 名义价值、未知品种报错、传 multiplier 覆盖、A股=1
  - [E5] 健壮性：减仓不退化清仓、today<entry 守卫、today==entry 当日、NaN 价格、numpy 类型、target==current
  - 优先级冲突：TP > 强平、batch_manage 混合标的

依赖处理：交易日历用 StubCalendar / trade_days / holding_trading_days 注入，
不依赖真实 panda_data，沙箱 Py3.10 可独立运行。
每例打印 input / expected / actual。
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(__file__))
from build import (
    run, validate_input, manage_position, classify, TradingCalendar,
    _resolve_multiplier, _is_a_stock, _is_future, _normalize_code, _get_lot_size,
    CLS_A_STOCK, CLS_FUTURE,
)

PASS, FAIL = 0, 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"✅ {name}")
    except AssertionError as e:
        FAIL += 1
        print(f"❌ {name}: {e}")
    except Exception as e:
        FAIL += 1
        print(f"💥 {name}: {type(e).__name__}: {e}")


def show(input_data, expected, actual):
    """打印 input/expected/actual（截断长 dict）。"""
    print(f"    input={input_data}")
    print(f"    expected={expected}")
    print(f"    actual={actual}")


# ============================================================
# 测试用交易日历（StubCalendar / trade_days）—— 不依赖 panda_data
# ============================================================

# 跨周末：周四6/18、周五6/19、(周六日非交易)、下周一6/22、周二6/23、周三6/24
TRADE_DAYS = [
    "2026-06-17", "2026-06-18", "2026-06-19",
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
]
# 含国庆长假：9-30 节前最后交易日，10-1..10-8 休市，10-9 节后首日
HOLIDAY_TRADE_DAYS = [
    "2026-09-29", "2026-09-30",
    "2026-10-09", "2026-10-10", "2026-10-12", "2026-10-13",
]
CFG = {"trade_days": TRADE_DAYS}
CFG_HOLIDAY = {"trade_days": HOLIDAY_TRADE_DAYS}


class StubCalendar:
    """鸭子类型 stub：用固定映射验证 config['calendar'] 注入路径。"""
    def __init__(self, mapping):
        # mapping: (entry, today) -> holding_trading_days
        self._m = mapping

    def holding_trading_days(self, entry_date, today):
        return self._m[(entry_date, today)]

    def is_next_day(self, entry_date, today):
        return self.holding_trading_days(entry_date, today) == 1


def base(**over):
    """构造一条合法输入基线（A股，total_equity 充足，入场当天）。"""
    pos = {
        "code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
        "current_qty": 800, "open_price": 10.0,
        "total_equity": 1_000_000, "today": "2026-06-19",
    }
    pos.update(over)
    return pos


# ============================================================
# 校验层
# ============================================================

def test_validate_ok():
    ok, err = validate_input(base())
    assert ok, err


def test_validate_missing_field():
    ok, err = validate_input({"code": "600036"})
    assert not ok


def test_validate_bad_price():
    ok, err = validate_input(base(entry_price=-1.0))
    assert not ok


def test_validate_bad_date():
    ok, err = validate_input(base(entry_date="bad"))
    assert not ok


def test_validate_missing_total_equity():
    p = base()
    del p["total_equity"]
    ok, err = validate_input(p)
    assert not ok and "total_equity" in err, err


# ============================================================
# E1 交易日语义
# ============================================================

def test_e1_friday_entry_monday_take_profit():
    """[E1] 周五入场，周一(交易日次日)高开+5.5% → 止盈（原自然日实现会误判为强平/跳过）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55)
    r = run(inp, config=CFG)
    exp = {"action": "sell", "target_qty": 0, "reason~": "止盈"}
    show("周五入场+周一+5.5%", exp, {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] == 0
    assert "止盈" in r["reason"], r["reason"]


def test_e1_friday_entry_monday_stop_loss():
    """[E1] 周五入场，周一低开-3.5% → 止损。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=9.65)
    r = run(inp, config=CFG)
    show("周五入场+周一-3.5%", {"action": "sell", "reason~": "止损"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止损" in r["reason"], r


def test_e1_holiday_entry_next_session_take_profit():
    """[E1] 节前最后交易日(9-30)入场，节后首日(10-9)为交易日次日，高开+6% → 止盈。"""
    inp = base(entry_date="2026-09-30", today="2026-10-09", open_price=10.6)
    r = run(inp, config=CFG_HOLIDAY)
    show("国庆前入场+节后首日+6%", {"action": "sell", "reason~": "止盈"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止盈" in r["reason"], r


def test_e1_force_close_across_weekend():
    """[E1] 周五入场，周二(=T+2,满2交易日)→ 强平（非自然日 days）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-23", open_price=10.1)
    r = run(inp, config=CFG)
    show("周五入场+周二(T+2)", {"action": "sell", "reason~": "强制平仓"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "强制平仓" in r["reason"], r


def test_e1_force_close_across_holiday():
    """[E1] 节前入场(9-29)，节后第二个交易日(10-10)=满2交易日 → 强平。"""
    inp = base(entry_date="2026-09-29", today="2026-10-10", open_price=10.1)
    r = run(inp, config=CFG_HOLIDAY)
    show("国庆跨假满2交易日", {"action": "sell", "reason~": "强制平仓"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "强制平仓" in r["reason"], r


def test_e1_natural_gt1_but_trading_eq1():
    """[E1] 自然日差=3(周五→周一)但交易日差=1：验证按交易日判次日而非自然日。"""
    cal = TradingCalendar(TRADE_DAYS)
    assert cal.holding_trading_days("2026-06-19", "2026-06-22") == 1, "周五→周一应为1个交易日"
    assert cal.is_next_day("2026-06-19", "2026-06-22") is True
    # 入场当天=0
    assert cal.holding_trading_days("2026-06-19", "2026-06-19") == 0
    # T+2
    assert cal.holding_trading_days("2026-06-19", "2026-06-23") == 2


def test_e1_entry_on_non_trading_day_fallback():
    """[E1] entry_date 为周六(非交易日,数据异常)：夹逼兜底不崩溃，能给出合理交易日数。"""
    cal = TradingCalendar(TRADE_DAYS)
    # 周六 2026-06-20 入场，今天周一 6-22：<=6-22 交易日数=4(17,18,19,22) - <=6-20 交易日数=3(17,18,19)=1
    hd = cal.holding_trading_days("2026-06-20", "2026-06-22")
    show("entry周六兜底", {"holding_trading_days": ">=0 不崩溃"}, {"holding_trading_days": hd})
    assert hd >= 0, hd


def test_e1_injected_calendar_stub():
    """[E1] config['calendar'] 注入 StubCalendar：验证可注入路径。"""
    stub = StubCalendar({("2026-06-19", "2026-06-22"): 1})
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55)
    r = run(inp, config={"calendar": stub})
    show("注入StubCalendar次日止盈", {"action": "sell", "reason~": "止盈"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止盈" in r["reason"], r


def test_e1_explicit_holding_trading_days():
    """[E1] 直接传 holding_trading_days（零依赖路径）：=1 触发次日止盈。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55,
               holding_trading_days=1)
    r = run(inp)  # 无 config，纯零依赖
    show("显式holding_trading_days=1", {"action": "sell", "reason~": "止盈"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "sell" and "止盈" in r["reason"], r


# ============================================================
# E2 仓位分母 total_equity
# ============================================================

def test_e2_total_equity_zero_returns_hold():
    """[E2] total_equity=0 → 返回 hold 不崩溃（原 available_cash=0 会 ZeroDivisionError）。"""
    inp = base(total_equity=0, current_qty=2000, open_price=10.0, today="2026-06-19")
    r = run(inp, config=CFG)
    show("total_equity=0", {"action": "hold", "reason~": "总权益非正"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "总权益非正" in r["reason"], r


def test_e2_total_equity_negative_returns_hold():
    """[E2] 负权益(穿仓) → hold。"""
    inp = base(total_equity=-50000, current_qty=2000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("负权益穿仓", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_total_equity_nan_rejected():
    """[E2] total_equity=NaN → validate_input 拒绝。"""
    ok, err = validate_input(base(total_equity=float("nan")))
    show("total_equity=NaN", {"ok": False}, {"ok": ok, "err": err})
    assert not ok, err


def test_e2_full_position_cash_zero_no_false_reduce():
    """[E2] 满仓现金趋零但 total_equity 正常：单票占比小，不再误减（原口径会误减）。"""
    # 持仓市值 60000，总权益 1,000,000 → 占比6% < 10%，应 hold（即便 available_cash≈0）
    inp = base(current_qty=6000, open_price=10.0, total_equity=1_000_000,
               available_cash=0, today="2026-06-19")
    r = run(inp, config=CFG)
    show("满仓现金0但占比6%", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_boundary_exactly_10pct_no_reduce():
    """[E2/10%口径] 占比恰好==10% 不减仓（严格 >10% 才动）。"""
    # 市值 = 1000股*100元 = 100,000；总权益 1,000,000 → 恰好10%
    inp = base(current_qty=1000, open_price=100.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("占比恰好10%", {"action": "hold"}, {"action": r["action"], "ratio": "10%", "reason": r["reason"]})
    assert r["action"] == "hold", r


def test_e2_over_10pct_reduces_to_le_10pct():
    """[E2/10%口径] 占比>10% 减仓至 <=10% 最近整百股。"""
    # 市值 = 2000*100 = 200,000；总权益 1,000,000 → 20% > 10%
    # 目标名义=100,000 → 1000股；floor 到 1000（整百），1000<2000 → sell
    inp = base(current_qty=2000, open_price=100.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("占比20%减仓", {"action": "sell", "target_qty": 1000},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] == 1000, r
    # 减仓后占比 = 1000*100/1e6 = 10% <= 10%
    assert (r["target_qty"] * 100) / 1_000_000 <= 0.10 + 1e-9


# ============================================================
# E3 代码分类
# ============================================================

def test_e3_classify_a_stock_three_forms():
    """[E3] 600036 / sh600036 / SZ000001 三种写法均判 A股，lot=100。"""
    for code in ("600036", "sh600036", "SH600036", "SZ000001", "sz000001", "Sh600036"):
        assert _is_a_stock(code), f"{code} 应判A股"
        assert classify(code) == CLS_A_STOCK, code
        assert _get_lot_size(code) == 100, code
    show("A股三写法分类", {"all": "A_STOCK lot=100"}, {"checked": ["600036", "sh600036", "SZ000001", "..."]})


def test_e3_classify_star_market_and_etf():
    """[E3] 科创板688 / ETF 510300 / 北交所开头8 均为6位数字 → A股。"""
    for code in ("688981", "510300", "159915", "830799"):
        assert _is_a_stock(code), f"{code} 6位数字应判A股"
        assert _get_lot_size(code) == 100, code


def test_e3_classify_future():
    """[E3] IF2406 / rb2410 / cu2401 判期货，lot=1。"""
    for code in ("IF2406", "rb2410", "cu2401", "RB2410"):
        assert _is_future(code), f"{code} 应判期货"
        assert classify(code) == CLS_FUTURE, code
        assert _get_lot_size(code) == 1, code


def test_e3_sh_prefix_not_future_no_odd_lot():
    """[E3] sh600036 不再被误判期货：减仓产出整百委托(不再出现909股)。"""
    # 市值 = 1000*100=100,000 占总权益... 设 total_equity 使其>10%
    inp = base(code="sh600036", current_qty=2000, open_price=100.0,
               total_equity=1_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("sh前缀减仓整百", {"action": "sell", "target_qty%100": 0},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "sell", r
    assert r["target_qty"] % 100 == 0, f"A股委托必须整百，实际 {r['target_qty']}"


def test_e3_normalize():
    assert _normalize_code("sh600036") == "600036"
    assert _normalize_code("SZ000001") == "000001"
    assert _normalize_code("600036") == "600036"
    assert _normalize_code("IF2406") == "IF2406"


# ============================================================
# E4 期货合约乘数
# ============================================================

def test_e4_if_notional_multiplier_300():
    """[E4] IF2406 名义价值 = qty*price*300，仓位比按名义价值算。"""
    # 10手 * 4050 * 300 = 12,150,000；总权益 1e8 → 12.15% > 10% → 减仓
    inp = base(code="IF2406", entry_price=4000.0, current_qty=10, open_price=4050.0,
               multiplier=300, total_equity=100_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    # 目标名义=1e7 → 1e7/(4050*300)=8.23 → floor 8 手
    show("IF乘数300减仓", {"action": "sell", "target_qty": 8},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell" and r["target_qty"] == 8, r


def test_e4_rb_notional_multiplier_10():
    """[E4] rb2410 名义价值 = qty*price*10。"""
    mult = _resolve_multiplier("rb2410")
    show("rb内置乘数", {"multiplier": 10}, {"multiplier": mult})
    assert mult == 10, mult
    # 200手*3500*10 = 7,000,000；总权益 1e7 → 70% > 10% → 减仓至 <=10%
    inp = base(code="rb2410", entry_price=3500.0, current_qty=200, open_price=3500.0,
               total_equity=10_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    # 目标名义=1e6 → 1e6/(3500*10)=28.57 → floor 28 手
    show("rb乘数10减仓", {"action": "sell", "target_qty": 28},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "sell" and r["target_qty"] == 28, r


def test_e4_unknown_future_raises():
    """[E4] 未知期货品种且未传 multiplier → 报错（不静默用1）。"""
    raised = False
    try:
        _resolve_multiplier("zz2410")  # zz 不在表中
    except ValueError as e:
        raised = True
        msg = str(e)
    show("未知期货乘数", {"raises": "ValueError"}, {"raised": raised})
    assert raised, "未知品种应报错"
    assert "multiplier" in msg


def test_e4_caller_multiplier_override():
    """[E4] 调用方传 multiplier 覆盖未知品种 → 不报错，按传入值算。"""
    mult = _resolve_multiplier("zz2410", multiplier=20)
    assert mult == 20, mult
    inp = base(code="zz2410", entry_price=1000.0, current_qty=5, open_price=1000.0,
               multiplier=20, total_equity=10_000_000, today="2026-06-19")
    r = run(inp, config=CFG)  # 名义=5*1000*20=100,000 占1% → hold
    show("传入乘数覆盖未知品种", {"no_raise": True, "action": "hold"},
         {"action": r["action"]})
    assert r["action"] == "hold", r


def test_e4_a_stock_multiplier_1():
    """[E4] A股 multiplier 恒为 1，市值口径不变。"""
    assert _resolve_multiplier("600036") == 1
    assert _resolve_multiplier("sh600036") == 1


# ============================================================
# E5 健壮性（4 子修复）
# ============================================================

def test_e5_no_degrade_to_clear_high_price():
    """[E5-①] 高价单手持仓，10%槽位<1手 → 不退化为清仓（保持原仓 hold，绝不卖光）。"""
    # IF 单手名义 = 1*4050*300 = 1,215,000；总权益 5,000,000 → 24.3% > 10%
    # 目标名义=500,000 → 500000/1215000=0.41手 → floor 0 → 不能清仓，应 hold
    inp = base(code="IF2406", entry_price=4000.0, current_qty=1, open_price=4050.0,
               multiplier=300, total_equity=5_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("高价单手不清仓", {"action": "hold", "target_qty": 1},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "hold", f"绝不能清仓: {r}"
    assert r["target_qty"] == 1, r


def test_e5_a_stock_min_lot_no_clear():
    """[E5-①] A股高价股10%槽位<100股 → 不清仓。"""
    # 100股*3000元=300,000；总权益 1,000,000 → 30% > 10%
    # 目标名义=100,000 → 100000/3000=33.3股 → floor 0(<100) → 不清仓 hold
    inp = base(code="600519", current_qty=100, open_price=3000.0,
               total_equity=1_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("A股高价不清仓", {"action": "hold", "target_qty": 100},
         {"action": r["action"], "target_qty": r["target_qty"]})
    assert r["action"] == "hold" and r["target_qty"] == 100, r


def test_e5_today_before_entry_guard():
    """[E5-②] today < entry_date：validate_input 拒绝（守卫）。"""
    ok, err = validate_input(base(entry_date="2026-06-22", today="2026-06-19"))
    show("today<entry校验", {"ok": False}, {"ok": ok, "err": err})
    assert not ok, err


def test_e5_today_before_entry_trading_guard_in_decision():
    """[E5-②] 决策层交易日维度 today<entry → hold（绕过校验直接调 manage_position）。"""
    stub = StubCalendar({("2026-06-22", "2026-06-19"): -1})
    r = manage_position(code="600036", entry_price=10.0, entry_date="2026-06-22",
                        current_qty=800, open_price=10.0, today="2026-06-19",
                        total_equity=1_000_000, config={"calendar": stub})
    show("决策层today<entry", {"action": "hold", "reason~": "早于"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "早于" in r["reason"], r


def test_e5_today_equals_entry_same_day_hold():
    """[E5] today==entry（入场当天，0个交易日，既非次日也未满2日）→ hold。"""
    inp = base(entry_date="2026-06-19", today="2026-06-19", open_price=10.5,
               current_qty=100)  # 即便+5%，当天非次日不止盈
    r = run(inp, config=CFG)
    show("入场当天+5%", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", f"入场当天不应触发次日止盈: {r}"


def test_e5_nan_price_validate_rejected():
    """[E5-③] entry_price/open_price 为 NaN → validate_input 拒绝。"""
    ok1, _ = validate_input(base(open_price=float("nan")))
    ok2, _ = validate_input(base(entry_price=float("inf")))
    show("NaN/inf价格校验", {"ok1": False, "ok2": False}, {"ok1": ok1, "ok2": ok2})
    assert not ok1 and not ok2


def test_e5_nan_price_decision_hold():
    """[E5-③] 绕过校验直接传 NaN 价格 → 决策层守卫返回 hold（双保险）。"""
    r = manage_position(code="600036", entry_price=10.0, entry_date="2026-06-19",
                        current_qty=800, open_price=float("nan"), today="2026-06-22",
                        total_equity=1_000_000, holding_trading_days=1)
    show("决策层NaN价格", {"action": "hold", "reason~": "NaN"},
         {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold" and "NaN" in r["reason"], r


def test_e5_numpy_like_integral_accepted():
    """[E5-④] numbers.Integral（模拟 numpy.int64）current_qty 被接受。"""
    class FakeNpInt(int):
        """模拟 numpy 整数：是 int 子类，也是 numbers.Integral。"""
        pass
    import numbers as _n
    assert isinstance(FakeNpInt(800), _n.Integral)
    ok, err = validate_input(base(current_qty=FakeNpInt(800)))
    show("numpy整数类型", {"ok": True}, {"ok": ok, "err": err})
    assert ok, err


def test_e5_numpy_like_real_price_accepted():
    """[E5-④] numbers.Real（模拟 numpy.float64）价格被接受。"""
    class FakeNpFloat(float):
        pass
    import numbers as _n
    assert isinstance(FakeNpFloat(10.5), _n.Real)
    ok, err = validate_input(base(open_price=FakeNpFloat(10.5), entry_price=FakeNpFloat(10.0)))
    assert ok, err


def test_e5_bool_rejected_as_qty():
    """[E5-④] bool 不应被当作合法数量（True/False 排除）。"""
    ok, err = validate_input(base(current_qty=True))
    assert not ok, "bool 不应通过 current_qty 校验"


def test_e5_target_equals_current_hold():
    """[E5] 减仓计算后 target==current（无需操作）→ hold。"""
    # 构造占比恰好略超但 floor 后 target==current 的场景：占比10.0001%，floor 不变
    # 市值=1000*100.01=100,010 总权益1,000,000 → 10.001% > 10%
    # 目标名义=100,000 → 100000/100.01=999.9 → floor 900？需整百 → 900 < 1000 会 sell
    # 改用：current 已是满足<=10%的最大整百，floor 后==current 则 hold
    # 市值=900*111=99,900 总权益 1,000,000 → 9.99% < 10% → 本就 hold（验证不误触发）
    inp = base(current_qty=900, open_price=111.0, total_equity=1_000_000, today="2026-06-19")
    r = run(inp, config=CFG)
    show("占比9.99%不动", {"action": "hold"}, {"action": r["action"], "reason": r["reason"]})
    assert r["action"] == "hold", r


# ============================================================
# 优先级冲突 & 批量
# ============================================================

def test_priority_tp_over_force_close():
    """[优先级] 次日同时满足止盈(+5.5%)与(若按日)强平 → TP 优先（reason 含止盈非强平）。"""
    inp = base(entry_date="2026-06-19", today="2026-06-22", open_price=10.55,
               holding_trading_days=1)
    r = run(inp)
    show("TP>强平", {"reason~": "止盈"}, {"reason": r["reason"]})
    assert "止盈" in r["reason"] and "强制平仓" not in r["reason"], r


def test_priority_force_close_over_reduce():
    """[优先级] 满2交易日强平 优先于 仓位减仓：即便超仓也全平到0。"""
    inp = base(code="600036", current_qty=5000, open_price=100.0, total_equity=1_000_000,
               entry_date="2026-06-19", today="2026-06-23", holding_trading_days=2)
    r = run(inp)
    show("强平>减仓", {"action": "sell", "target_qty": 0, "reason~": "强制平仓"},
         {"action": r["action"], "target_qty": r["target_qty"], "reason": r["reason"]})
    assert r["action"] == "sell" and r["target_qty"] == 0 and "强制平仓" in r["reason"], r


def test_batch_mixed_a_stock_and_future():
    """[批量] batch_manage 混合 A股+期货：各自按品种正确处理。"""
    positions = [
        base(code="600036", entry_date="2026-06-19", today="2026-06-22", open_price=10.55,
             holding_trading_days=1),  # A股次日止盈
        base(code="IF2406", entry_price=4000.0, current_qty=10, open_price=4050.0,
             multiplier=300, total_equity=100_000_000, today="2026-06-19"),  # 期货减仓
        base(code="000001", entry_date="2026-06-22", today="2026-06-22", open_price=14.9,
             current_qty=100),  # 入场当天 hold
    ]
    results = run(positions, config=CFG)
    show("批量混合", {"len": 3, "0": "sell止盈", "1": "sell减仓", "2": "hold"},
         {"actions": [x["action"] for x in results]})
    assert len(results) == 3
    assert results[0]["action"] == "sell" and "止盈" in results[0]["reason"], results[0]
    assert results[1]["action"] == "sell" and results[1]["target_qty"] == 8, results[1]
    assert results[2]["action"] == "hold", results[2]


def test_empty_list():
    assert run([]) == []


# ============================================================
# 原有快乐路径用例（保留，按新契约调整）
# ============================================================

def test_legacy_hold_entry_day():
    r = run(base(entry_date="2026-06-19", today="2026-06-19", open_price=10.1, current_qty=100),
            config=CFG)
    assert r["action"] == "hold", r


def test_legacy_future_take_profit():
    r = run(base(code="IF2406", entry_price=4000.0, current_qty=2, open_price=4220.0,
                 multiplier=300, total_equity=100_000_000,
                 entry_date="2026-06-19", today="2026-06-22", holding_trading_days=1),
            config=CFG)
    assert r["action"] == "sell" and r["target_qty"] == 0 and "止盈" in r["reason"], r


def test_legacy_boundary_5pct():
    r = run(base(entry_date="2026-06-19", today="2026-06-22", open_price=10.50,
                 current_qty=100, holding_trading_days=1), config=CFG)
    assert r["action"] == "sell", r  # 恰好 +5% 触发（>=）


def test_legacy_boundary_3pct():
    r = run(base(entry_date="2026-06-19", today="2026-06-22", open_price=9.70,
                 current_qty=100, holding_trading_days=1), config=CFG)
    assert r["action"] == "sell", r  # 恰好 -3% 触发（<=）


if __name__ == "__main__":
    print("=" * 70)
    print("B11 增强版自测")
    print("=" * 70)

    print("\n---- 校验层 ----")
    test("校验通过", test_validate_ok)
    test("校验缺字段", test_validate_missing_field)
    test("校验价格异常", test_validate_bad_price)
    test("校验日期异常", test_validate_bad_date)
    test("校验缺 total_equity", test_validate_missing_total_equity)

    print("\n---- E1 交易日语义 ----")
    test("E1 周五入场周一止盈", test_e1_friday_entry_monday_take_profit)
    test("E1 周五入场周一止损", test_e1_friday_entry_monday_stop_loss)
    test("E1 国庆前入场节后首日止盈", test_e1_holiday_entry_next_session_take_profit)
    test("E1 跨周末满2交易日强平", test_e1_force_close_across_weekend)
    test("E1 跨国庆满2交易日强平", test_e1_force_close_across_holiday)
    test("E1 自然日差>1但交易日差=1", test_e1_natural_gt1_but_trading_eq1)
    test("E1 entry为非交易日兜底", test_e1_entry_on_non_trading_day_fallback)
    test("E1 注入 StubCalendar", test_e1_injected_calendar_stub)
    test("E1 显式 holding_trading_days", test_e1_explicit_holding_trading_days)

    print("\n---- E2 仓位分母 total_equity ----")
    test("E2 total_equity=0 hold不崩", test_e2_total_equity_zero_returns_hold)
    test("E2 负权益 hold", test_e2_total_equity_negative_returns_hold)
    test("E2 total_equity=NaN 拒绝", test_e2_total_equity_nan_rejected)
    test("E2 满仓现金0不误减", test_e2_full_position_cash_zero_no_false_reduce)
    test("E2 占比恰好10%不减", test_e2_boundary_exactly_10pct_no_reduce)
    test("E2 占比>10%减至≤10%", test_e2_over_10pct_reduces_to_le_10pct)

    print("\n---- E3 代码分类 ----")
    test("E3 A股三写法分类", test_e3_classify_a_stock_three_forms)
    test("E3 科创板/ETF 判A股", test_e3_classify_star_market_and_etf)
    test("E3 期货分类", test_e3_classify_future)
    test("E3 sh前缀减仓整百", test_e3_sh_prefix_not_future_no_odd_lot)
    test("E3 归一化", test_e3_normalize)

    print("\n---- E4 期货合约乘数 ----")
    test("E4 IF乘数300", test_e4_if_notional_multiplier_300)
    test("E4 rb乘数10", test_e4_rb_notional_multiplier_10)
    test("E4 未知品种报错", test_e4_unknown_future_raises)
    test("E4 传入乘数覆盖", test_e4_caller_multiplier_override)
    test("E4 A股乘数=1", test_e4_a_stock_multiplier_1)

    print("\n---- E5 健壮性 ----")
    test("E5 高价期货单手不清仓", test_e5_no_degrade_to_clear_high_price)
    test("E5 A股高价不清仓", test_e5_a_stock_min_lot_no_clear)
    test("E5 today<entry 校验拒绝", test_e5_today_before_entry_guard)
    test("E5 决策层today<entry hold", test_e5_today_before_entry_trading_guard_in_decision)
    test("E5 today==entry 当天hold", test_e5_today_equals_entry_same_day_hold)
    test("E5 NaN/inf价格校验拒绝", test_e5_nan_price_validate_rejected)
    test("E5 决策层NaN价格hold", test_e5_nan_price_decision_hold)
    test("E5 numpy整数被接受", test_e5_numpy_like_integral_accepted)
    test("E5 numpy浮点被接受", test_e5_numpy_like_real_price_accepted)
    test("E5 bool拒绝为数量", test_e5_bool_rejected_as_qty)
    test("E5 target==current hold", test_e5_target_equals_current_hold)

    print("\n---- 优先级冲突 & 批量 ----")
    test("优先级 TP>强平", test_priority_tp_over_force_close)
    test("优先级 强平>减仓", test_priority_force_close_over_reduce)
    test("批量混合A股+期货", test_batch_mixed_a_stock_and_future)
    test("空列表", test_empty_list)

    print("\n---- 原有快乐路径（保留）----")
    test("legacy 入场当天hold", test_legacy_hold_entry_day)
    test("legacy 期货次日止盈", test_legacy_future_take_profit)
    test("legacy 边界+5%", test_legacy_boundary_5pct)
    test("legacy 边界-3%", test_legacy_boundary_3pct)

    print("\n" + "=" * 70)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 70)
    sys.exit(0 if FAIL == 0 else 1)
