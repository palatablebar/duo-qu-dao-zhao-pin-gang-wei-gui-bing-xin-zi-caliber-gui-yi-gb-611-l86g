"""轻量 schema 守护：给已存在的库补上新增列，避免升级后丢数据或 500。

项目仍用 `create_all` 建表（见 config/app.py）；`create_all` 不会改已存在的表，
所以新增薪资包字段时由本模块补 `ALTER TABLE ADD COLUMN`。只做「缺列补列」，
不删列、不改类型，字段定义与 `migrations/001_core_tables.sql` 保持一致。
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from src.config.database import engine

logger = logging.getLogger("app.schema")

# (表, 列, ADD COLUMN 片段)；片段同时兼容 PostgreSQL 与 MySQL 的 ADD COLUMN 语法
COLUMNS: list[tuple[str, str, str]] = [
    ("posts", "salary_package", "JSON"),
    ("posts", "salary_period", "VARCHAR(12) NOT NULL DEFAULT 'unknown'"),
    ("posts", "comparable_monthly_low", "INTEGER"),
    ("posts", "comparable_monthly_high", "INTEGER"),
    ("posts", "comparable_monthly_median", "INTEGER"),
    ("posts", "has_variable", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("posts", "variable_scope", "VARCHAR(24) NOT NULL DEFAULT 'none'"),
    ("clusters", "salary_status", "VARCHAR(24) NOT NULL DEFAULT 'noncomparable'"),
    ("clusters", "salary_adopted_post_id", "INTEGER"),
    ("clusters", "salary_source_count", "INTEGER NOT NULL DEFAULT 0"),
    ("clusters", "salary_comparable_sources", "INTEGER NOT NULL DEFAULT 0"),
    ("clusters", "salary_noncomparable_sources", "INTEGER NOT NULL DEFAULT 0"),
    ("clusters", "has_variable", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("clusters", "variable_scope", "VARCHAR(24) NOT NULL DEFAULT 'none'"),
    ("clusters", "salary_sources", "JSON"),
    ("clusters", "salary_differences", "JSON"),
    ("clusters", "salary_adopted", "JSON"),
]


def ensure_columns() -> list[str]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in COLUMNS:
            if table not in tables:
                continue
            existing = {item["name"] for item in inspector.get_columns(table)}
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
            logger.info("[schema] added column %s.%s", table, column)
    return added
