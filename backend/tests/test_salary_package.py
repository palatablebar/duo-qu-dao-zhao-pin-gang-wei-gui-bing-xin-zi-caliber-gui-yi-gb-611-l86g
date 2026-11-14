"""归并薪资包单测：只采用一条完整来源 / 不一致进复核 / 全部不可比明确标出 / 不拼区间。"""
from __future__ import annotations

from src.services import salary_package
from src.services.normalize_service import enrich_post_fields


def make_post(post_id: int, raw: str, channel: str = "zhaopin", company: str = "云雀数智科技有限公司",
              title: str = "Java开发工程师", city: str = "北京", published_at=None, raw_text: str = "岗位描述") -> dict:
    derived = enrich_post_fields(
        company_raw=company, title_raw=title, city=city, salary_raw=raw, degree="本科", experience="3-5年"
    )
    post = {
        "id": post_id,
        "channel_code": channel,
        "company_raw": company,
        "title_raw": title,
        "city": city,
        "salary_raw": raw,
        "published_at": published_at,
        "raw_text": raw_text,
        "external_id": f"ext-{post_id}",
    }
    post.update(derived)
    return post


def test_equivalent_writings_adopt_single_source():
    result = salary_package.select_package(
        [
            make_post(1, "10-15K", "zhaopin"),
            make_post(2, "月薪10000-15000元", "boss"),
            make_post(3, "10000-15000元/月", "lagou"),
        ]
    )
    assert result["status"] == "comparable"
    assert result["adopted"] is not None
    assert (result["low"], result["high"]) == (10000, 15000)
    adopted_ids = [row["post_id"] for row in result["sources"] if row["adopted"]]
    assert adopted_ids == [result["adopted"]["post_id"]]
    assert len(result["sources"]) == 3


def test_different_months_are_inconsistent_and_not_merged():
    result = salary_package.select_package(
        [
            make_post(1, "10-15K"),
            make_post(2, "10-15K"),
            make_post(3, "10-15K·13薪"),
        ]
    )
    assert result["status"] == "inconsistent"
    assert result["adopted"] is None
    assert result["low"] is None and result["high"] is None
    fields = {item["field"] for item in result["differences"]}
    assert "months" in fields
    assert "package_groups" in fields
    assert "薪资包不一致" in result["reason"]


def test_commission_source_vs_plain_source_is_inconsistent():
    result = salary_package.select_package(
        [make_post(1, "8000-12000元/月+提成", "a"), make_post(2, "10-12K", "b")]
    )
    assert result["status"] == "inconsistent"
    assert result["adopted"] is None
    assert any(item["field"] == "variable_scope" for item in result["differences"])


def test_all_noncomparable_is_flagged():
    result = salary_package.select_package([make_post(1, "面议", "a"), make_post(2, "12-8K", "b")])
    assert result["status"] == "noncomparable"
    assert result["adopted"] is None
    assert result["low"] is None
    assert "全部来源薪资不可比" in result["reason"]


def test_single_source_adopted_with_steps_preserved():
    result = salary_package.select_package([make_post(1, "8-12K·13薪", "a")])
    assert result["status"] == "comparable"
    adopted = result["adopted"]
    assert adopted["post_id"] == 1
    assert adopted["salary_raw"] == "8-12K·13薪"
    assert (adopted["comparable_monthly_low"], adopted["comparable_monthly_high"]) == (7385, 11077)
    assert adopted["basis_steps"]
    assert adopted["months"] == 13


def test_inconsistent_keeps_every_original_value():
    result = salary_package.select_package(
        [make_post(1, "10-15K"), make_post(2, "10-15K·13薪")]
    )
    assert {row["salary_raw"] for row in result["sources"]} == {"10-15K", "10-15K·13薪"}
    assert all(row["basis_steps"] for row in result["sources"])
    assert all(row["norm_basis"] for row in result["sources"])


def test_adoption_prefers_explicit_months_and_range():
    result = salary_package.select_package(
        [
            make_post(1, "15000", "a"),  # 单点、未写月数
            make_post(2, "10000-15000元/月", "b"),  # 区间、显式 /月
        ]
    )
    # "15000" 单点折成 15000-15000，与 10000-15000 签名不同 → 不一致，不能拼成 10000-15000
    assert result["status"] == "inconsistent"


def test_deterministic():
    members = [make_post(1, "10-15K"), make_post(2, "10-15K·13薪")]
    assert salary_package.select_package(members) == salary_package.select_package(members)
