"""归并簇服务：列表、详情（成员对照 + 两两相似度）、viewer 脱敏。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CLUSTER_STATUS_LABELS,
    DEGREE_LABELS,
    EXPERIENCE_LABELS,
    PARSE_STATUS_LABELS,
    SALARY_STATUS_LABELS,
    PAY_PERIOD_LABELS,
    Role,
    SalaryStatus,
)
from src.models.channel import Channel
from src.models.cluster import Cluster
from src.models.post import Post
from src.models.review import Review
from src.services import dedupe
from src.services.post_service import mask_company, mask_text
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc


def publish_state(cluster: Cluster, review: Review | None = None) -> tuple[bool, str]:
    """能否对外发布：薪资包必须可比、岗位未过期、复核结论不能是拆分。"""
    if cluster.salary_status != SalaryStatus.COMPARABLE.value:
        return False, SALARY_STATUS_LABELS.get(cluster.salary_status, cluster.salary_status)
    if cluster.status == "expired":
        return False, "岗位已过期"
    if cluster.status == "merged":
        return False, "已拆散待重算"
    if review is not None and review.decision == "split":
        return False, "复核结论为拆分"
    if cluster.needs_review and review is None:
        return False, "待人工复核"
    return True, "可对外发布"


def serialize(cluster: Cluster, role: str, review: Review | None = None) -> dict:
    viewer = role == Role.VIEWER.value
    company = mask_company(cluster.company_display) if viewer else cluster.company_display
    publishable, publish_reason = publish_state(cluster, review)
    return {
        "id": cluster.id,
        "run_id": cluster.run_id,
        "fingerprint": cluster.fingerprint,
        "blocking_key": cluster.blocking_key,
        "company_display": company,
        "company_norm": cluster.company_norm,
        "title_display": cluster.title_display,
        "title_stem": cluster.title_stem,
        "city": cluster.city,
        "salary_low": cluster.salary_low,
        "salary_high": cluster.salary_high,
        "monthly_median": cluster.monthly_median,
        "salary_basis": cluster.salary_basis,
        "salary_status": cluster.salary_status or SalaryStatus.NONCOMPARABLE.value,
        "salary_status_label": SALARY_STATUS_LABELS.get(
            cluster.salary_status or SalaryStatus.NONCOMPARABLE.value,
            cluster.salary_status or "",
        ),
        "salary_adopted_post_id": cluster.salary_adopted_post_id,
        "salary_source_count": cluster.salary_source_count or 0,
        "salary_comparable_sources": cluster.salary_comparable_sources or 0,
        "salary_noncomparable_sources": cluster.salary_noncomparable_sources or 0,
        "has_variable": bool(cluster.has_variable),
        "variable_scope": cluster.variable_scope or "none",
        "salary_differences": cluster.salary_differences or [],
        "publishable": publishable,
        "publish_reason": publish_reason,
        "channels": cluster.channels or [],
        "channel_count": cluster.channel_count,
        "member_count": cluster.member_count,
        "dup_removed": cluster.dup_removed,
        "degree": cluster.degree,
        "degree_label": DEGREE_LABELS.get(cluster.degree, cluster.degree),
        "experience": cluster.experience,
        "experience_label": EXPERIENCE_LABELS.get(cluster.experience, cluster.experience),
        "published_at": iso_utc(cluster.published_at),
        "expire_at": iso_utc(cluster.expire_at),
        "status": cluster.status,
        "status_label": CLUSTER_STATUS_LABELS.get(cluster.status, cluster.status),
        "confidence": round(cluster.confidence, 3),
        "needs_review": cluster.needs_review,
        "review_reason": cluster.review_reason or "",
        "golden_post_id": cluster.golden_post_id,
        "member_ids": cluster.member_ids or [],
        "review": {
            "decision": review.decision,
            "reviewer": review.reviewer,
            "note": review.note,
            "updated_at": iso_utc(review.updated_at),
        }
        if review
        else None,
        "created_at": iso_utc(cluster.created_at),
    }


def latest_run_id(db: Session) -> int | None:
    return db.scalar(select(func.max(Cluster.run_id)))


def list_clusters(
    db: Session,
    *,
    role: str,
    run_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    multi_only: bool = False,
    needs_review: bool | None = None,
    salary_status: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    target_run = run_id or latest_run_id(db)
    stmt = select(Cluster)
    count_stmt = select(func.count()).select_from(Cluster)
    if target_run:
        stmt = stmt.where(Cluster.run_id == target_run)
        count_stmt = count_stmt.where(Cluster.run_id == target_run)
    if status:
        stmt = stmt.where(Cluster.status == status)
        count_stmt = count_stmt.where(Cluster.status == status)
    if multi_only:
        stmt = stmt.where(Cluster.member_count > 1)
        count_stmt = count_stmt.where(Cluster.member_count > 1)
    if needs_review is not None:
        stmt = stmt.where(Cluster.needs_review.is_(needs_review))
        count_stmt = count_stmt.where(Cluster.needs_review.is_(needs_review))
    if salary_status:
        stmt = stmt.where(Cluster.salary_status == salary_status)
        count_stmt = count_stmt.where(Cluster.salary_status == salary_status)
    if q:
        like = f"%{q.strip()}%"
        clause = (
            Cluster.company_display.ilike(like)
            | Cluster.title_display.ilike(like)
            | Cluster.fingerprint.ilike(like)
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Cluster.member_count.desc(), Cluster.id).limit(limit).offset(offset)
    ).all()
    reviews = {review.cluster_id: review for review in db.scalars(select(Review)).all()}
    by_status = {
        key: int(count)
        for key, count in db.execute(
            select(Cluster.salary_status, func.count())
            .where(Cluster.run_id == target_run)
            .group_by(Cluster.salary_status)
        ).all()
    } if target_run else {}
    comparable = by_status.get(SalaryStatus.COMPARABLE.value, 0)
    inconsistent = by_status.get(SalaryStatus.INCONSISTENT.value, 0)
    noncomparable = by_status.get(SalaryStatus.NONCOMPARABLE.value, 0)
    return {
        "items": [serialize(row, role, reviews.get(row.id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "run_id": target_run,
        # 计数对账：三个薪资状态之和必须等于本运行的簇总数
        "salary_counts": {
            "comparable": comparable,
            "inconsistent": inconsistent,
            "noncomparable": noncomparable,
            "run_total": sum(by_status.values()),
        },
        "publish_counts": publish_counts(db, target_run),
    }


def publish_counts(db: Session, run_id: int | None) -> dict:
    """一次运行的发布就绪计数，供页面计数对账。"""
    if run_id is None:
        return {"publishable": 0, "blocked": 0}
    rows = db.scalars(select(Cluster).where(Cluster.run_id == run_id)).all()
    reviews = {review.cluster_id: review for review in db.scalars(select(Review)).all()}
    publishable = sum(1 for row in rows if publish_state(row, reviews.get(row.id))[0])
    return {"publishable": publishable, "blocked": len(rows) - publishable}


def get_cluster(db: Session, cluster_id: int, role: str) -> dict:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise AppError("NOT_FOUND", 404, {"entity": "cluster", "id": cluster_id})
    review = db.scalar(select(Review).where(Review.cluster_id == cluster.id))
    payload = serialize(cluster, role, review)
    payload["members"] = _members(db, cluster, role)
    viewer = role == Role.VIEWER.value
    sources = cluster.salary_sources or []
    adopted = cluster.salary_adopted or None
    if viewer:
        # 客户只读看不到精确公司名：来源清单里的公司字段同样脱敏
        sources = [dict(row) for row in sources]
        for row in sources:
            row["company_raw"] = mask_company(row.get("company_raw") or "")
        if adopted:
            adopted = dict(adopted)
            adopted["company_raw"] = mask_company(adopted.get("company_raw") or "")
    payload["salary_package"] = {
        "status": payload["salary_status"],
        "status_label": payload["salary_status_label"],
        "adopted": adopted,
        "sources": sources,
        "differences": cluster.salary_differences or [],
        "source_count": payload["salary_source_count"],
        "comparable_sources": payload["salary_comparable_sources"],
        "noncomparable_sources": payload["salary_noncomparable_sources"],
        "low": cluster.salary_low,
        "high": cluster.salary_high,
        "median": cluster.monthly_median,
        "has_variable": payload["has_variable"],
        "variable_scope": payload["variable_scope"],
        "run_id": cluster.run_id,
        "cluster_id": cluster.id,
    }
    return payload


def _members(db: Session, cluster: Cluster, role: str) -> list[dict]:
    ids = [int(item) for item in (cluster.member_ids or [])]
    if not ids:
        return []
    rows = db.scalars(select(Post).where(Post.id.in_(ids)).order_by(Post.id)).all()
    channels = {channel.id: channel for channel in db.scalars(select(Channel)).all()}
    viewer = role == Role.VIEWER.value
    prepared = []
    for row in rows:
        channel = channels.get(row.channel_id)
        prepared.append(
            {
                "id": row.id,
                "external_id": row.external_id,
                "channel_code": channel.code if channel else "",
                "channel_name": channel.name if channel else "",
                "company_raw": mask_company(row.company_raw) if viewer else row.company_raw,
                "title_raw": row.title_raw,
                "city": row.city,
                "salary_raw": row.salary_raw,
                "salary_status": row.salary_status,
                "salary_status_label": PARSE_STATUS_LABELS.get(row.salary_status, row.salary_status),
                "salary_period": row.salary_period,
                "salary_period_label": PAY_PERIOD_LABELS.get(row.salary_period, row.salary_period),
                "monthly_low": row.monthly_low,
                "monthly_high": row.monthly_high,
                "monthly_median": row.monthly_median,
                "comparable_monthly_low": row.comparable_monthly_low,
                "comparable_monthly_high": row.comparable_monthly_high,
                "comparable_monthly_median": row.comparable_monthly_median,
                "has_variable": row.has_variable,
                "variable_scope": row.variable_scope,
                "months": row.months,
                "salary_package": row.salary_package or {},
                "is_adopted": row.id == cluster.salary_adopted_post_id,
                "degree_label": DEGREE_LABELS.get(row.degree, row.degree),
                "experience_label": EXPERIENCE_LABELS.get(row.experience, row.experience),
                "published_at": iso_utc(row.published_at),
                "raw_text": mask_text(row.raw_text, row.company_raw) if viewer else row.raw_text,
                "is_golden": row.id == cluster.golden_post_id,
                "company_norm": row.company_norm,
                "title_stem": row.title_stem,
                "monthly_low_value": row.monthly_low,
                "monthly_high_value": row.monthly_high,
                "monthly_median_value": row.monthly_median,
                "degree": row.degree,
                "experience": row.experience,
            }
        )

    golden = next((item for item in prepared if item["is_golden"]), prepared[0])
    for item in prepared:
        scored = dedupe.similarity(item, golden)
        item["similarity"] = scored
        for key in ("monthly_low_value", "monthly_high_value", "monthly_median_value"):
            item.pop(key, None)
    return prepared
