"""算法 A｜薪资口径归一（纯函数、确定性、不访问网络）。

一条原始薪资先被整理成一个「薪资包」，而不是只折出一个数字：

1. 字符归一：NFKC 全角→半角，`～ ~ — – 至` → `-`，统一逗号、去多余空白；
2. 识别计算周期：月薪（缺省）/ 年薪（`年薪 / 年包 / /年`）/ 日薪（`日薪 / 元/天 / /天`）；
   同一原值同时出现年薪与日薪 → `unparsed`（周期矛盾）；
3. 提取发薪月数 `N薪`（缺省 12，合法 12–24）；月薪按 `× 12 ÷ months` 折月，
   年薪先 ÷ 12，日薪按 21.75 个工作日/月折月；
4. 区分固定收入与浮动收入：`底薪 / 基本工资 / 固定工资` 为固定；
   `提成 / 佣金 / 年终奖 / 奖金 / 绩效` 为浮动。浮动金额能按明确周期算出来的，
   计入「含浮动月薪」；算不出来（如仅写「+提成」「提成 3%」）只打标，不臆造数字；
5. 保留原值、每一步换算（`basis_steps`）、是否含浮动收入与浮动项目；
6. 面议 → `negotiable`；空值 / 无金额 / 区间矛盾 / 周期矛盾 / 量级超界 → `unparsed`；
7. 输出 `fixed_monthly_*`（固定月薪）、`total_monthly_*`（固定 + 已量化浮动）、
   `comparable_monthly_*`（用于排序的单一口径），以及兼容旧字段 `monthly_*`（固定月薪折月值）。

本模块只处理「一条来源」。把多条来源拼成一个区间是明确禁止的：归并簇的薪资包
选择见 `services/salary_package.py`。
"""
from __future__ import annotations

import re
import unicodedata

from src.constants.enums import (
    ParseStatus,
    PayPeriod,
    PAY_PERIOD_LABELS,
    VariableScope,
    VARIABLE_SCOPE_LABELS,
)

NEGOTIABLE_PATTERN = re.compile(r"面议|面谈|详谈|待定|保密|另议")
MONTHS_PATTERN = re.compile(r"(\d{1,2})\s*薪")
AMOUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(万|w|千|k)?")
PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(%|％|个点)")

UNIT_MULTIPLIER = {"万": 10000, "w": 10000, "千": 1000, "k": 1000, "": 1}

NOISE_TOKENS = (
    "年薪制", "年薪", "年包", "月薪", "税前", "税后", "基本工资", "综合薪资", "综合月薪",
    "薪资", "工资", "人民币", "元/月", "元每月", "元/月薪", "每月", "/月", "元", "起",
    "以上", "以下", "左右", "之间", "以内", "急聘", "诚聘", "高薪", "可谈",
    "日薪", "日结", "元/天", "/天", "每天", "一天", "日工资", "按天", "/年", "每年",
    "年收入", "底薪", "无责底薪", "基础工资", "固定工资", "固定薪资",
    "提成", "业务提成", "销售提成", "佣金", "抽成",
    "年终奖", "年终奖金", "季度奖", "全勤奖", "绩效奖金", "绩效工资", "奖金",
    "绩效", "分红", "期权", "股票", "股权",
    "含提成", "含奖金", "含绩效", "总收入", "总包", "到手", "包年",
)

DASH_CHARS = ("～", "~", "—", "–", "－", "至", "到")
MONTH_MIN, MONTH_MAX = 12, 24
MONTHLY_FLOOR, MONTHLY_CEIL = 500, 500000

# 日薪折月的法定月平均工作日（21.75 天/月 = 年工作日 261 天 ÷ 12）。
WORKDAYS_PER_MONTH = 21.75

ANNUAL_MARKERS = ("年薪", "年包", "年薪制", "年收入", "/年", "每年", "包年")
DAILY_MARKERS = ("日薪", "日结", "元/天", "/天", "每天", "一天", "日工资", "按天")
BASE_MARKERS = ("无责底薪", "底薪", "基本工资", "基础工资", "固定工资", "固定薪资")
TOTAL_MARKERS = ("综合薪资", "综合月薪", "总收入", "总包", "到手", "包年")
INCLUDED_MARKERS = ("含提成", "含奖金", "含绩效", "含浮动", "已含提成", "已含奖金")

VARIABLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("commission", ("业务提成", "销售提成", "提成", "佣金", "抽成")),
    ("bonus", ("年终奖金", "年终奖", "季度奖", "全勤奖", "绩效奖金", "奖金")),
    ("performance", ("绩效工资", "绩效")),
    ("other", ("分红", "期权", "股票", "股权")),
)

VARIABLE_LABELS = {
    "commission": "提成",
    "bonus": "奖金",
    "performance": "绩效",
    "other": "长期激励",
}

SEGMENT_SPLIT = re.compile(r"[+，,；;、]|以及|另加|另有")

SUPPORTED_PERIODS = (PayPeriod.MONTH.value, PayPeriod.YEAR.value, PayPeriod.DAY.value)


def normalize_raw(raw: str | None) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip()
    for dash in DASH_CHARS:
        text = text.replace(dash, "-")
    text = text.replace("，", ",").replace("、", ",").replace("·", " ").replace("•", " ")
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _round(value: float) -> int:
    """确定性取整：四舍五入到整数元（Python round 对 .5 走偶数，仍逐次一致）。"""
    return int(round(value))


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _period_label(period: str) -> str:
    return PAY_PERIOD_LABELS.get(period, PAY_PERIOD_LABELS[PayPeriod.UNKNOWN.value])


def _scope_label(scope: str) -> str:
    return VARIABLE_SCOPE_LABELS.get(scope, scope)


def _result(
    status: str,
    *,
    raw: str,
    basis: str,
    reason: str | None = None,
    period: str = PayPeriod.UNKNOWN.value,
    months: int = 12,
    months_explicit: bool = False,
    quoted_low: int | None = None,
    quoted_high: int | None = None,
    salary_low: int | None = None,
    salary_high: int | None = None,
    fixed_monthly_low: int | None = None,
    fixed_monthly_high: int | None = None,
    variable_monthly_low: int | None = None,
    variable_monthly_high: int | None = None,
    total_monthly_low: int | None = None,
    total_monthly_high: int | None = None,
    comparable_monthly_low: int | None = None,
    comparable_monthly_high: int | None = None,
    comparable_monthly_median: int | None = None,
    monthly_low: int | None = None,
    monthly_high: int | None = None,
    monthly_median: int | None = None,
    confidence: float = 0.0,
    annual_total: int | None = None,
    has_variable: bool = False,
    variable_items: list | None = None,
    variable_scope: str = VariableScope.NONE.value,
    basis_steps: list | None = None,
) -> dict:
    items = variable_items or []
    if items:
        has_variable = True
    if has_variable and variable_scope == VariableScope.NONE.value:
        variable_scope = VariableScope.UNQUANTIFIED.value
    return {
        "status": status,
        "reason": reason,
        "raw": raw,
        "period": period,
        "period_label": _period_label(period),
        "months": months,
        "months_explicit": months_explicit,
        "quoted_low": quoted_low,
        "quoted_high": quoted_high,
        "salary_low": salary_low,
        "salary_high": salary_high,
        "fixed_monthly_low": fixed_monthly_low,
        "fixed_monthly_high": fixed_monthly_high,
        "variable_monthly_low": variable_monthly_low,
        "variable_monthly_high": variable_monthly_high,
        "total_monthly_low": total_monthly_low,
        "total_monthly_high": total_monthly_high,
        "comparable_monthly_low": comparable_monthly_low,
        "comparable_monthly_high": comparable_monthly_high,
        "comparable_monthly_median": comparable_monthly_median,
        # 兼容旧字段：monthly_* 为固定月薪的折月值（README §10 口径）
        "monthly_low": monthly_low,
        "monthly_high": monthly_high,
        "monthly_median": monthly_median,
        "annual_total": annual_total,
        "confidence": confidence,
        "has_variable": has_variable,
        "variable_items": items,
        "variable_scope": variable_scope,
        "variable_scope_label": _scope_label(variable_scope),
        "basis_steps": basis_steps or [basis],
        "norm_basis": basis,
    }


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _variable_keyword(segment: str) -> str | None:
    for kind, words in VARIABLE_KEYWORDS:
        if any(word in segment for word in words):
            return kind
    return None


