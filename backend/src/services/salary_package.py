"""算法 A 的归并侧：从多条来源中选出一条完整、前后一致的薪资包。

规则（对应 README §10「归并后的薪资包」）：

1. 每条来源独立归一，绝不把不同来源的底薪、提成、发薪月数拼成一个区间；
2. 只有 `parsed` 且折月后区间完整的来源才是候选；
3. 候选之间按「薪资包签名」比较：发薪月数 + 固定月薪区间 + 浮动口径 + 含浮动月薪区间；
   签名完全一致才算可比一致；
4. 一致时只采用一条来源（最完整 → 置信度高 → 发布新 → id 小），其余来源保留原值与换算过程；
5. 不一致 / 部分来源面议或不可比 → `inconsistent`，不输出对外薪资，进入人工复核并列明差异；
6. 全部来源都不可比 → `noncomparable`，明确标出，不参与排序与发布。

本模块是纯函数，不访问数据库、不访问网络，供 dedupe / merge / cluster / export 共用。
"""
from __future__ import annotations

from src.constants.enums import (
    ParseStatus,
    PayPeriod,
    SALARY_STATUS_LABELS,
    SalaryStatus,
    VariableScope,
    VARIABLE_SCOPE_LABELS,
)

SCOPE_RANK = {
    VariableScope.QUANTIFIED.value: 0,
    VariableScope.FIXED_ONLY.value: 1,
    VariableScope.NONE.value: 2,
    VariableScope.INCLUDED_UNQUANTIFIED.value: 3,
    VariableScope.UNQUANTIFIED.value: 4,
}

PERIOD_LABELS = {
    PayPeriod.MONTH.value: "月薪",
    PayPeriod.YEAR.value: "年薪",
    PayPeriod.DAY.value: "日薪",
    PayPeriod.UNKNOWN.value: "未标注",
}


def _int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def money_range(low: int | None, high: int | None) -> str:
    if low is None or high is None:
        return "不可比"
    if low == high:
        return f"{_fmt(low)} 元"
    return f"{_fmt(low)}–{_fmt(high)} 元"


def scope_label(scope: str) -> str:
    return VARIABLE_SCOPE_LABELS.get(scope, scope)


def status_label(status: str) -> str:
    return SALARY_STATUS_LABELS.get(status, status)


def _package_from_json(member: dict) -> dict | None:
    package = member.get("salary_package") or member.get("package")
    if isinstance(package, dict) and package.get("raw") is not None:
        return package
    return None


def _package_from_legacy(member: dict) -> dict:
    """老数据兼容：只有 legacy 列时构造一个最小薪资包，仍保留原值与口径说明。"""
    return {
        "status": member.get("salary_status") or "unparsed",
        "reason": member.get("salary_reason"),
        "raw": member.get("salary_raw") or "",
        "period": member.get("salary_period") or PayPeriod.UNKNOWN.value,
        "months": member.get("months") or 12,
        "months_explicit": bool(member.get("months_explicit")),
        "quoted_low": member.get("salary_low"),
        "quoted_high": member.get("salary_high"),
        "fixed_monthly_low": member.get("monthly_low"),
        "fixed_monthly_high": member.get("monthly_high"),
        "variable_monthly_low": member.get("variable_monthly_low"),
        "variable_monthly_high": member.get("variable_monthly_high"),
        "total_monthly_low": member.get("total_monthly_low"),
        "total_monthly_high": member.get("total_monthly_high"),
        "comparable_monthly_low": member.get("comparable_monthly_low"),
        "comparable_monthly_high": member.get("comparable_monthly_high"),
        "comparable_monthly_median": member.get("comparable_monthly_median", member.get("monthly_median")),
        "monthly_low": member.get("monthly_low"),
        "monthly_high": member.get("monthly_high"),
        "monthly_median": member.get("monthly_median"),
        "confidence": member.get("salary_confidence") or 0.0,
        "has_variable": bool(member.get("has_variable")),
        "variable_items": member.get("variable_items") or [],
        "variable_scope": member.get("variable_scope") or VariableScope.NONE.value,
        "basis_steps": member.get("basis_steps") or ([member.get("salary_basis")] if member.get("salary_basis") else []),
        "norm_basis": member.get("salary_basis") or "",
    }


