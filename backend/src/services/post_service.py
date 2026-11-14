"""原始岗位服务：筛选、详情、薪资口径列对照；viewer 精确公司名脱敏。"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    DEGREE_LABELS,
    EXPERIENCE_LABELS,
    PARSE_STATUS_LABELS,
    PAY_PERIOD_LABELS,
    VARIABLE_SCOPE_LABELS,
    Role,
)

SALARY_STATUSES = ("parsed", "negotiable", "unparsed")
from src.models.channel import Channel
from src.models.post import Post
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc



def mask_company(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        return "某单位"
    head = cleaned[0]
    return f"{head}****（脱敏）"


def mask_text(text: str, company_raw: str) -> str:
    if not text or not company_raw:
        return text
    return text.replace(company_raw, mask_company(company_raw))


def serialize(post: Post, channel: Channel | None, role: str) -> dict:
    viewer = role == Role.VIEWER.value
    company = mask_company(post.company_raw) if viewer else post.company_raw
    payload = {
        "id": post.id,
        "external_id": post.external_id,
        "channel_id": post.channel_id,
        "channel_code": channel.code if channel else None,
        "channel_name": channel.name if channel else None,
        "company_raw": company,
        "company_norm": post.company_norm,
        "title_raw": post.title_raw,
        "title_stem": post.title_stem,
        "city": post.city,
        "degree": post.degree,
        "degree_label": DEGREE_LABELS.get(post.degree, post.degree),
        "experience": post.experience,
        "experience_label": EXPERIENCE_LABELS.get(post.experience, post.experience),
        "salary_raw": post.salary_raw,
        "salary_status": post.salary_status,
        "salary_status_label": PARSE_STATUS_LABELS.get(post.salary_status, post.salary_status),
        "salary_low": post.salary_low,
        "salary_high": post.salary_high,
        "months": post.months,
        "monthly_low": post.monthly_low,
        "monthly_high": post.monthly_high,
        "monthly_median": post.monthly_median,
        "salary_basis": post.salary_basis,
        "salary_confidence": round(post.salary_confidence, 2),
        "salary_period": post.salary_period,
        "salary_period_label": PAY_PERIOD_LABELS.get(post.salary_period, post.salary_period),
        "comparable_monthly_low": post.comparable_monthly_low,
        "comparable_monthly_high": post.comparable_monthly_high,
        "comparable_monthly_median": post.comparable_monthly_median,
        "has_variable": post.has_variable,
        "variable_scope": post.variable_scope,
        "variable_scope_label": VARIABLE_SCOPE_LABELS.get(post.variable_scope, post.variable_scope),
        "salary_package": post.salary_package or {},
        "salary_reason": (post.salary_package or {}).get("reason"),
        "published_at": iso_utc(post.published_at),
        "expire_at": iso_utc(post.expire_at),
        "raw_text": mask_text(post.raw_text, post.company_raw) if viewer else post.raw_text,
        "created_at": iso_utc(post.created_at),
    }
    if viewer:
        payload["salary_basis"] = re.sub(r"【.*?】", "", payload["salary_basis"])
    return payload


def _channel_map(db: Session) -> dict[int, Channel]:
    return {channel.id: channel for channel in db.scalars(select(Channel)).all()}


def list_posts(
    db: Session,
    *,
    role: str,
    channel_id: int | None = None,
    city: str | None = None,
    salary_status: str | None = None,
    salary_period: str | None = None,
    variable_scope: str | None = None,
    q: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    stmt = select(Post)
    count_stmt = select(func.count()).select_from(Post)
    if channel_id:
        stmt = stmt.where(Post.channel_id == channel_id)
        count_stmt = count_stmt.where(Post.channel_id == channel_id)
    if city:
        stmt = stmt.where(Post.city == city)
        count_stmt = count_stmt.where(Post.city == city)
    if salary_status:
        stmt = stmt.where(Post.salary_status == salary_status)
        count_stmt = count_stmt.where(Post.salary_status == salary_status)
    if salary_period:
        stmt = stmt.where(Post.salary_period == salary_period)
        count_stmt = count_stmt.where(Post.salary_period == salary_period)
    if variable_scope:
        stmt = stmt.where(Post.variable_scope == variable_scope)
        count_stmt = count_stmt.where(Post.variable_scope == variable_scope)
    if q:
        like = f"%{q.strip()}%"
        clause = (
            Post.title_raw.ilike(like)
            | Post.company_raw.ilike(like)
            | Post.external_id.ilike(like)
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Post.id).limit(limit).offset(offset)).all()
    channels = _channel_map(db)
    return {
        "items": [serialize(row, channels.get(row.channel_id), role) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_post(db: Session, post_id: int, role: str) -> dict:
    post = db.get(Post, post_id)
    if post is None:
        raise AppError("NOT_FOUND", 404, {"entity": "post", "id": post_id})
    return serialize(post, db.get(Channel, post.channel_id), role)


def city_options(db: Session, role: str) -> list[str]:
    return sorted({row for row in db.scalars(select(Post.city)).all() if row})


def salary_breakdown(db: Session) -> dict:
    rows = db.execute(select(Post.salary_status, func.count()).group_by(Post.salary_status)).all()
    counts = {key: int(count) for key, count in rows}
    total = db.scalar(select(func.count()).select_from(Post)) or 0
    period_rows = db.execute(select(Post.salary_period, func.count()).group_by(Post.salary_period)).all()
    variable_rows = db.execute(select(Post.variable_scope, func.count()).group_by(Post.variable_scope)).all()
    return {
        "total": total,
        "parsed": counts.get("parsed", 0),
        "negotiable": counts.get("negotiable", 0),
        "unparsed": counts.get("unparsed", 0),
        "by_period": {key: int(count) for key, count in period_rows},
        "by_variable_scope": {key: int(count) for key, count in variable_rows},
        "with_variable": sum(
            int(count) for key, count in variable_rows if key and key != "none" and key != "fixed_only"
        ),
    }
