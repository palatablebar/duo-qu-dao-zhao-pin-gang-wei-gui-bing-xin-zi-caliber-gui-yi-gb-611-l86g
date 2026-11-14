from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import REVIEW_ROLES
from src.controllers import cluster_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.schemas.cluster import SalaryAdoptIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("")
def list_clusters(
    run_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    multi: bool = False,
    needs_review: bool | None = None,
    salary_status: str | None = None,
    limit: int = Query(30),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return cluster_controller.list_clusters(
        db,
        role=principal["role"],
        run_id=run_id,
        status=status,
        q=q,
        multi_only=multi,
        needs_review=needs_review,
        salary_status=salary_status,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/reconcile")
def reconcile(
    run_id: int | None = None,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return cluster_controller.reconcile(db, run_id)


@router.get("/{cluster_id}")
def get_cluster(
    cluster_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))
) -> dict:
    return cluster_controller.get_cluster(db, cluster_id, principal["role"])


@router.post("/{cluster_id}/salary")
def adopt_salary(
    cluster_id: int,
    payload: SalaryAdoptIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*REVIEW_ROLES)),
) -> dict:
    return cluster_controller.adopt_salary(db, cluster_id, payload.model_dump(), principal, request)
