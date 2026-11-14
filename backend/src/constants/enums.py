"""共享枚举（后端唯一定义处）。前端副本见 frontend/site/js/config.js。

README「共享枚举出现位置」一节列出全部出现点，改动需两侧同步。
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class ChannelKind(StrEnum):
    """渠道接入方式：招聘站点 / 接口对接 / 文件导入 / 手工登记。"""

    SITE = "site"
    API = "api"
    FILE = "file"
    MANUAL = "manual"


CHANNEL_KIND_LABELS: dict[str, str] = {
    ChannelKind.SITE.value: "招聘站点",
    ChannelKind.API.value: "接口对接",
    ChannelKind.FILE.value: "文件导入",
    ChannelKind.MANUAL.value: "手工登记",
}


class ParseStatus(StrEnum):
    """薪资口径归一结果：可比较 / 面议 / 不可解析。"""

    PARSED = "parsed"
    NEGOTIABLE = "negotiable"
    UNPARSED = "unparsed"


PARSE_STATUS_LABELS: dict[str, str] = {
    ParseStatus.PARSED.value: "已归一",
    ParseStatus.NEGOTIABLE.value: "面议",
    ParseStatus.UNPARSED.value: "不可比",
}

PARSE_STATUS_ORDER: list[str] = [
    ParseStatus.PARSED.value,
    ParseStatus.NEGOTIABLE.value,
    ParseStatus.UNPARSED.value,
]


class ClusterStatus(StrEnum):
    """归并簇状态：在架发布 / 已过期下线 / 已拆散待重算。"""

    ACTIVE = "active"
    EXPIRED = "expired"
    MERGED = "merged"


CLUSTER_STATUS_LABELS: dict[str, str] = {
    ClusterStatus.ACTIVE.value: "在架",
    ClusterStatus.EXPIRED.value: "已过期",
    ClusterStatus.MERGED.value: "已拆散待重算",
}

CLUSTER_STATUS_ORDER: list[str] = [
    ClusterStatus.ACTIVE.value,
    ClusterStatus.EXPIRED.value,
    ClusterStatus.MERGED.value,
]


class ReviewDecision(StrEnum):
    MERGE = "merge"
    SPLIT = "split"
    KEEP = "keep"


REVIEW_DECISION_LABELS: dict[str, str] = {
    ReviewDecision.MERGE.value: "确认合并",
    ReviewDecision.SPLIT.value: "拆分为独立岗位",
    ReviewDecision.KEEP.value: "保持原样",
}

REVIEW_DECISION_ORDER: list[str] = [
    ReviewDecision.MERGE.value,
    ReviewDecision.SPLIT.value,
    ReviewDecision.KEEP.value,
]


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


RUN_STATUS_LABELS: dict[str, str] = {
    RunStatus.QUEUED.value: "排队中",
    RunStatus.RUNNING.value: "执行中",
    RunStatus.SUCCESS.value: "成功",
    RunStatus.PARTIAL.value: "部分成功",
    RunStatus.FAILED.value: "失败",
}


class TriggerKind(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SEED = "seed"


TRIGGER_LABELS: dict[str, str] = {
    TriggerKind.MANUAL.value: "手动",
    TriggerKind.SCHEDULE.value: "定时",
    TriggerKind.SEED.value: "初始化",
}


class Degree(StrEnum):
    ANY = "any"
    COLLEGE = "college"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTOR = "doctor"


DEGREE_LABELS: dict[str, str] = {
    Degree.ANY.value: "不限",
    Degree.COLLEGE.value: "大专",
    Degree.BACHELOR.value: "本科",
    Degree.MASTER.value: "硕士",
    Degree.DOCTOR.value: "博士",
}

DEGREE_ORDER: list[str] = [item.value for item in Degree]


class Experience(StrEnum):
    ANY = "any"
    JUNIOR = "1-3"
    MIDDLE = "3-5"
    SENIOR = "5-10"
    EXPERT = "10+"


EXPERIENCE_LABELS: dict[str, str] = {
    Experience.ANY.value: "不限",
    Experience.JUNIOR.value: "1-3 年",
    Experience.MIDDLE.value: "3-5 年",
    Experience.SENIOR.value: "5-10 年",
    Experience.EXPERT.value: "10 年以上",
}

EXPERIENCE_ORDER: list[str] = [item.value for item in Experience]


# 薪资区间的元数据：用于前端下拉与后端校验
DEGREE_UNKNOWN_LABEL = "未标注"
EXPERIENCE_UNKNOWN_LABEL = "未标注"


class PayPeriod(StrEnum):
    """薪资计算周期：原值按什么周期计价。"""

    MONTH = "month"
    YEAR = "year"
    DAY = "day"
    UNKNOWN = "unknown"


PAY_PERIOD_LABELS: dict[str, str] = {
    PayPeriod.MONTH.value: "月薪",
    PayPeriod.YEAR.value: "年薪",
    PayPeriod.DAY.value: "日薪",
    PayPeriod.UNKNOWN.value: "未标注",
}

PAY_PERIOD_ORDER: list[str] = [
    PayPeriod.MONTH.value,
    PayPeriod.YEAR.value,
    PayPeriod.DAY.value,
    PayPeriod.UNKNOWN.value,
]


class SalaryStatus(StrEnum):
    """归并后薪资包状态：单一口径可比 / 多来源不一致待复核 / 全部来源不可比。"""

    COMPARABLE = "comparable"
    INCONSISTENT = "inconsistent"
    NONCOMPARABLE = "noncomparable"


SALARY_STATUS_LABELS: dict[str, str] = {
    SalaryStatus.COMPARABLE.value: "可比",
    SalaryStatus.INCONSISTENT.value: "多来源不一致待复核",
    SalaryStatus.NONCOMPARABLE.value: "全部不可比",
}

SALARY_STATUS_ORDER: list[str] = [
    SalaryStatus.COMPARABLE.value,
    SalaryStatus.INCONSISTENT.value,
    SalaryStatus.NONCOMPARABLE.value,
]


class VariableScope(StrEnum):
    """浮动收入的可比范围：无浮动 / 固定收入 / 浮动未量化 / 已量化计入 / 已含浮动无法拆分。"""

    NONE = "none"
    FIXED_ONLY = "fixed_only"
    UNQUANTIFIED = "unquantified"
    QUANTIFIED = "quantified"
    INCLUDED_UNQUANTIFIED = "included_unquantified"


VARIABLE_SCOPE_LABELS: dict[str, str] = {
    VariableScope.NONE.value: "无浮动收入",
    VariableScope.FIXED_ONLY.value: "仅固定收入",
    VariableScope.UNQUANTIFIED.value: "底薪（浮动未量化）",
    VariableScope.QUANTIFIED.value: "固定 + 已量化浮动",
    VariableScope.INCLUDED_UNQUANTIFIED.value: "总额（已含浮动，无法拆分）",
}
