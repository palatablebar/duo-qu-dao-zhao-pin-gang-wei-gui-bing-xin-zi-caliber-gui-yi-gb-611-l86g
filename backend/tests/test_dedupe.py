"""算法 B（重复岗归并）单测：分块 / 相似度 / 阈值边界 / golden record / 确定性。"""
from __future__ import annotations

from datetime import datetime

from src.services import dedupe
from src.services.normalize_service import enrich_post_fields, normalize_company


def make_post(
    post_id: int,
    *,
    company: str,
    title: str,
    city: str = "北京",
    salary: str = "10-15K",
    degree: str = "本科",
    experience: str = "3-5年",
    channel: str = "zhaopin",
    published_at: datetime | None = None,
    expire_at: datetime | None = None,
    raw_text: str = "岗位描述",
) -> dict:
    derived = enrich_post_fields(
        company_raw=company,
        title_raw=title,
        city=city,
        salary_raw=salary,
        degree=degree,
        experience=experience,
    )
    post = {
        "id": post_id,
        "channel_code": channel,
        "channel_id": post_id,
        "company_raw": company,
        "title_raw": title,
        "city": city,
        "salary_raw": salary,
        "degree": degree,
        "experience": experience,
        "published_at": published_at or datetime(2026, 11, 1),
        "expire_at": expire_at,
        "raw_text": raw_text,
    }
    post.update(derived)
    post["salary_package"] = derived["salary_package"]
    post["salary_period"] = derived["salary_period"]
    post["comparable_monthly_low"] = derived["comparable_monthly_low"]
    post["comparable_monthly_high"] = derived["comparable_monthly_high"]
    post["comparable_monthly_median"] = derived["comparable_monthly_median"]
    post["has_variable"] = derived["has_variable"]
    post["variable_scope"] = derived["variable_scope"]
    return post


def test_company_spelling_variants_merge_into_one_cluster():
    posts = [
        make_post(1, company="云雀数智科技（北京）有限公司", title="Java开发工程师", channel="zhaopin"),
        make_post(2, company="云雀数智科技有限公司", title="Java 开发工程师（急聘）", channel="boss"),
        make_post(3, company="云雀数智科技", title="Java开发工程师-双休", channel="lagou"),
    ]
    assert normalize_company(posts[0]["company_raw"]) == normalize_company(posts[2]["company_raw"])
    result = dedupe.build_clusters(posts)
    assert result["metrics"]["clusters"] == 1
    cluster = result["clusters"][0]
    assert cluster["member_count"] == 3
    assert cluster["dup_removed"] == 2
    assert cluster["channel_count"] == 3


def test_blocking_key_separates_cities():
    posts = [
        make_post(1, company="远山网络科技有限公司", title="前端开发工程师", city="北京"),
        make_post(2, company="远山网络科技有限公司", title="前端开发工程师", city="上海"),
    ]
    result = dedupe.build_clusters(posts)
    assert result["metrics"]["clusters"] == 2
    assert result["metrics"]["pairs"] == 0  # 不同分块不比较


def test_threshold_boundary_changes_cluster_count():
    posts = [
        make_post(1, company="泓源信息技术有限公司", title="测试工程师", salary="10-10.5K", degree="本科", experience="3-5年"),
        make_post(2, company="泓源信息技术有限公司", title="测试工程师", salary="14-14.9K", degree="大专", experience="1-3年"),
    ]
    score = dedupe.similarity(posts[0], posts[1])["score"]
    assert 0.6 < score < 0.82  # 相同职位但薪资不重叠、属性不符
    assert dedupe.build_clusters(posts, threshold=0.82)["metrics"]["clusters"] == 2
    assert dedupe.build_clusters(posts, threshold=0.65)["metrics"]["clusters"] == 1


def test_golden_record_prefers_complete_then_newer():
    complete_old = make_post(
        1,
        company="知舟软件服务有限公司",
        title="产品经理",
        published_at=datetime(2026, 10, 1),
        expire_at=datetime(2026, 12, 1),
        raw_text="完整字段",
    )
    sparse_new = make_post(
        2,
        company="知舟软件服务有限公司",
        title="产品经理",
        published_at=datetime(2026, 11, 10),
        raw_text="",
    )
    sparse_new["degree"] = "any"
    sparse_new["experience"] = "any"
    result = dedupe.build_clusters([complete_old, sparse_new])
    cluster = result["clusters"][0]
    assert cluster["member_count"] == 2
    assert cluster["golden_post_id"] == 1

    newer = dict(sparse_new)
    newer["id"] = 3
    newer["published_at"] = datetime(2026, 11, 12)
    both_sparse = dedupe.pick_golden([sparse_new, newer])
    assert both_sparse["id"] == 3


