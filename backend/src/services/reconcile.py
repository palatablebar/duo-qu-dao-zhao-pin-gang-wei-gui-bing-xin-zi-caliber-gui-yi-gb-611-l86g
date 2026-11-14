"""计数对账（纯函数）：页面计数、复核结论、导出清单三方必须一致。

对账口径（同一次归并运行）：
- salary_comparable + salary_inconsistent + salary_noncomparable = clusters_total；
- clusters.csv 数据行数 = clusters_total；
- posts.csv 数据行数 = posts_total；
- pending_total + review_total = needs_review 簇数；
- reviews.csv 数据行数 = review_total。
"""
from __future__ import annotations


def evaluate(*, posts_total: int, clusters_total: int, clusters_csv_rows: int,
             salary_counts: dict[str, int], needs_review: int, review_total: int,
             pending_total: int, reviews_csv_rows: int, posts_csv_rows: int,
             reviewed_needs_review: int | None = None) -> dict:
    if reviewed_needs_review is None:
        reviewed_needs_review = review_total
    salary_sum = sum(int(salary_counts.get(key, 0)) for key in ("comparable", "inconsistent", "noncomparable"))
    checks = [
        {
            "key": "salary_status_sum",
            "label": "薪资包三档之和 = 归并簇数",
            "left": salary_sum,
            "right": clusters_total,
            "ok": salary_sum == clusters_total,
        },
        {
            "key": "clusters_csv_rows",
            "label": "归并清单导出行数 = 归并簇数",
            "left": clusters_csv_rows,
            "right": clusters_total,
            "ok": clusters_csv_rows == clusters_total,
        },
        {
            "key": "posts_csv_rows",
            "label": "岗位口径导出行数 = 原始岗位数",
            "left": posts_csv_rows,
            "right": posts_total,
            "ok": posts_csv_rows == posts_total,
        },
        {
            "key": "pending_plus_reviewed",
            "label": "待复核 + 已复核 = 待复核标记簇数",
            "left": pending_total + reviewed_needs_review,
            "right": needs_review,
            "ok": pending_total + reviewed_needs_review == needs_review,
        },
        {
            "key": "reviews_csv_rows",
            "label": "复核记录导出行数 = 复核结论条数",
            "left": reviews_csv_rows,
            "right": review_total,
            "ok": reviews_csv_rows == review_total,
        },
    ]
    return {
        "balanced": all(item["ok"] for item in checks),
        "checks": checks,
        "counts": {
            "posts_total": posts_total,
            "clusters_total": clusters_total,
            "salary_comparable": int(salary_counts.get("comparable", 0)),
            "salary_inconsistent": int(salary_counts.get("inconsistent", 0)),
            "salary_noncomparable": int(salary_counts.get("noncomparable", 0)),
            "needs_review": needs_review,
            "review_total": review_total,
            "reviewed_needs_review": reviewed_needs_review,
            "pending_total": pending_total,
        },
        "exports": {
            "clusters_csv_rows": clusters_csv_rows,
            "posts_csv_rows": posts_csv_rows,
            "reviews_csv_rows": reviews_csv_rows,
        },
    }
