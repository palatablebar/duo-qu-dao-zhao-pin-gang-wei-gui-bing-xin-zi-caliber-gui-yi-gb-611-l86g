# 数据库迁移说明

本项目用 SQLAlchemy `Base.metadata.create_all()` 在 backend 启动时建表（见 `src/config/app.py`），
因此首次 `docker compose up` 会自动建好表，不需要额外执行迁移。

- `001_core_tables.sql`：核心表的人类可读 DDL 参考（PostgreSQL 语法），用于 reviewer 对照字段；
  运行时不执行它。
- 后续如果要做字段变更，建议引入 Alembic，并在本目录按 `00x_<描述>.py` 递增。
- seed 数据只走 `backend/scripts/seed_demo.py`，不要写进 SQL。
- **已有库升级（薪资包字段）**：启动时 `src/utils/schema_guard.py` 会对已存在的 `posts` / `clusters`
  做「缺列补列」（清单见 `COLUMNS`），只增不删；随后 seed/main 会在读取时沿用旧的
  `salary_raw`、`salary_basis` 等字段，不会清空原始薪资。若要让老簇补出
  `salary_sources` / 薪资包结论，重新发起一次归并运行（或重启 backend 触发 seed 重算）即可。
