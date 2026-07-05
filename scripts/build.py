#!/usr/bin/env python3
# B11 自动止盈止损+仓位管理（增强版）
# 适用品种：A股 / 股指期货 / 商品期货
# 纯 Python 标准库实现；唯一定向例外：交易日历可选接入 panda_data.get_trade_cal（见 E1 决策）。
#
# 本文件按 CLAUDE.md §「架构约定」分四层：配置常量 / 判断层 / 决策层 / 批量层 / 输出层。
# 输出严格遵循 CLAUDE.md §「调仓指令数据结构」8 字段。
#
# 增强修复对照（验收报告 52/100 -> 修复 6 项）：
#   E1  交易日语义：用交易日历替代自然日差，拆分 is_next_day() 与 holding_trading_days()
#   E2  仓位分母：改为 total_equity（调用方传入），<=0 短路 hold
#   E3  代码分类：先剥离 sh/sz/SH/SZ 前缀，6 位纯数字优先判 A股
#   E4  期货乘数：名义价值 = qty*price*multiplier，内置乘数表 + 可传 multiplier 覆盖
#   E5  健壮性：减仓不退化清仓 / today>=entry 守卫 / NaN-inf 校验 / numbers 类型放宽
#   E6  测试补全：见 test.py

import math
import numbers
import re
from datetime import datetime

# ============================================================
# 配置常量（交易规则阈值）
# ============================================================

STOP_PROFIT_PCT   =  0.05    # [E1] 次日开盘 浮盈 >= +5% → 止盈全平
STOP_LOSS_PCT     = -0.03    # [E1] 次日开盘 浮亏 <= -3% → 止损全平
FORCE_CLOSE_TDAYS =  2       # [E1] 持仓满 2 个交易日（holding_trading_days >= 2）→ 强平
MAX_SINGLE_RATIO  =  0.10    # [E2/E4] 单票名义仓位上限占总权益 10%（严格 > 10% 才减仓）

DATE_FMT = "%Y-%m-%d"

# 最小交易单位
A_STOCK_LOT = 100            # A股 100 股
FUTURE_LOT  = 1              # 期货 1 手

# [E4] 内置合约乘数表（品种字母前缀 -> 每手合约乘数）。
# 调用方可通过输入字段 multiplier 覆盖；未知品种且未传 multiplier → 报错（不静默用 1）。
FUTURE_MULTIPLIER = {
    # 股指期货
    "IF": 300, "IC": 200, "IH": 300, "IM": 200,
    # 国债期货
    "T": 10000, "TF": 10000, "TS": 20000, "TL": 10000,
    # 常见商品期货（每手吨/单位 * 价格口径）
    "RB": 10, "HC": 10, "I": 100, "J": 100, "JM": 60, "ZC": 100,
    "CU": 5, "AL": 5, "ZN": 5, "PB": 5, "NI": 1, "SN": 1,
    "AU": 1000, "AG": 15,
    "RU": 10, "BU": 10, "FU": 10, "SC": 1000, "MA": 10, "TA": 5,
    "M": 10, "Y": 10, "P": 10, "C": 10, "CS": 10, "A": 10, "B": 10,
    "SR": 10, "CF": 5, "OI": 10, "RM": 10, "FG": 20, "SA": 20,
    "PP": 5, "L": 5, "V": 5, "EG": 10, "EB": 5, "PG": 20,
    "JD": 10, "AP": 10, "CJ": 5, "UR": 20, "SF": 5, "SM": 5,
}

# 标的类别
CLS_A_STOCK = "A_STOCK"
CLS_FUTURE  = "FUTURE"


# ============================================================
# 标的分类（E3：先归一化前缀，6 位纯数字优先判 A股）
# ============================================================

def _normalize_code(code):
    """剥离 sh/sz/SH/SZ 交易所前缀（大小写不敏感），返回归一化后的代码主体。"""
    c = code.strip()
    m = re.match(r'^(?:sh|sz)(.+)$', c, flags=re.IGNORECASE)
    return m.group(1) if m else c


def _is_a_stock(code):
    """归一化后为 6 位纯数字 → A股（覆盖 600036 / sh600036 / 688xxx / ETF 等）。"""
    core = _normalize_code(code)
    return len(core) == 6 and core.isdigit()


