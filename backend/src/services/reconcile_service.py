"""对账服务：页面计数、复核结论、导出清单三方必须一致（查库版）。

纯计算规则在 `services/reconcile.py`（可单测、不依赖数据库）；本模块只负责
查库补数，并直接用导出服务的 CSV 行数做「导出清单」一侧的对账。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.cluster import Cluster
from src.models.post import Post
from src.models.review import Review
from src.services import cluster_service, export_service, run_service
from src.services.reconcile import evaluate


def _csv_rows(payload: bytes) -> int:
    return len(export_service.csv_data_rows(payload))


def summary(db: Session, run_id: int | None) -> dict:
    target = run_id if run_id is not None else (run_service.latest_run(db).id if run_service.latest_run(db) else None)
    posts_total = db.scalar(select(func.count()).select_from(Post)) or 0
    if target is None:
        clusters_total = 0
        salary_counts = {"comparable": 0, "inconsistent": 0, "noncomparable": 0}
        needs_review = 0
    else:
        clusters_total = db.scalar(select(func.count()).select_from(Cluster).where(Cluster.run_id == target)) or 0
        rows = db.execute(
            select(Cluster.salary_status, func.count())
            .where(Cluster.run_id == target)
            .group_by(Cluster.salary_status)
        ).all()
        salary_counts = {key: int(count) for key, count in rows}
        needs_review = db.scalar(
            select(func.count())
            .select_from(Cluster)
            .where(Cluster.run_id == target, Cluster.needs_review.is_(True))
        ) or 0
    review_total = db.scalar(
        select(func.count())
        .select_from(Review)
        .join(Cluster, Review.cluster_id == Cluster.id)
        .where(Cluster.run_id == target if target is not None else False)
    ) or 0
    reviewed_needs_review = db.scalar(
        select(func.count())
        .select_from(Review)
        .join(Cluster, Review.cluster_id == Cluster.id)
        .where(
            Cluster.run_id == target if target is not None else False,
            Cluster.needs_review.is_(True),
        )
    ) or 0
    pending_total = (
        db.scalar(
            select(func.count())
            .select_from(Cluster)
            .where(
                Cluster.run_id == target,
                Cluster.needs_review.is_(True),
                Cluster.id.not_in(select(Review.cluster_id)),
            )
        ) or 0
        if target is not None
        else 0
    )
    clusters_payload = export_service.clusters_csv(db, target)
    result = evaluate(
        posts_total=int(posts_total),
        clusters_total=int(clusters_total),
        clusters_csv_rows=_csv_rows(clusters_payload),
        salary_counts=salary_counts,
        needs_review=int(needs_review),
        review_total=int(review_total),
        pending_total=int(pending_total),
        reviews_csv_rows=_csv_rows(export_service.reviews_csv(db)),
        posts_csv_rows=_csv_rows(export_service.posts_csv(db)),
        reviewed_needs_review=int(reviewed_needs_review),
    )
    # 来源明细：每条来源一行，必须能覆盖本运行所有簇的全部成员，且被采用来源恰好一条/可比簇
    source_rows = export_service.csv_data_rows(export_service.cluster_sources_csv(db, target))
    adopted_rows = sum(1 for row in source_rows if row[-2] == "是")
    cluster_rows = export_service.csv_data_rows(clusters_payload)
    header = export_service.csv_headers(clusters_payload)
    # 列表页与导出清单的「可否对外发布」必须一致
    publish_counts = cluster_service.publish_counts(db, target)
    if cluster_rows:
        index = header.index("可否对外发布") if "可否对外发布" in header else None
        exported_publishable = (
            sum(1 for row in cluster_rows if index is not None and row[index] == "是") if index is not None else 0
        )
        result["checks"].append(
            {
                "key": "publishable_rows_match",
                "label": "导出清单可发布行数 = 页面可发布计数",
                "left": exported_publishable,
                "right": publish_counts["publishable"],
                "ok": exported_publishable == publish_counts["publishable"],
            }
        )
        result["exports"]["publishable_rows"] = exported_publishable
    result["counts"]["publishable"] = publish_counts["publishable"]
    member_ids = {
        int(member_id)
        for cluster in (
            db.scalars(select(Cluster).where(Cluster.run_id == target)).all() if target is not None else []
        )
        for member_id in (cluster.member_ids or [])
    }
    exported_ids = {int(row[7]) for row in source_rows if row[7]}
    adopted_ok = adopted_rows == int(salary_counts.get("comparable", 0))
    coverage_ok = exported_ids == member_ids
    result["checks"].extend(
        [
            {
                "key": "source_rows_cover_members",
                "label": "来源明细覆盖全部成员岗位",
                "left": len(exported_ids),
                "right": len(member_ids),
                "ok": coverage_ok,
            },
            {
                "key": "adopted_one_per_comparable_cluster",
                "label": "可比簇恰好各采用一条来源",
                "left": adopted_rows,
                "right": int(salary_counts.get("comparable", 0)),
                "ok": adopted_ok,
            },
        ]
    )
    result["balanced"] = all(item["ok"] for item in result["checks"])
    result["exports"]["cluster_sources_rows"] = len(source_rows)
    result["run_id"] = target
    return result