def _detect_period(text: str) -> str:
    annual = _has_any(text, ANNUAL_MARKERS)
    daily = _has_any(text, DAILY_MARKERS)
    if annual and daily:
        return "conflict"
    if annual:
        return PayPeriod.YEAR.value
    if daily:
        return PayPeriod.DAY.value
    return PayPeriod.MONTH.value


def _clean_for_amounts(segment: str) -> str:
    text = PERCENT_PATTERN.sub(" ", segment)
    for token in NOISE_TOKENS:
        text = text.replace(token, " ")
    for token in ANNUAL_MARKERS + DAILY_MARKERS + BASE_MARKERS + TOTAL_MARKERS + INCLUDED_MARKERS:
        text = text.replace(token, " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _amount_matches(segment: str) -> list[tuple[str, str]]:
    return [(item.group(1), item.group(2) or "") for item in AMOUNT_PATTERN.finditer(_clean_for_amounts(segment))]


def _convert_amounts(matches: list[tuple[str, str]]) -> list[float]:
    """金额单位继承：只在后一个数字明确带单位、且前一个数字量级较小时向左继承。

    例：8-12k → 8k–12k；1-1.5万 → 1万–1.5万；8000-1万 → 8000–10000（不把 8000 当成 8000 万）。
    """
    amounts: list[float] = []
    for index, (value_text, unit) in enumerate(matches):
        chosen = unit
        if not chosen:
            next_unit = matches[index + 1][1] if index + 1 < len(matches) else ""
            prev_unit = matches[index - 1][1] if index > 0 else ""
            inherited = next_unit or prev_unit
            if inherited and float(value_text) < 1000:
                chosen = inherited
        amounts.append(float(value_text) * UNIT_MULTIPLIER[chosen])
    return amounts


def _range_from_matches(matches: list[tuple[str, str]]) -> tuple[float, float, bool, bool] | None:
    """返回 (low, high, single, inherited)。"""
    if not matches:
        return None
    amounts = _convert_amounts(matches[:2])
    inherited = any(not unit for _, unit in matches[:2]) and any(unit for _, unit in matches[:2])
    if len(amounts) == 1:
        return amounts[0], amounts[0], True, inherited
    return amounts[0], amounts[1], False, inherited


def _monthly_from(amount: float, period: str, months: int) -> float:
    if period == PayPeriod.YEAR.value:
        return amount / 12
    if period == PayPeriod.DAY.value:
        return amount * WORKDAYS_PER_MONTH
    return amount * 12 / months


def _annual_total_from(amount: float, period: str, months: int) -> float | None:
    if period == PayPeriod.YEAR.value:
        return amount
    if period == PayPeriod.DAY.value:
        return amount * WORKDAYS_PER_MONTH * 12
    return amount * 12 / months * 12


def _parse_variable_item(segment: str, period: str, kind: str) -> dict:
    """解析一个浮动收入片段；只有明确周期/口径的金额才计入可比月薪。"""
    lower = segment.lower()
    item_period: str | None = None
    if _has_any(lower, ("年终", "年度", "每年", "年薪", "/年", "年包")):
        item_period = PayPeriod.YEAR.value
    elif _has_any(lower, ("每月", "/月", "月度", "月薪")):
        item_period = PayPeriod.MONTH.value
    elif _has_any(lower, ("每天", "/天", "每日", "日结")):
        item_period = PayPeriod.DAY.value
    elif period == PayPeriod.YEAR.value and kind == "bonus":
        item_period = PayPeriod.YEAR.value

    percent_match = PERCENT_PATTERN.search(segment)
    percent = float(percent_match.group(1)) if percent_match else None

    # 比例提成（提成 3%）没有基数，不能把 3 当成金额；先去掉百分比再找金额。
    amount_source = PERCENT_PATTERN.sub(" ", segment) if percent_match else segment
    matches = _amount_matches(amount_source)
    amounts = _convert_amounts(matches[:2]) if matches else []
    raw_range = None
    if amounts:
        low, high = (amounts[0], amounts[0]) if len(amounts) == 1 else (amounts[0], amounts[1])
        raw_range = (low, high)

    quantified = bool(raw_range) and item_period is not None and percent is None
    monthly_low = monthly_high = None
    if quantified:
        low, high = raw_range
        if item_period == PayPeriod.YEAR.value:
            monthly_low, monthly_high = _round(low / 12), _round(high / 12)
        elif item_period == PayPeriod.DAY.value:
            monthly_low, monthly_high = _round(low * WORKDAYS_PER_MONTH), _round(high * WORKDAYS_PER_MONTH)
        else:
            monthly_low, monthly_high = _round(low), _round(high)

    label = VARIABLE_LABELS.get(kind, "浮动收入")
    if percent is not None:
        label = f"{label}（{_fmt(percent)}%）"
    elif raw_range:
        label = f"{label}（{_fmt(raw_range[0])}–{_fmt(raw_range[1])} 元）"
    return {
        "kind": kind,
        "label": label,
        "raw": segment.strip(),
        "period": item_period or "unknown",
        "period_label": {"year": "按年", "month": "按月", "day": "按日"}.get(item_period or "", "未标注周期"),
        "amount_low": _round(raw_range[0]) if raw_range else None,
        "amount_high": _round(raw_range[1]) if raw_range else None,
        "percent": percent,
        "monthly_low": monthly_low,
        "monthly_high": monthly_high,
        "quantified": quantified,
    }


def _variable_reason(kind: str, item: dict) -> str:
    if item["quantified"]:
        return (
            f"{VARIABLE_LABELS.get(kind, '浮动收入')} {_fmt(item['amount_low'])}–{_fmt(item['amount_high'])} 元"
            f"/{item['period_label']} 折月 {_fmt(item['monthly_low'])}–{_fmt(item['monthly_high'])} 元，计入含浮动月薪"
        )
    if item["percent"] is not None:
        return f"{VARIABLE_LABELS.get(kind, '浮动收入')}按 {_fmt(item['percent'])}% 计，未给出基数，只打标不计数"
    if item["amount_low"] is not None:
        return f"{VARIABLE_LABELS.get(kind, '浮动收入')} {_fmt(item['amount_low'])}–{_fmt(item['amount_high'])} 元未注明周期，只打标不计数"
    return f"{VARIABLE_LABELS.get(kind, '浮动收入')}未给出金额，只打标不计数"


def parse_salary(raw: str | None) -> dict:
    original = (raw or "").strip()
    text = normalize_raw(original)
    if not text:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="薪资原值为空",
            basis=f"原值「{original}」：空值，无法归一",
        )
    if NEGOTIABLE_PATTERN.search(text):
        return _result(
            ParseStatus.NEGOTIABLE.value,
            raw=original,
            reason="面议无区间",
            basis=f"原值「{original}」：面议，无具体区间，按月薪不可比档位入库（confidence 0.2）",
            confidence=0.2,
        )

    steps: list[str] = [f"字符归一：「{original}」→「{text}」"]

    work = text
    months = 12
    months_explicit = False
    months_match = MONTHS_PATTERN.search(work)
    if months_match:
        months = max(MONTH_MIN, min(MONTH_MAX, int(months_match.group(1))))
        months_explicit = True
        steps.append(f"提取发薪月数：{months} 薪（合法区间 {MONTH_MIN}–{MONTH_MAX}）")
        work = f"{work[: months_match.start()]} {work[months_match.end():]}"
    else:
        steps.append("未标注发薪月数，按 12 薪计")

    period = _detect_period(work)
    if period == "conflict":
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="计算周期矛盾：同时出现年薪与日薪",
            basis=f"原值「{original}」：同时出现年薪/年包与日薪/元每天写法，无法确定计价周期",
            period=PayPeriod.UNKNOWN.value,
            months=months,
            months_explicit=months_explicit,
        )
    steps.append(f"识别计算周期：{_period_label(period)}")
    annual_mode = period == PayPeriod.YEAR.value

    segments = [item for item in SEGMENT_SPLIT.split(work) if item.strip()]
    if not segments:
        segments = [work]

    base_matches: list[tuple[str, str]] = []
    total_matches: list[tuple[str, str]] = []
    plain_matches: list[tuple[str, str]] = []
    variable_items: list[dict] = []
    included_in_total = False

    for segment in segments:
        lower = segment.strip()
        if not lower:
            continue
        percent_only = PERCENT_PATTERN.search(lower) and not _amount_matches(lower)
        if _has_any(lower, INCLUDED_MARKERS):
            included_in_total = True
            total_matches.extend(_amount_matches(lower))
            continue
        if _has_any(lower, BASE_MARKERS):
            base_matches.extend(_amount_matches(lower))
            continue
        kind = _variable_keyword(lower)
        if kind is not None:
            variable_items.append(_parse_variable_item(lower, period, kind))
            continue
        if percent_only:
            variable_items.append(
                {
                    "kind": "other",
                    "label": "浮动比例（未标注项目）",
                    "raw": lower,
                    "period": "unknown",
                    "period_label": "未标注周期",
                    "amount_low": None,
                    "amount_high": None,
                    "percent": float(PERCENT_PATTERN.search(lower).group(1)),
                    "monthly_low": None,
                    "monthly_high": None,
                    "quantified": False,
                }
            )
            continue
        if _has_any(lower, TOTAL_MARKERS):
            total_matches.extend(_amount_matches(lower))
            continue
        plain_matches.extend(_amount_matches(lower))

    if not base_matches and not total_matches and not plain_matches:
        reason = "未识别到金额"
        if variable_items:
            reason = "只识别到浮动收入，未识别到固定/总额金额"
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason=reason,
            basis=f"原值「{original}」：{reason}，进入不可比清单",
            period=period,
            months=months,
            months_explicit=months_explicit,
            variable_items=variable_items,
            basis_steps=steps,
        )

    fixed_matches = base_matches or (total_matches if not base_matches and not plain_matches else plain_matches)
    if base_matches and total_matches:
        fixed_source, total_source = base_matches, total_matches
    elif base_matches:
        fixed_source, total_source = base_matches, []
    elif total_matches and not plain_matches:
        fixed_source, total_source = [], total_matches
    else:
        fixed_source, total_source = plain_matches, []

    fixed_range = _range_from_matches(fixed_source)
    total_range = _range_from_matches(total_source) if total_source else None
    if fixed_range is None and total_range is None:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="未识别到金额",
            basis=f"原值「{original}」：未识别到可用的固定或总额金额",
            period=period,
            months=months,
            months_explicit=months_explicit,
            variable_items=variable_items,
            basis_steps=steps,
        )

    if fixed_range and fixed_range[0] > fixed_range[1]:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="区间矛盾：下限高于上限",
            basis=f"原值「{original}」：固定收入下限 {_fmt(fixed_range[0])} 高于上限 {_fmt(fixed_range[1])}，判为矛盾数据",
            period=period,
            months=months,
            months_explicit=months_explicit,
            basis_steps=steps,
        )
    if total_range and total_range[0] > total_range[1]:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="区间矛盾：下限高于上限",
            basis=f"原值「{original}」：总额下限 {_fmt(total_range[0])} 高于上限 {_fmt(total_range[1])}，判为矛盾数据",
            period=period,
            months=months,
            months_explicit=months_explicit,
            basis_steps=steps,
        )

    fixed_monthly = None
    if fixed_range:
        fixed_low = _monthly_from(fixed_range[0], period, months)
        fixed_high = _monthly_from(fixed_range[1], period, months)
        fixed_monthly = (fixed_low, fixed_high)

    total_monthly = None
    if total_range:
        total_low = _monthly_from(total_range[0], period, months)
        total_high = _monthly_from(total_range[1], period, months)
        total_monthly = (total_low, total_high)

    variable_low_sum = sum(item["monthly_low"] for item in variable_items if item["quantified"] and item["monthly_low"] is not None)
    variable_high_sum = sum(item["monthly_high"] for item in variable_items if item["quantified"] and item["monthly_high"] is not None)
    variable_known = any(item["quantified"] for item in variable_items)
    variable_unquantified = any(not item["quantified"] for item in variable_items)

    if fixed_monthly and variable_known:
        total_monthly = (fixed_monthly[0] + variable_low_sum, fixed_monthly[1] + variable_high_sum)
    if total_monthly and fixed_monthly and total_monthly[0] < fixed_monthly[0] - 1:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="口径矛盾：总额低于底薪",
            basis=f"原值「{original}」：总额折月 {_fmt(total_monthly[0])} 低于底薪折月 {_fmt(fixed_monthly[0])}",
            period=period,
            months=months,
            months_explicit=months_explicit,
            basis_steps=steps,
        )

    if total_monthly:
        comparable = total_monthly
    elif fixed_monthly:
        comparable = fixed_monthly
    else:
        comparable = None
    assert comparable is not None

    if comparable[0] < MONTHLY_FLOOR or comparable[1] > MONTHLY_CEIL:
        return _result(
            ParseStatus.UNPARSED.value,
            raw=original,
            reason="量级超出月薪可比范围",
            basis=(
                f"原值「{original}」：折月后区间 {_fmt(comparable[0])}-{_fmt(comparable[1])} "
                f"超出可比范围 {MONTHLY_FLOOR}-{MONTHLY_CEIL}"
            ),
            period=period,
            months=months,
            months_explicit=months_explicit,
            basis_steps=steps,
        )

    quoted_range = total_range or fixed_range
    assert quoted_range is not None
    quoted_low, quoted_high = _round(quoted_range[0]), _round(quoted_range[1])

    if fixed_monthly:
        fixed_round = (_round(fixed_monthly[0]), _round(fixed_monthly[1]))
    else:
        fixed_round = (None, None)  # type: ignore[assignment]
    if total_monthly:
        total_round = (_round(total_monthly[0]), _round(total_monthly[1]))
    else:
        total_round = (None, None)  # type: ignore[assignment]

    comparable_round = (
        _round(comparable[0]),
        _round(comparable[1]),
        _round((comparable[0] + comparable[1]) / 2),
    )

    # 兼容旧字段：salary_low/high = 名义月薪（年薪先 ÷ 12、日薪按 21.75 天折月），
    # monthly_* = 固定月薪 × 12 ÷ months（日/年薪已折月，月数不再重复折算）
    if period == PayPeriod.YEAR.value:
        nominal_low, nominal_high = _round(quoted_range[0] / 12), _round(quoted_range[1] / 12)
    elif period == PayPeriod.DAY.value:
        nominal_low, nominal_high = _round(quoted_range[0] * WORKDAYS_PER_MONTH), _round(quoted_range[1] * WORKDAYS_PER_MONTH)
    else:
        nominal_low, nominal_high = quoted_low, quoted_high
    if fixed_monthly:
        legacy_monthly = fixed_round
        legacy_median = _round(((fixed_monthly[0] + fixed_monthly[1]) / 2))
    else:
        legacy_monthly = total_round
        legacy_median = _round(((total_monthly[0] + total_monthly[1]) / 2)) if total_monthly else None

    if included_in_total:
        scope = VariableScope.INCLUDED_UNQUANTIFIED.value
    elif variable_unquantified:
        scope = VariableScope.UNQUANTIFIED.value
    elif variable_known:
        scope = VariableScope.QUANTIFIED.value
    elif base_matches:
        scope = VariableScope.FIXED_ONLY.value
    else:
        scope = VariableScope.NONE.value

    conversion_target = "固定月薪" if fixed_monthly else "总额月薪"
    conversion_low = fixed_round[0] if fixed_monthly else total_round[0]
    conversion_high = fixed_round[1] if fixed_monthly else total_round[1]
    if period == PayPeriod.YEAR.value:
        steps.append(
            f"年薪折月：{_fmt(quoted_low)}–{_fmt(quoted_high)} 元/年 ÷ 12 = "
            f"{conversion_target} {_fmt(conversion_low)}–{_fmt(conversion_high)} 元/月"
        )
    elif period == PayPeriod.DAY.value:
        steps.append(
            f"日薪折月：{_fmt(quoted_low)}–{_fmt(quoted_high)} 元/天 × {_fmt(WORKDAYS_PER_MONTH)} 工作日/月 = "
            f"{conversion_target} {_fmt(conversion_low)}–{_fmt(conversion_high)} 元/月"
        )
    else:
        steps.append(
            f"月薪折月：名义 {_fmt(quoted_low)}–{_fmt(quoted_high)} 元 × 12 ÷ {months} 薪 = "
            f"{conversion_target} {_fmt(conversion_low)}–{_fmt(conversion_high)} 元/月"
        )
    steps.extend(_variable_reason(item["kind"], item) for item in variable_items)
    if fixed_monthly and variable_known and total_round[0] is not None:
        steps.append(
            f"含浮动月薪 = 固定 {_fmt(fixed_round[0])}–{_fmt(fixed_round[1])} + 浮动 "
            f"{_fmt(variable_low_sum)}–{_fmt(variable_high_sum)} = "
            f"{_fmt(total_round[0])}–{_fmt(total_round[1])} 元/月"
        )
    if scope == VariableScope.QUANTIFIED.value:
        steps.append("浮动收入已量化，可比口径取含浮动月薪")
    elif scope == VariableScope.UNQUANTIFIED.value:
        steps.append("浮动收入未量化，可比口径只取固定月薪（底薪），排序时按底薪口径标注")
    elif scope == VariableScope.INCLUDED_UNQUANTIFIED.value:
        steps.append("原值声明总额已含浮动，但无法拆分固定与浮动，可比口径使用总额并标注")
    elif scope == VariableScope.FIXED_ONLY.value:
        steps.append("仅给出底薪/固定工资，未提浮动收入，可比口径为固定月薪")
    else:
        steps.append("无浮动收入，可比口径为固定月薪")
    if not fixed_monthly and total_monthly:
        steps.append("固定与浮动无法拆分：含浮动月薪字段留空，总额口径单独保留")

    confidence = 0.95
    if quoted_range[0] == quoted_range[1]:
        confidence -= 0.12
    used_source = total_source if (total_range and not fixed_range) else fixed_source
    if any(not unit for _, unit in used_source):
        confidence -= 0.05
    if months_explicit and months != 12 and period == PayPeriod.MONTH.value:
        confidence -= 0.03
    if period == PayPeriod.YEAR.value:
        confidence -= 0.08
    if period == PayPeriod.DAY.value:
        confidence -= 0.1
    if variable_unquantified:
        confidence -= 0.1
    elif variable_known:
        confidence -= 0.03
    if included_in_total:
        confidence -= 0.12
    confidence = round(max(0.3, confidence), 2)

    basis = "；".join(steps)
    return _result(
        ParseStatus.PARSED.value,
        raw=original,
        basis=basis,
        period=period,
        months=months,
        months_explicit=months_explicit,
        quoted_low=quoted_low,
        quoted_high=quoted_high,
        salary_low=nominal_low,
        salary_high=nominal_high,
        fixed_monthly_low=fixed_round[0],
        fixed_monthly_high=fixed_round[1],
        variable_monthly_low=_round(variable_low_sum) if variable_known else None,
        variable_monthly_high=_round(variable_high_sum) if variable_known else None,
        total_monthly_low=total_round[0],
        total_monthly_high=total_round[1],
        comparable_monthly_low=comparable_round[0],
        comparable_monthly_high=comparable_round[1],
        comparable_monthly_median=comparable_round[2],
        monthly_low=legacy_monthly[0],
        monthly_high=legacy_monthly[1],
        monthly_median=legacy_median,
        annual_total=_round(_annual_total_from(sum(quoted_range) / 2, period, months)) if annual_mode else None,
        confidence=confidence,
        has_variable=bool(variable_items),
        variable_items=variable_items,
        variable_scope=scope,
        basis_steps=steps,
    )


def parse_many(raws: list[str]) -> dict:
    """批量归一：保留输入顺序，输出 unparsed 清单与失败率。"""
    items = [parse_salary(raw) for raw in raws]
    unparsed = [
        {"index": index, "raw": item["raw"], "reason": item["reason"]}
        for index, item in enumerate(items)
        if item["status"] == ParseStatus.UNPARSED.value
    ]
    total = len(items)
    parsed = sum(1 for item in items if item["status"] == ParseStatus.PARSED.value)
    negotiable = sum(1 for item in items if item["status"] == ParseStatus.NEGOTIABLE.value)
    variable = sum(1 for item in items if item.get("has_variable"))
    variable_unquantified = sum(
        1 for item in items if item.get("variable_scope") == VariableScope.UNQUANTIFIED.value
    )
    stats = {
        "total": total,
        "parsed": parsed,
        "negotiable": negotiable,
        "unparsed": len(unparsed),
        "with_variable": variable,
        "variable_unquantified": variable_unquantified,
        "fail_rate": round(len(unparsed) / total, 4) if total else 0.0,
        "noncomparable_rate": round((len(unparsed) + negotiable) / total, 4) if total else 0.0,
    }
    return {"items": items, "unparsed": unparsed, "stats": stats}