def _is_future(code):
    """非 A股 且 剥离前缀后仍含字母 → 期货（如 IF2406 / rb2410 / cu2401）。"""
    if _is_a_stock(code):
        return False
    core = _normalize_code(code)
    # 期货代码形如 字母前缀 + 数字月份，剥离前缀后仍含字母
    return bool(re.match(r'^[A-Za-z]{1,3}\d{2,4}$', core))


def classify(code):
    """返回标的类别：A_STOCK / FUTURE。无法识别时抛出 ValueError。"""
    if _is_a_stock(code):
        return CLS_A_STOCK
    if _is_future(code):
        return CLS_FUTURE
    raise ValueError(f"无法识别的标的代码: {code!r}（既非6位A股代码，也非期货合约代码）")


def _get_lot_size(code):
    return A_STOCK_LOT if classify(code) == CLS_A_STOCK else FUTURE_LOT


def _resolve_multiplier(code, multiplier=None):
    """
    [E4] 解析合约乘数：
      - A股 multiplier = 1（恒定）
      - 期货：调用方传入 multiplier 优先；否则查内置表；都没有 → 报错。
    """
    if classify(code) == CLS_A_STOCK:
        return 1
    if multiplier is not None:
        if not isinstance(multiplier, numbers.Real) or isinstance(multiplier, bool):
            raise ValueError(f"multiplier 类型错误: {type(multiplier)}")
        if multiplier <= 0 or math.isnan(multiplier) or math.isinf(multiplier):
            raise ValueError(f"multiplier 必须为正有限数，实际 {multiplier}")
        return multiplier
    # 提取期货品种字母前缀（大写）查内置表，如 IF2406 → IF, rb2410 → RB
    m = re.match(r'^([A-Za-z]{1,3})\d', _normalize_code(code))
    prefix = m.group(1).upper() if m else ""
    if prefix in FUTURE_MULTIPLIER:
        return FUTURE_MULTIPLIER[prefix]
    raise ValueError(
        f"未知期货品种 {code!r}（前缀 {prefix!r} 不在内置乘数表），"
        f"请通过 multiplier 字段显式传入合约乘数"
    )


# ============================================================
# 交易日历（E1：可注入 / 可降级，避免 test.py 依赖真实 panda_data）
# ============================================================

