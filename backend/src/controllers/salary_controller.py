"""薪资口径试算控制器（算法 A 的可交互入口，结果不由前端计算）。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, post_service, salary_norm


def normalize(payload: dict, principal: dict, request: Request, db: Session) -> dict:
    result = salary_norm.parse_salary(payload["raw"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="salary.normalize",
        entity="post",
        entity_id=None,
        detail={"raw": payload["raw"][:40], "status": result["status"]},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return result


SAMPLE_RAWS = [
    "8-12K·13薪",
    "年薪18万",
    "4000-6000元/月",
    "300元/天",
    "底薪8000+提成",
    "月薪8000-10000+年终奖2万",
    "面议",
    "12-8K",
]


def samples() -> dict:
    return {"items": [salary_norm.parse_salary(raw) for raw in SAMPLE_RAWS]}


def salary_breakdown(db: Session) -> dict:
    return post_service.salary_breakdown(db)
