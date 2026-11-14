"""对账单测：页面计数、复核结论、导出清单必须一致（纯函数）。"""
from __future__ import annotations

from src.services.reconcile import evaluate


def _balanced(**overrides):
    base = dict(
        posts_total=160,
        clusters_total=118,
        clusters_csv_rows=118,
        salary_counts={"comparable": 89, "inconsistent": 10, "noncomparable": 19},
        needs_review=12,
        review_total=3,
        pending_total=9,
        reviews_csv_rows=3,
        posts_csv_rows=160,
        reviewed_needs_review=3,
    )
    base.update(overrides)
    return evaluate(**base)


def test_balanced_when_counts_match():
    result = _balanced()
    assert result["balanced"] is True
    assert all(item["ok"] for item in result["checks"])
    assert result["counts"]["clusters_total"] == 118
    assert result["counts"]["salary_comparable"] == 89


def test_salary_status_sum_must_equal_cluster_total():
    result = _balanced(salary_counts={"comparable": 89, "inconsistent": 10, "noncomparable": 18})
    assert result["balanced"] is False
    check = next(item for item in result["checks"] if item["key"] == "salary_status_sum")
    assert check["ok"] is False
    assert check["left"] == 117 and check["right"] == 118


def test_export_rows_must_match_cluster_total():
    result = _balanced(clusters_csv_rows=117)
    assert result["balanced"] is False
    check = next(item for item in result["checks"] if item["key"] == "clusters_csv_rows")
    assert check["ok"] is False


def test_pending_plus_reviewed_must_equal_needs_review():
    result = _balanced(pending_total=8)
    assert result["balanced"] is False
    check = next(item for item in result["checks"] if item["key"] == "pending_plus_reviewed")
    assert check["ok"] is False


def test_review_export_rows_must_match_review_total():
    result = _balanced(reviews_csv_rows=2)
    assert result["balanced"] is False
    check = next(item for item in result["checks"] if item["key"] == "reviews_csv_rows")
    assert check["ok"] is False