class TradingCalendar:
    """
    交易日历抽象。提供两个能力：
      - holding_trading_days(entry_date, today): 持仓跨越的交易日数（entry 当天 = 第 0 个交易日）
      - is_next_day(entry_date, today): today 是否为 entry 的下一个交易日（holding_trading_days == 1）

    三种构造来源（按优先级，满足"可注入/可降级"）：
      1. TradingCalendar(trade_days=[...])  调用方显式传入交易日序列（YYYY-MM-DD 升序），零三方依赖
      2. config 注入自定义对象（鸭子类型，实现上述两个方法即可）—— 用于测试 stub
      3. TradingCalendar.from_panda_data()  接入 panda_data.get_trade_cal（生产环境，定向例外）
    """

    def __init__(self, trade_days):
        # trade_days: 可迭代的 YYYY-MM-DD 字符串；内部归一化为有序去重列表 + 索引
        days = sorted(set(trade_days))
        self._days = days
        self._index = {d: i for i, d in enumerate(days)}

    # ---- 交易日序号 ----
    def _ordinal(self, date_str):
        """返回该日期在交易日序列中的序号；非交易日返回 None。"""
        return self._index.get(date_str)

    def trading_days_between(self, entry_date, today):
        """
        entry 当天记为第 0 个交易日。返回 today 相对 entry 跨越的交易日数。
        - entry/today 均为交易日时：直接取序号差 ti - ei（精确）。
        - 任一为非交易日（数据异常）时回退到"夹逼"语义：
          (<= today 的交易日数) - (<= entry 的交易日数)，保证非负且单调，不崩溃。
        - today < entry 时返回负数（交由守卫层处理）。
        """
        ei = self._ordinal(entry_date)
        ti = self._ordinal(today)
        if ei is not None and ti is not None:
            return ti - ei
        # 非交易日兜底：基于排序位置夹逼
        ei2 = self._count_le(entry_date)  # <= entry 的交易日数
        ti2 = self._count_le(today)       # <= today 的交易日数
        return ti2 - ei2

    def _count_le(self, date_str):
        """返回 <= date_str 的交易日个数。"""
        import bisect
        return bisect.bisect_right(self._days, date_str)

    def holding_trading_days(self, entry_date, today):
        """持仓交易日数（entry 当天=0）。今天=entry 返回 0，次日返回 1，T+2 返回 2。"""
        return self.trading_days_between(entry_date, today)

    def is_next_day(self, entry_date, today):
        """today 是否为 entry 的下一个交易日。"""
        return self.holding_trading_days(entry_date, today) == 1

    @classmethod
    def from_panda_data(cls, start_date, end_date, exchange="SH"):
        """
        生产环境：从 panda_data.get_trade_cal 构造交易日历（定向例外）。
        入参 start_date/end_date 为 YYYY-MM-DD；内部转 YYYYMMDD 调用。
        沙箱无 panda_data 时抛 ImportError，调用方应改用 trade_days 注入。
        """
        try:
            import panda_data  # noqa: F401  仅在生产路径导入
        except ImportError as e:
            raise ImportError(
                "panda_data 不可用；请改用 TradingCalendar(trade_days=[...]) "
                "或 config['calendar'] 注入交易日历"
            ) from e
        s = start_date.replace("-", "")
        e = end_date.replace("-", "")
        result = panda_data.get_trade_cal(
            start_date=s, end_date=e, exchange=exchange, is_trading_day=1, fields=[]
        )
        # result 为表格（DataFrame 或可迭代记录）；提取 is_trade==1 的 nature_date
        trade_days = []
        records = result.to_dict("records") if hasattr(result, "to_dict") else result
        for row in records:
            is_trade = row.get("is_trade", 1)
            nd = row.get("nature_date")
            if is_trade == 1 and nd is not None:
                s = str(nd)
                trade_days.append(f"{s[0:4]}-{s[4:6]}-{s[6:8]}")
        return cls(trade_days)


def _resolve_calendar(pos, config):
    """
    [E1] 解析交易日历，按执行优先级（先命中先返回）：
      1. pos["holding_trading_days"]   调用方直接给出持仓交易日数（最轻量，零依赖）
      2. config["calendar"]            注入对象（测试 stub / 自定义）
      3. pos["trade_days"]             该条持仓自带交易日序列
      4. config["trade_days"]          全局交易日序列
      5. panda_data.get_trade_cal      生产兜底
    返回 (calendar_or_None, explicit_holding_days_or_None)。
    """
    config = config or {}
    # 1) 显式持仓交易日数：直接短路，无需日历对象
    if "holding_trading_days" in pos and pos["holding_trading_days"] is not None:
        return None, pos["holding_trading_days"]
    # 2) 注入对象
    cal = config.get("calendar")
    if cal is not None:
        return cal, None
    # 3) 该条自带交易日序列
    if pos.get("trade_days"):
        return TradingCalendar(pos["trade_days"]), None
    # 4) 全局交易日序列
    if config.get("trade_days"):
        return TradingCalendar(config["trade_days"]), None
    # 5) 生产兜底：从 panda_data 拉取 entry..today 区间日历
    return TradingCalendar.from_panda_data(pos["entry_date"], pos["today"]), None


# ============================================================
# 校验层（E2/E5：分母守卫 / NaN-inf / numbers 类型放宽）
# ============================================================

def _is_real(x):
    """数值（含 numpy 浮点/整数），排除 bool。"""
    return isinstance(x, numbers.Real) and not isinstance(x, bool)


def _finite(x):
    """有限实数（非 NaN/inf）。"""
    return _is_real(x) and not math.isnan(float(x)) and not math.isinf(float(x))


