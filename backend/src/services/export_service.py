"""导出服务：归并清单（含算法 A/B 结果） / 原始岗位口径对照 / 复核记录。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CLUSTER_STATUS_LABELS,
    DEGREE_LABELS,
    EXPERIENCE_LABELS,
    PARSE_STATUS_LABELS,
    PAY_PERIOD_LABELS,
    REVIEW_DECISION_LABELS,
    SALARY_STATUS_LABELS,
    TRIGGER_LABELS,
    VARIABLE_SCOPE_LABELS,
)
from src.models.channel import Channel
from src.models.cluster import Cluster
from src.models.post import Post
from src.models.review import Review
from src.models.run import Run
from src.services import run_service
from src.services.cluster_service import publish_state
from src.utils.csv_export import csv_data_rows as _csv_rows
from src.utils.csv_export import to_csv


def _stamp(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return value.strftime(fmt) if value else ""


def _package_value(post: Post, field: str):
    value = (post.salary_package or {}).get(field)
    return "" if value is None else value


def _variable_labels(post: Post) -> str:
    items = (post.salary_package or {}).get("variable_items") or []
    return "、".join(item.get("label") or "浮动收入" for item in items)


def clusters_csv(db: Session, run_id: int | None = None) -> bytes:
    target = run_id or (run_service.latest_run(db).id if run_service.latest_run(db) else None)
    stmt = select(Cluster).where(Cluster.run_id == target) if target else select(Cluster).where(False)
    clusters = db.scalars(stmt.order_by(Cluster.id)).all()
    run = db.get(Run, target) if target else None
    reviews = {review.cluster_id: review for review in db.scalars(select(Review)).all()}
    headers = [
        "簇ID", "运行编号", "指纹", "公司", "职位", "城市",
        "薪资包状态", "月薪下限", "月薪上限", "月薪中位",
        "是否含浮动", "浮动口径", "采用来源岗位ID", "来源数", "可比来源数", "不可比来源数",
        "薪资口径（采用来源）", "复核结论", "薪资包差异", "可否对外发布", "未发布原因",
        "渠道数", "渠道", "成员数", "消重条数", "置信度",
        "状态", "待复核", "学历", "经验", "最近发布", "过期时间", "归并阈值",
    ]
    rows = [
        [
            item.id,
            run.run_no if run else "",
            item.fingerprint,
            item.company_display,
            item.title_display,
            item.city,
            SALARY_STATUS_LABELS.get(item.salary_status, item.salary_status),
            item.salary_low if item.salary_low is not None else "",
            item.salary_high if item.salary_high is not None else "",
            item.monthly_median if item.monthly_median is not None else "不可比",
            "是" if item.has_variable else "否",
            VARIABLE_SCOPE_LABELS.get(item.variable_scope, item.variable_scope),
            item.salary_adopted_post_id or "",
            item.salary_source_count,
            item.salary_comparable_sources,
            item.salary_noncomparable_sources,
            item.salary_basis,
            REVIEW_DECISION_LABELS.get(reviews[item.id].decision, reviews[item.id].decision)
            if item.id in reviews
            else "",
            "；".join(
                f"{diff.get('label')}：{diff.get('detail')}" for diff in (item.salary_differences or [])
                if diff.get("field") != "equivalent_writings"
            ),
            "是" if publish_state(item, reviews.get(item.id))[0] else "否",
            publish_state(item, reviews.get(item.id))[1],
            item.channel_count,
            "、".join(item.channels or []),
            item.member_count,
            item.dup_removed,
            f"{item.confidence:.3f}",
            CLUSTER_STATUS_LABELS.get(item.status, item.status),
            "是" if item.needs_review else "否",
            DEGREE_LABELS.get(item.degree, item.degree),
            EXPERIENCE_LABELS.get(item.experience, item.experience),
            _stamp(item.published_at, "%Y-%m-%d"),
            _stamp(item.expire_at, "%Y-%m-%d"),
            f"{run.threshold:.2f}" if run else "",
        ]
        for item in clusters
    ]
    return to_csv(headers, rows)


def posts_csv(db: Session) -> bytes:
    rows = db.execute(select(Post, Channel).join(Channel, Post.channel_id == Channel.id).order_by(Post.id)).all()
    headers = [
        "岗位ID", "渠道编码", "渠道名称", "外部ID", "公司", "公司归一", "职位", "职位词干", "城市",
        "薪资原值", "计算周期", "口径状态", "原值区间下限", "原值区间上限",
        "名义月薪下限", "名义月薪上限", "发薪月数",
        "固定月薪下限", "固定月薪上限", "浮动月薪下限", "浮动月薪上限",
        "含浮动月薪下限", "含浮动月薪上限", "可比月薪下限", "可比月薪上限", "可比月薪中位",
        "是否含浮动", "浮动口径", "浮动项目",
        "口径说明", "换算过程", "置信度", "学历", "经验", "发布时间", "过期时间",
    ]
    body = [
        [
            post.id,
            channel.code,
            channel.name,
            post.external_id,
            post.company_raw,
            post.company_norm,
            post.title_raw,
            post.title_stem,
            post.city,
            post.salary_raw,
            PAY_PERIOD_LABELS.get(post.salary_period, post.salary_period),
            PARSE_STATUS_LABELS.get(post.salary_status, post.salary_status),
            _package_value(post, "quoted_low"),
            _package_value(post, "quoted_high"),
            post.salary_low if post.salary_low is not None else "",
            post.salary_high if post.salary_high is not None else "",
            post.months,
            _package_value(post, "fixed_monthly_low"),
            _package_value(post, "fixed_monthly_high"),
            _package_value(post, "variable_monthly_low"),
            _package_value(post, "variable_monthly_high"),
            _package_value(post, "total_monthly_low"),
            _package_value(post, "total_monthly_high"),
            post.comparable_monthly_low if post.comparable_monthly_low is not None else "",
            post.comparable_monthly_high if post.comparable_monthly_high is not None else "",
            post.comparable_monthly_median if post.comparable_monthly_median is not None else "不可比",
            "是" if post.has_variable else "否",
            VARIABLE_SCOPE_LABELS.get(post.variable_scope, post.variable_scope),
            _variable_labels(post),
            post.salary_basis,
            "；".join((post.salary_package or {}).get("basis_steps") or []),
            f"{post.salary_confidence:.2f}",
            DEGREE_LABELS.get(post.degree, post.degree),
            EXPERIENCE_LABELS.get(post.experience, post.experience),
            _stamp(post.published_at, "%Y-%m-%d"),
            _stamp(post.expire_at, "%Y-%m-%d"),
        ]
        for post, channel in rows
    ]
    return to_csv(headers, body)


def csv_data_rows(payload: bytes) -> list[list[str]]:
    """对账用：解析含 BOM 的 CSV，返回除表头外的数据行。"""
    return _csv_rows(payload)


def csv_headers(payload: bytes) -> list[str]:
    from src.utils.csv_export import csv_header

    return csv_header(payload)


def cluster_sources_csv(db: Session, run_id: int | None = None) -> bytes:
    """每个归并簇的每条来源一行：原值、周期、固定/浮动、换算过程、是否被采用。"""
    target = run_id or (run_service.latest_run(db).id if run_service.latest_run(db) else None)
    stmt = select(Cluster).where(Cluster.run_id == target) if target else select(Cluster).where(False)
    clusters = db.scalars(stmt.order_by(Cluster.id)).all()
    run = db.get(Run, target) if target else None
    headers = [
        "簇ID", "运行编号", "指纹", "公司", "职位", "城市", "薪资包状态",
        "来源岗位ID", "渠道", "外部ID", "薪资原值", "计算周期", "发薪月数",
        "口径状态", "原值区间下限", "原值区间上限",
        "固定月薪下限", "固定月薪上限", "浮动月薪下限", "浮动月薪上限",
        "含浮动月薪下限", "含浮动月薪上限", "可比月薪下限", "可比月薪上限", "可比月薪中位",
        "是否含浮动", "浮动口径", "浮动项目", "是否被采用", "换算过程",
    ]
    body = []
    for cluster in clusters:
        for source in cluster.salary_sources or []:
            body.append(
                [
                    cluster.id,
                    run.run_no if run else "",
                    cluster.fingerprint,
                    cluster.company_display,
                    cluster.title_display,
                    cluster.city,
                    SALARY_STATUS_LABELS.get(cluster.salary_status, cluster.salary_status),
                    source.get("post_id"),
                    source.get("channel_code"),
                    source.get("external_id"),
                    source.get("salary_raw"),
                    PAY_PERIOD_LABELS.get(source.get("period"), source.get("period")),
                    source.get("months"),
                    PARSE_STATUS_LABELS.get(source.get("status"), source.get("status")),
                    source.get("quoted_low"),
                    source.get("quoted_high"),
                    source.get("fixed_monthly_low"),
                    source.get("fixed_monthly_high"),
                    source.get("variable_monthly_low"),
                    source.get("variable_monthly_high"),
                    source.get("total_monthly_low"),
                    source.get("total_monthly_high"),
                    source.get("comparable_monthly_low"),
                    source.get("comparable_monthly_high"),
                    source.get("comparable_monthly_median"),
                    "是" if source.get("has_variable") else "否",
                    VARIABLE_SCOPE_LABELS.get(source.get("variable_scope"), source.get("variable_scope")),
                    source.get("variable_labels"),
                    "是" if source.get("adopted") else "否",
                    "；".join(source.get("basis_steps") or []),
                ]
            )
    return to_csv(headers, body)


def reviews_csv(db: Session) -> bytes:
    reviews = db.scalars(select(Review).order_by(Review.id)).all()
    clusters = {item.id: item for item in db.scalars(select(Cluster)).all()}
    runs = {item.id: item for item in db.scalars(select(Run)).all()}
    headers = [
        "复核ID", "簇ID", "运行编号", "公司", "职位", "城市", "成员数",
        "薪资包状态", "采用来源岗位ID", "来源数", "差异说明",
        "结论", "复核人", "备注", "复核时间",
    ]
    body = []
    for review in reviews:
        cluster = clusters.get(review.cluster_id)
        run = runs.get(review.run_id or 0)
        body.append(
            [
                review.id,
                review.cluster_id,
                run.run_no if run else "",
                cluster.company_display if cluster else "",
                cluster.title_display if cluster else "",
                cluster.city if cluster else "",
                cluster.member_count if cluster else "",
                SALARY_STATUS_LABELS.get(cluster.salary_status, cluster.salary_status) if cluster else "",
                (cluster.salary_adopted_post_id or "") if cluster else "",
                cluster.salary_source_count if cluster else "",
                "；".join(
                    f"{diff.get('label')}：{diff.get('detail')}" for diff in (cluster.salary_differences or [])
                )
                if cluster
                else "",
                REVIEW_DECISION_LABELS.get(review.decision, review.decision),
                review.reviewer,
                review.note or "",
                _stamp(review.updated_at),
            ]
        )
    return to_csv(headers, body)


def runs_csv(db: Session) -> bytes:
    runs = db.scalars(select(Run).order_by(Run.id)).all()
    headers = [
        "运行编号", "触发方式", "状态", "阈值", "原始岗位", "归并簇", "消重条数",
        "可比簇（运行时刻）", "不一致簇（运行时刻）", "全部不可比簇（运行时刻）",
        "不可比占比", "操作人", "开始时间", "结束时间",
    ]
    body = [
        [
            run.run_no,
            TRIGGER_LABELS.get(run.trigger, run.trigger),
            run.status,
            f"{run.threshold:.2f}",
            run.posts_in,
            run.clusters_out,
            run.dupes_removed,
            (run.metrics or {}).get("salary_comparable", 0),
            (run.metrics or {}).get("salary_inconsistent", 0),
            (run.metrics or {}).get("salary_noncomparable", 0),
            f"{(run.metrics or {}).get('noncomparable_rate', 0) * 100:.2f}%",
            run.operator_email,
            _stamp(run.started_at),
            _stamp(run.finished_at),
        ]
        for run in runs
    ]
    return to_csv(headers, body)