def member_package(member: dict) -> dict:
    package = _package_from_json(member) or _package_from_legacy(member)
    package = dict(package)
    for field in ("comparable_monthly_low", "comparable_monthly_high", "comparable_monthly_median"):
        package[field] = _int(package.get(field))
    for field in ("fixed_monthly_low", "fixed_monthly_high", "variable_monthly_low", "variable_monthly_high",
                  "total_monthly_low", "total_monthly_high", "monthly_low", "monthly_high", "monthly_median"):
        package[field] = _int(package.get(field))
    package["months"] = _int(package.get("months")) or 12
    package["has_variable"] = bool(package.get("has_variable"))
    package["variable_scope"] = package.get("variable_scope") or VariableScope.NONE.value
    package["variable_scope_label"] = scope_label(package["variable_scope"])
    package["period"] = package.get("period") or PayPeriod.UNKNOWN.value
    package["period_label"] = PERIOD_LABELS.get(package["period"], package["period"])
    package["basis_steps"] = list(package.get("basis_steps") or [])
    package["variable_items"] = list(package.get("variable_items") or [])
    return package


def source_row(member: dict, package: dict | None = None) -> dict:
    package = package or member_package(member)
    variable_labels = "、".join(item.get("label") or "浮动收入" for item in package["variable_items"]) or "无"
    return {
        "post_id": int(member.get("id") or 0),
        "external_id": member.get("external_id") or "",
        "channel_code": member.get("channel_code") or member.get("channel_name") or "",
        "channel_name": member.get("channel_name") or "",
        "company_raw": member.get("company_raw") or "",
        "title_raw": member.get("title_raw") or "",
        "city": member.get("city") or "",
        "salary_raw": package.get("raw") or member.get("salary_raw") or "",
        "status": package.get("status") or "unparsed",
        "reason": package.get("reason"),
        "period": package.get("period"),
        "period_label": package.get("period_label"),
        "months": package.get("months"),
        "months_explicit": bool(package.get("months_explicit")),
        "quoted_low": _int(package.get("quoted_low")),
        "quoted_high": _int(package.get("quoted_high")),
        "fixed_monthly_low": package.get("fixed_monthly_low"),
        "fixed_monthly_high": package.get("fixed_monthly_high"),
        "variable_monthly_low": package.get("variable_monthly_low"),
        "variable_monthly_high": package.get("variable_monthly_high"),
        "total_monthly_low": package.get("total_monthly_low"),
        "total_monthly_high": package.get("total_monthly_high"),
        "comparable_monthly_low": package.get("comparable_monthly_low"),
        "comparable_monthly_high": package.get("comparable_monthly_high"),
        "comparable_monthly_median": package.get("comparable_monthly_median"),
        "has_variable": package["has_variable"],
        "variable_scope": package["variable_scope"],
        "variable_scope_label": package["variable_scope_label"],
        "variable_items": package["variable_items"],
        "variable_labels": variable_labels,
        "confidence": round(float(package.get("confidence") or 0.0), 2),
        "published_ts": _published_key(member),
        "basis_steps": package["basis_steps"],
        "norm_basis": package.get("norm_basis") or "",
        "is_comparable": _is_candidate(package),
    }


def _is_candidate(package: dict) -> bool:
    return (
        package.get("status") == ParseStatus.PARSED.value
        and package.get("comparable_monthly_low") is not None
        and package.get("comparable_monthly_high") is not None
    )


def signature(package: dict) -> tuple:
    """薪资包签名：只有签名一致才认为多条来源描述的是同一个薪资包。"""
    return (
        package.get("months"),
        package.get("comparable_monthly_low"),
        package.get("comparable_monthly_high"),
        package.get("variable_scope"),
        package.get("variable_monthly_low"),
        package.get("variable_monthly_high"),
        bool(package.get("has_variable")),
    )


