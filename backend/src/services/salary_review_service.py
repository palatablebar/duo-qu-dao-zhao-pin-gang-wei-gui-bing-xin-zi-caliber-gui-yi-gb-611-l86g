"""薪资包人工复核：在「不一致」的簇里选定一条来源作为对外口径。

规则：
- 只能对 `salary_status=inconsistent` 的簇做薪资包复核；
- 被选来源必须是该簇成员，且该来源自身 `parsed` 且可比；
- 选定后：簇的对外薪资字段（salary_low/high/monthly_median/basis/adopted）全部取自该来源，
  salary_status 变为 `comparable`，来源清单与差异保留不丢；
- 不可比 / 来源不属于该簇 / 来源自身不可比 → 422；
- 全部来源不可比的簇允许人工直接给结论（keep/split/merge），但薪资包仍保持 noncomparable。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import SalaryStatus
from src.models.channel import Channel
from src.models.cluster import Cluster
from src.models.post import Post
from src.services import salary_package
from src.utils.errors import AppError, not_found


def _member_payload(post: Post, channel: Channel | None) -> dict:
    return {
        "id": post.id,
        "external_id": post.external_id,
        "channel_code": channel.code if channel else "",
        "channel_name": channel.name if channel else "",
        "company_raw": post.company_raw,
        "title_raw": post.title_raw,
        "city": post.city,
        "salary_raw": post.salary_raw,
        "salary_status": post.salary_status,
        "salary_period": post.salary_period,
        "months": post.months,
        "monthly_low": post.monthly_low,
        "monthly_high": post.monthly_high,
        "monthly_median": post.monthly_median,
        "comparable_monthly_low": post.comparable_monthly_low,
        "comparable_monthly_high": post.comparable_monthly_high,
        "comparable_monthly_median": post.comparable_monthly_median,
        "salary_package": post.salary_package or {},
        "has_variable": post.has_variable,
        "variable_scope": post.variable_scope,
        "published_at": post.published_at,
    }


def sources_of(db: Session, cluster: Cluster) -> dict:
    ids = [int(item) for item in (cluster.member_ids or [])]
    posts = db.scalars(select(Post).where(Post.id.in_(ids)).order_by(Post.id)).all() if ids else []
    channels = {channel.id: channel for channel in db.scalars(select(Channel)).all()}
    return salary_package.select_package(
        [_member_payload(post, channels.get(post.channel_id)) for post in posts]
    )


def adopt_source(db: Session, cluster_id: int, post_id: int, reviewer: str) -> dict:
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise not_found("cluster", cluster_id)
    if cluster.salary_status == SalaryStatus.NONCOMPARABLE.value:
        raise AppError(
            "SALARY_NOT_ADOPTABLE",
            422,
            {"reason": "全部来源不可比，没有可采用的薪资包", "cluster_id": cluster_id},
        )
    post = db.get(Post, post_id)
    if post is None or post_id not in [int(item) for item in (cluster.member_ids or [])]:
        raise AppError(
            "SALARY_SOURCE_UNKNOWN",
            422,
            {"reason": "所选来源不属于该归并簇", "cluster_id": cluster_id, "post_id": post_id},
        )

    selection = sources_of(db, cluster)
    source = next((row for row in selection["sources"] if row["post_id"] == post_id), None)
    if source is None or not source["is_comparable"]:
        raise AppError(
            "SALARY_SOURCE_NOT_COMPARABLE",
            422,
            {"reason": "所选来源自身薪资不可比", "cluster_id": cluster_id, "post_id": post_id},
        )

    cluster.salary_low = source["comparable_monthly_low"]
    cluster.salary_high = source["comparable_monthly_high"]
    cluster.monthly_median = source["comparable_monthly_median"]
    cluster.salary_basis = source["norm_basis"]
    cluster.salary_adopted_post_id = post_id
    cluster.salary_adopted = {key: value for key, value in source.items() if key != "basis_steps"}
    cluster.salary_adopted["basis_steps"] = list(source["basis_steps"])
    cluster.salary_status = SalaryStatus.COMPARABLE.value
    cluster.needs_review = False
    cluster.review_reason = ""
    cluster.has_variable = source["has_variable"]
    cluster.variable_scope = source["variable_scope"]

    for row in selection["sources"]:
        row["adopted"] = row["post_id"] == post_id
    cluster.salary_sources = selection["sources"]
    differences = [item for item in selection["differences"] if item["field"] != "equivalent_writings"]
    differences.append(
        {
            "field": "manual_adoption",
            "label": "人工选定来源",
            "detail": f"{reviewer} 选定岗位 #{post_id}「{post.salary_raw}」作为对外口径",
        }
    )
    cluster.salary_differences = differences
    return {
        "cluster_id": cluster.id,
        "run_id": cluster.run_id,
        "salary_status": cluster.salary_status,
        "adopted_post_id": cluster.salary_adopted_post_id,
        "salary_low": cluster.salary_low,
        "salary_high": cluster.salary_high,
        "monthly_median": cluster.monthly_median,
        "basis_steps": cluster.salary_adopted.get("basis_steps", []),
        "sources": cluster.salary_sources,
        "differences": cluster.salary_differences,
    }