def test_expired_cluster_detected():
    posts = [
        make_post(1, company="嘉禾数字营销有限公司", title="数据分析师", expire_at=datetime(2026, 10, 1)),
    ]
    result = dedupe.build_clusters(posts, now=datetime(2026, 11, 14))
    assert result["clusters"][0]["status"] == "expired"


def test_deterministic():
    posts = [
        make_post(1, company="元朔智能科技有限公司", title="运维工程师", channel="zhaopin"),
        make_post(2, company="元朔智能科技", title="运维工程师", channel="boss"),
        make_post(3, company="鹿鸣智能科技有限公司", title="算法工程师", channel="lagou"),
    ]
    assert dedupe.build_clusters(posts) == dedupe.build_clusters(posts)


def test_cluster_salary_package_is_single_source():
    posts = [
        make_post(1, company="云雀数智科技有限公司", title="Java开发工程师", salary="10-15K", channel="zhaopin"),
        make_post(2, company="云雀数智科技有限公司", title="Java 开发工程师（急聘）", salary="月薪10000-15000元", channel="boss"),
        make_post(3, company="云雀数智科技有限公司", title="Java开发工程师-双休", salary="10-15K", channel="lagou"),
    ]
    result = dedupe.build_clusters(posts)
    cluster = result["clusters"][0]
    assert cluster["salary_status"] == "comparable"
    assert (cluster["salary_low"], cluster["salary_high"]) == (10000, 15000)
    assert cluster["monthly_median"] == 12500
    assert cluster["salary_adopted_post_id"] in {1, 2, 3}
    expected = next(post for post in posts if post["id"] == cluster["salary_adopted_post_id"])
    assert cluster["salary_low"] == expected["comparable_monthly_low"]
    assert cluster["salary_high"] == expected["comparable_monthly_high"]
    assert cluster["salary_basis"] == expected["salary_basis"]


def test_cluster_does_not_stitch_different_packages():
    posts = [
        make_post(1, company="白石数字营销有限公司", title="Java开发工程师", salary="10-15K", channel="zhaopin"),
        make_post(2, company="白石数字营销有限公司", title="Java开发工程师", salary="10-15K", channel="boss"),
        make_post(3, company="白石数字营销有限公司", title="Java开发工程师", salary="10-15K·13薪", channel="lagou"),
    ]
    result = dedupe.build_clusters(posts)
    cluster = result["clusters"][0]
    assert cluster["salary_status"] == "inconsistent"
    assert cluster["salary_low"] is None and cluster["salary_high"] is None
    assert cluster["monthly_median"] is None
    assert cluster["needs_review"] is True
    assert "薪资包不一致" in cluster["review_reason"]
    assert len(cluster["salary_sources"]) == 3


def test_cluster_all_noncomparable_is_flagged_not_sorted():
    posts = [
        make_post(1, company="长风供应链有限公司", title="运营专员", salary="面议", channel="zhaopin"),
        make_post(2, company="长风供应链有限公司", title="运营专员", salary="面议", channel="boss"),
    ]
    result = dedupe.build_clusters(posts)
    cluster = result["clusters"][0]
    assert cluster["salary_status"] == "noncomparable"
    assert cluster["salary_low"] is None
    assert cluster["monthly_median"] is None


def test_metrics_salary_status_counts_add_up():
    posts = [
        make_post(1, company="云雀数智科技有限公司", title="Java开发工程师", salary="10-15K"),
        make_post(2, company="白石数字营销有限公司", title="Java开发工程师", salary="10-15K"),
        make_post(3, company="白石数字营销有限公司", title="Java开发工程师", salary="10-15K·13薪"),
        make_post(4, company="长风供应链有限公司", title="运营专员", salary="面议"),
    ]
    metrics = dedupe.build_clusters(posts)["metrics"]
    assert (
        metrics["salary_comparable"] + metrics["salary_inconsistent"] + metrics["salary_noncomparable"]
        == metrics["clusters"]
    )