def _package_descriptor(package: dict) -> str:
    parts = [package.get("period_label") or "未标注周期", f"{package.get('months')} 薪"]
    if package.get("fixed_monthly_low") is not None:
        parts.append(f"固定月薪 {money_range(package['fixed_monthly_low'], package['fixed_monthly_high'])}")
    elif package.get("total_monthly_low") is not None:
        parts.append(f"总额月薪 {money_range(package['total_monthly_low'], package['total_monthly_high'])}")
    if package.get("has_variable"):
        parts.append(f"浮动：{package.get('variable_scope_label')}")
    else:
        parts.append("不含浮动")
    return " · ".join(parts)


def _adoption_order(row: dict, package: dict) -> tuple:
    return (
        SCOPE_RANK.get(package["variable_scope"], 9),
        0 if package.get("months_explicit") else 1,
        0 if package.get("quoted_low") != package.get("quoted_high") else 1,
        -round(float(package.get("confidence") or 0.0), 4),
        -float(row.get("published_ts") or 0.0),
        int(row.get("post_id") or 0),
    )


def _published_key(member: dict) -> float:
    value = member.get("published_at")
    if value is None:
        return 0.0
    if hasattr(value, "timestamp"):
        try:
            return value.timestamp()
        except (OverflowError, OSError):
            return 0.0
    return 0.0