def validate_input(pos):
    """
    校验单条输入，返回 (ok, error_msg)。
    [E5] 数量用 numbers.Integral、价格/权益用 numbers.Real（兼容 numpy）；NaN/inf 一律拒绝。
    [E2] total_equity 校验下界与运行时守卫一致：允许 <=0 通过校验（运行时短路 hold），
         但 NaN/inf 必须拒绝（无法做除零守卫）。
    """
    if not isinstance(pos, dict):
        return False, "输入必须为 dict"

    # 必填 + 类型
    if not isinstance(pos.get("code"), str) or not pos.get("code").strip():
        return False, "缺少或非法字段: code"
    for f in ("entry_date", "today"):
        if not isinstance(pos.get(f), str):
            return False, f"缺少或非法字段: {f}（需 str）"
    for f in ("entry_price", "open_price"):
        if f not in pos:
            return False, f"缺少字段: {f}"
        if not _is_real(pos[f]):
            return False, f"字段 {f} 类型错误，需 numbers.Real，实际 {type(pos[f])}"
        if not _finite(pos[f]):
            return False, f"字段 {f} 为 NaN/inf，非法"
        if pos[f] <= 0:
            return False, f"{f} 必须 > 0"
    if "current_qty" not in pos:
        return False, "缺少字段: current_qty"
    if not isinstance(pos["current_qty"], numbers.Integral) or isinstance(pos["current_qty"], bool):
        return False, f"字段 current_qty 类型错误，需 numbers.Integral，实际 {type(pos['current_qty'])}"
    if pos["current_qty"] < 0:
        return False, "current_qty 必须 >= 0"

    # total_equity：方案A 必填（仓位分母）
    if "total_equity" not in pos:
        return False, "缺少字段: total_equity（仓位比例分母，方案A 由调用方传入）"
    if not _is_real(pos["total_equity"]):
        return False, f"字段 total_equity 类型错误，需 numbers.Real，实际 {type(pos['total_equity'])}"
    if math.isnan(float(pos["total_equity"])) or math.isinf(float(pos["total_equity"])):
        return False, "total_equity 为 NaN/inf，非法"
    # 注意：total_equity <= 0 允许通过校验，运行时短路返回 hold（E2 守卫）

    # available_cash：可选，若提供需为有限实数（不作分母）
    if "available_cash" in pos and pos["available_cash"] is not None:
        if not _finite(pos["available_cash"]):
            return False, "available_cash 若提供须为有限实数"

    # multiplier：可选
    if "multiplier" in pos and pos["multiplier"] is not None:
        if not _is_real(pos["multiplier"]) or not _finite(pos["multiplier"]) or pos["multiplier"] <= 0:
            return False, "multiplier 若提供须为正有限数"

    # 代码可分类
    try:
        classify(pos["code"])
    except ValueError as e:
        return False, str(e)

    # 日期格式
    try:
        entry = datetime.strptime(pos["entry_date"], DATE_FMT)
        today = datetime.strptime(pos["today"], DATE_FMT)
    except (ValueError, TypeError):
        return False, "日期格式错误，需为 YYYY-MM-DD"

    # [E5] today >= entry_date 守卫（自然日层面先粗筛；交易日层面在决策层再守）
    if today < entry:
        return False, f"today({pos['today']}) 早于 entry_date({pos['entry_date']})"

    return True, ""


# ============================================================
# 决策层（返回标准 8 字段调仓指令 dict）
# ============================================================

