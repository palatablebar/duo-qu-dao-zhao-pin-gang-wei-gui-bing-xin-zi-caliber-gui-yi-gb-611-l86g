"""归并簇控制器。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, cluster_service, reconcile_service, salary_review_service


def list_clusters(db: Session, **filters) -> dict:
    return cluster_service.list_clusters(db, **filters)


def get_cluster(db: Session, cluster_id: int, role: str) -> dict:
    return cluster_service.get_cluster(db, cluster_id, role)


def adopt_salary(
    db: Session, cluster_id: int, payload: dict, principal: dict, request: Request
) -> dict:
    result = salary_review_service.adopt_source(db, cluster_id, int(payload["post_id"]), principal["email"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="salary.adopt",
        entity="cluster",
        entity_id=cluster_id,
        detail={
            "post_id": payload["post_id"],
            "low": result["salary_low"],
            "high": result["salary_high"],
            "note": payload.get("note"),
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return result


def reconcile(db: Session, run_id: int | None) -> dict:
    return reconcile_service.summary(db, run_id)