def _group_sources(sources: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for row in sources:
        if not row["is_comparable"]:
            continue
        package = row["_package"]
        key = signature(package)
        group = groups.get(key)
        if group is None:
            group = {"key": key, "rows": [], "package": package}
            groups[key] = group
        group["rows"].append(row)
    return sorted(groups.values(), key=lambda item: (-len(item["rows"]), item["rows"][0]["post_id"]))


def _struct_diff(groups: list[dict]) -> list[dict]:
    diffs: list[dict] = []
    months = sorted({int(group["package"].get("months") or 12) for group in groups})
    if len(months) > 1:
        diffs.append(
            {
                "field": "months",
                "label": "发薪月数不同",
                "detail": " / ".join(f"{value} 薪" for value in months),
            }
        )
    scopes = sorted({group["package"]["variable_scope"] for group in groups})
    if len(scopes) > 1:
        diffs.append(
            {
                "field": "variable_scope",
                "label": "浮动收入口径不同",
                "detail": " / ".join(scope_label(value) for value in scopes),
            }
        )
    ranges = []
    for group in groups:
        package = group["package"]
        ranges.append(money_range(package.get("comparable_monthly_low"), package.get("comparable_monthly_high")))
    if len(set(ranges)) > 1:
        diffs.append(
            {
                "field": "comparable",
                "label": "可比月薪区间不同",
                "detail": " / ".join(ranges),
            }
        )
    variable_labels = sorted(
        {
            item.get("label") or "浮动收入"
            for group in groups
            for item in group["package"].get("variable_items") or []
        }
    )
    if len(variable_labels) > 1:
        diffs.append(
            {
                "field": "variable_items",
                "label": "浮动项目不同",
                "detail": " / ".join(variable_labels),
            }
        )
    return diffs


def select_package(members: list[dict]) -> dict:
    """对一个归并簇的全部成员选择薪资包。

    返回：
      status / status_label
      adopted: 采用的单条来源（含原值、换算过程）；不一致或全部不可比时为 None
      sources: 每条来源的完整薪资包（含是否被采用）
      differences: 复核用差异清单
      reason: 进入复核的原因（可直接写进 review_reason）
      low / high / median: 采用来源的可比月薪，绝不跨来源拼区间
    """
    ordered = sorted(members, key=lambda item: int(item.get("id") or 0))
    source_rows: list[dict] = []
    for member in ordered:
        package = member_package(member)
        row = source_row(member, package)
        row["_package"] = package
        source_rows.append(row)

    candidates = [row for row in source_rows if row["is_comparable"]]
    noncomparable = [row for row in source_rows if not row["is_comparable"]]
    groups = _group_sources(source_rows)

    differences: list[dict] = []
    reason_parts: list[str] = []
    adopted: dict | None = None

    if not candidates:
        status = SalaryStatus.NONCOMPARABLE.value
        reason_parts.append("全部来源薪资不可比（面议/不可解析），不参与排序与发布")
        differences.append(
            {
                "field": "all_noncomparable",
                "label": "全部来源不可比",
                "detail": "、".join(f"{row['channel_code']}「{row['salary_raw']}」" for row in source_rows),
            }
        )
    elif len(groups) > 1 or noncomparable:
        status = SalaryStatus.INCONSISTENT.value
        if len(groups) > 1:
            reason_parts.append(f"薪资包不一致：{len(groups)} 种口径")
            differences.append(
                {
                    "field": "package_groups",
                    "label": "来源薪资包分组",
                    "detail": "；".join(
                        f"{_package_descriptor(group['package'])}（{len(group['rows'])} 条："
                        f"{'、'.join(row['channel_code'] for row in group['rows'])}）"
                        for group in groups
                    ),
                }
            )
        differences.extend(_struct_diff(groups))
        if noncomparable:
            statuses = {}
            for row in noncomparable:
                statuses[row["status"]] = statuses.get(row["status"], 0) + 1
            detail = "、".join(
                f"{row['channel_code']}「{row['salary_raw']}」{row['reason'] or row['status']}"
                for row in noncomparable
            )
            differences.append(
                {
                    "field": "noncomparable_sources",
                    "label": "部分来源不可比，无法核对",
                    "detail": detail,
                }
            )
            status_words = {"negotiable": "面议", "unparsed": "不可比"}
            reason_parts.append(
                "；".join(f"{count} 条{status_words.get(key, key)}" for key, count in sorted(statuses.items()))
                + "来源未参与比对"
            )
    else:
        status = SalaryStatus.COMPARABLE.value
        best = min(
            (row for row in candidates),
            key=lambda row: _adoption_order(row, row["_package"]),
        )
        adopted = {key: value for key, value in best.items() if key != "_package"}
        adopted["basis_steps"] = list(best["basis_steps"])
        if len(source_rows) > 1:
            differences.append(
                {
                    "field": "equivalent_writings",
                    "label": "多种写法，折算后一致",
                    "detail": "；".join(f"{row['channel_code']}「{row['salary_raw']}」" for row in source_rows),
                }
            )

    for row in source_rows:
        row.pop("_package", None)
        row["adopted"] = bool(adopted and row["post_id"] == adopted["post_id"])

    low = high = median = None
    if adopted:
        low = adopted["comparable_monthly_low"]
        high = adopted["comparable_monthly_high"]
        median = adopted["comparable_monthly_median"]

    has_variable = any(row["has_variable"] for row in source_rows)
    if adopted:
        variable_scope = adopted["variable_scope"]
    elif source_rows:
        variable_scope = max(
            (row["variable_scope"] for row in source_rows),
            key=lambda value: SCOPE_RANK.get(value, 9),
        )
    else:
        variable_scope = VariableScope.NONE.value

    return {
        "status": status,
        "status_label": status_label(status),
        "adopted": adopted,
        "sources": source_rows,
        "differences": differences,
        "reason": "；".join(part for part in reason_parts if part),
        "low": low,
        "high": high,
        "median": median,
        "has_variable": has_variable,
        "variable_scope": variable_scope,
        "variable_scope_label": scope_label(variable_scope),
        "source_count": len(source_rows),
        "comparable_sources": len(candidates),
        "noncomparable_sources": len(noncomparable),
    }


def adopted_basis(package: dict) -> str:
    """对外展示的一句话口径：只用采用来源的换算过程。"""
    if not package:
        return ""
    return package.get("norm_basis") or "；".join(package.get("basis_steps") or [])