def manage_position(code, entry_price, entry_date, current_qty, open_price, today,
                    total_equity, multiplier=None,
                    trade_days=None, holding_trading_days=None, config=None,
                    **_ignored):
    """
    核心决策函数。决策优先级：TP > SL > 强平 > 减仓 > hold，全程仅用当日可得数据。

    Args 关键新增（增强）：
        total_equity (E2): 仓位比例分母（持仓市值+现金，调用方传入）。<=0 短路 hold。
        multiplier   (E4): 期货合约乘数；A股恒为 1；未知期货且未传 → 报错。
        trade_days / holding_trading_days / config["calendar"] (E1): 交易日历来源。
        **_ignored: 吞掉调用方 pos dict 中的可选透传字段（如 available_cash），不参与决策。
    Returns: dict，8 字段（code/pnl_pct/current_qty/time/action/qty_change/target_qty/reason）。
    """
    config = config or {}
    pnl_pct = (open_price - entry_price) / entry_price

    def _mk_order(action, target_qty, reason):
        return {
            "code": code,
            "pnl_pct": round(pnl_pct, 6),
            "current_qty": int(current_qty),
            "time": today,
            "action": action,
            "qty_change": int(target_qty) - int(current_qty),
            "target_qty": int(target_qty),
            "reason": reason,
        }

    # ---- 守卫层（E2/E5）：异常输入一律返回 hold，不进入数值计算 ----
    # NaN/inf 价格守卫（双保险，validate_input 已拦截，此处兜底直接调用场景）
    if not _finite(entry_price) or not _finite(open_price):
        return _mk_order("hold", current_qty, "[B11]hold 价格为 NaN/inf，跳过")
    # E2：总权益分母 <= 0（含 0 与负权益）短路，防除零
    if not _is_real(total_equity) or math.isnan(float(total_equity)) or math.isinf(float(total_equity)) \
            or total_equity <= 0:
        return _mk_order("hold", current_qty, f"[B11]hold 总权益非正({total_equity})，跳过仓位校验")

    # ---- 交易日语义（E1） ----
    pos_for_cal = {
        "entry_date": entry_date, "today": today,
        "trade_days": trade_days, "holding_trading_days": holding_trading_days,
    }
    cal, explicit_hold = _resolve_calendar(pos_for_cal, config)
    if explicit_hold is not None:
        hold_tdays = int(explicit_hold)
        is_next = (hold_tdays == 1)
    else:
        hold_tdays = cal.holding_trading_days(entry_date, today)
        is_next = cal.is_next_day(entry_date, today)

    # E5：today < entry（交易日维度持仓为负）守卫
    if hold_tdays < 0:
        return _mk_order("hold", current_qty, f"[B11]hold today 早于 entry_date(交易日数={hold_tdays})，异常跳过")

    # ---- 优先级 1：次日止盈（E1：is_next 基于交易日历） ----
    if is_next and pnl_pct >= STOP_PROFIT_PCT:
        return _mk_order("sell", 0,
                         f"[B11]次日高开止盈 open={open_price:.4f} entry={entry_price:.4f} pnl={pnl_pct:+.4f}")

    # ---- 优先级 2：次日止损（与止盈条件互斥，用 elif） ----
    elif is_next and pnl_pct <= STOP_LOSS_PCT:
        return _mk_order("sell", 0,
                         f"[B11]次日低开止损 open={open_price:.4f} entry={entry_price:.4f} pnl={pnl_pct:+.4f}")

    # ---- 优先级 3：持仓满 2 交易日强平（E1：holding_trading_days >= 2，平到 0 不下取整） ----
    if hold_tdays >= FORCE_CLOSE_TDAYS:
        return _mk_order("sell", 0,
                         f"[B11]持仓{hold_tdays}个交易日≥{FORCE_CLOSE_TDAYS}强制平仓 entry_date={entry_date}")

    # ---- 优先级 4：单票名义仓位 > 10% 减仓（E2 分母 total_equity / E4 分子乘乘数） ----
    mult = _resolve_multiplier(code, multiplier)
    lot = _get_lot_size(code)
    notional = current_qty * open_price * mult          # E4：名义价值 = qty*price*multiplier
    ratio = notional / total_equity                     # E2：分子分母同口径（名义价值）
    if ratio > MAX_SINGLE_RATIO:                        # 严格 > 10% 才动（==10% 不动）
        # 目标名义价值 = total_equity * 10%；换算目标数量后向下取整到最小单位
        raw_target_qty = (total_equity * MAX_SINGLE_RATIO) / (open_price * mult)
        target_qty = max(0, int(math.floor(raw_target_qty / lot)) * lot)
        # E5：floor 后若 >0 保留（A股>=100 / 期货>=1手）；且 target<current 才 sell，不退化清仓
        if 0 < target_qty < current_qty:
            return _mk_order("sell", target_qty,
                             f"[B11]单票仓位{ratio:.2%}>{MAX_SINGLE_RATIO:.0%} 减仓至{target_qty}(占比≤10%)")
        # floor 到 0 或 target>=current：不操作（严禁清仓退化）
        return _mk_order("hold", current_qty,
                         f"[B11]hold 仓位{ratio:.2%}超限但减仓后不足1单位/无需减，保持原仓")

    # ---- 优先级 5：hold ----
    return _mk_order("hold", current_qty,
                     f"[B11]hold 持仓{hold_tdays}交易日 pnl={pnl_pct:+.4f} 仓位{ratio:.2%}")


# ============================================================
# 批量层
# ============================================================

def batch_manage(positions, config=None):
    """批量处理持仓列表。config 透传（含交易日历注入）。"""
    out = []
    for pos in positions:
        kwargs = dict(pos)
        kwargs["config"] = config
        out.append(manage_position(**kwargs))
    return out


# ============================================================
# 输出层
# ============================================================

def print_order(order):
    """格式化打印单条调仓指令。"""
    print(f"code={order['code']:<10s} pnl={order['pnl_pct']:>+.4f} "
          f"qty={order['current_qty']:>6d} -> {order['action']:<4s} "
          f"target={order['target_qty']:>6d} change={order['qty_change']:>+7d} "
          f"| {order['reason']}")


# ============================================================
# 标准入口
# ============================================================

def run(input_data, config=None):
    """
    标准入口函数。
    Args:
        input_data: dict（单条）或 list[dict]（批量）
        config: dict，可选。支持 config["calendar"]（注入交易日历）/ config["trade_days"]（全局交易日序列）
    Returns:
        dict（单条）或 list[dict]（批量）
    """
    if isinstance(input_data, list):
        if len(input_data) == 0:
            return []
        for i, pos in enumerate(input_data):
            ok, err = validate_input(pos)
            if not ok:
                raise ValueError(f"输入[{i}]校验失败: {err}")
        return batch_manage(input_data, config=config)
    elif isinstance(input_data, dict):
        ok, err = validate_input(input_data)
        if not ok:
            raise ValueError(f"输入校验失败: {err}")
        kwargs = dict(input_data)
        kwargs["config"] = config
        return manage_position(**kwargs)
    else:
        raise TypeError("run() 入参必须为 dict 或 list[dict]")


# ============================================================
# 示例（__main__）
# ============================================================

if __name__ == "__main__":
    # 构造一段交易日历（跨周末：2026-06-19 周五，下一交易日为 2026-06-22 周一）
    TRADE_DAYS = [
        "2026-06-17", "2026-06-18", "2026-06-19",  # 周三/四/五
        "2026-06-22", "2026-06-23", "2026-06-24",  # 下周一/二/三
    ]
    cfg = {"trade_days": TRADE_DAYS}

    examples = [
        {   # A股次日止盈：周五入场，周一(真实交易日次日)高开 +5.5%
            "code": "600036", "entry_price": 10.0, "entry_date": "2026-06-19",
            "current_qty": 800, "open_price": 10.55,
            "total_equity": 100000, "today": "2026-06-22",
        },
        {   # A股带 sh 前缀次日止损：归一化后判 A股，-3.5%
            "code": "sh600036", "entry_price": 10.0, "entry_date": "2026-06-19",
            "current_qty": 800, "open_price": 9.65,
            "total_equity": 100000, "today": "2026-06-22",
        },
        {   # 持仓满 2 交易日强平（周五入场，周二=T+2）
            "code": "SZ000001", "entry_price": 15.0, "entry_date": "2026-06-19",
            "current_qty": 500, "open_price": 15.1,
            "total_equity": 100000, "today": "2026-06-23",
        },
        {   # 期货 IF 名义价值 = 10*4050*300 = 12,150,000，占总权益 12.15% > 10% → 减仓至 8 手
            "code": "IF2406", "entry_price": 4000.0, "entry_date": "2026-06-19",
            "current_qty": 10, "open_price": 4050.0, "multiplier": 300,
            "total_equity": 100_000_000, "today": "2026-06-19",
        },
        {   # 入场当天，hold（0 个交易日，既非次日也未满 2 日）
            "code": "000001", "entry_price": 15.0, "entry_date": "2026-06-22",
            "current_qty": 500, "open_price": 14.9,
            "total_equity": 100000, "today": "2026-06-22",
        },
    ]

    print("=== B11 自动止盈止损+仓位管理（增强版）===\n")
    for pos in examples:
        order = run(pos, config=cfg)
        print_order(order)

    print("\n=== 批量调用 ===")
    for r in run(examples, config=cfg):
        print(f"{r['code']:<10s}: {r['action']:<4s} qty_change={r['qty_change']:+d}")
