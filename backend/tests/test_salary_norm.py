"""算法 A（薪资口径归一）单测：周期 / 浮动 / 换算过程 / 不可比 / 矛盾 / 确定性。"""
from __future__ import annotations

import pytest

from src.services.salary_norm import parse_many, parse_salary


def test_range_with_13_months():
    result = parse_salary("8-12K·13薪")
    assert result["status"] == "parsed"
    assert result["months"] == 13
    assert result["months_explicit"] is True
    assert (result["salary_low"], result["salary_high"]) == (8000, 12000)
    # 8000×12/13=7385、12000×12/13=11077、10000×12/13=9231
    assert result["monthly_low"] == 7385
    assert result["monthly_high"] == 11077
    assert result["monthly_median"] == 9231
    assert result["comparable_monthly_low"] == 7385
    assert result["comparable_monthly_median"] == 9231
    assert "13 薪" in result["norm_basis"]
    assert result["basis_steps"] and result["norm_basis"] == "；".join(result["basis_steps"])


def test_annual_salary_converted_to_monthly():
    result = parse_salary("年薪18万")
    assert result["status"] == "parsed"
    assert result["period"] == "year"
    assert result["annual_total"] == 180000
    assert result["fixed_monthly_low"] == result["fixed_monthly_high"] == 15000
    assert result["comparable_monthly_median"] == 15000
    assert result["months"] == 12


def test_daily_wage_converted_with_workdays():
    result = parse_salary("300元/天")
    assert result["status"] == "parsed"
    assert result["period"] == "day"
    assert result["quoted_low"] == result["quoted_high"] == 300
    # 300 × 21.75 = 6525
    assert result["comparable_monthly_median"] == 6525
    assert "21.75" in result["norm_basis"]


def test_daily_wage_in_sane_range_is_not_unparsed():
    assert parse_salary("100元/天")["status"] == "parsed"
    assert parse_salary("元/天")["status"] == "unparsed"


def test_base_salary_with_unquantified_commission():
    result = parse_salary("底薪8000+提成")
    assert result["status"] == "parsed"
    assert result["has_variable"] is True
    assert result["variable_scope"] == "unquantified"
    assert result["fixed_monthly_low"] == result["fixed_monthly_high"] == 8000
    # 未量化的提成不能编造金额
    assert result["variable_monthly_low"] is None
    assert result["comparable_monthly_median"] == 8000
    assert result["variable_items"][0]["quantified"] is False


def test_quantified_year_end_bonus_is_added_to_total_not_inserted_into_base():
    result = parse_salary("月薪8000-10000+年终奖2万")
    assert result["status"] == "parsed"
    assert result["variable_scope"] == "quantified"
    assert (result["fixed_monthly_low"], result["fixed_monthly_high"]) == (8000, 10000)
    # 20000 ÷ 12 = 1666.67 → 1667
    assert (result["variable_monthly_low"], result["variable_monthly_high"]) == (1667, 1667)
    assert (result["total_monthly_low"], result["total_monthly_high"]) == (9667, 11667)
    assert result["comparable_monthly_low"] == 9667
    assert "含浮动月薪" in result["norm_basis"]


def test_percent_commission_has_no_invented_amount():
    result = parse_salary("月薪8000+提成3%")
    assert result["status"] == "parsed"
    assert result["comparable_monthly_median"] == 8000
    assert result["variable_monthly_low"] is None
    assert result["variable_items"][0]["percent"] == 3.0


def test_total_with_included_variable_cannot_be_split():
    result = parse_salary("综合月薪8000-10000（含提成）")
    assert result["status"] == "parsed"
    assert result["variable_scope"] == "included_unquantified"
    assert result["fixed_monthly_low"] is None
    assert (result["total_monthly_low"], result["total_monthly_high"]) == (8000, 10000)
    assert result["comparable_monthly_low"] == 8000


def test_yuan_per_month_and_fullwidth_variants():
    assert parse_salary("4000-6000元/月")["monthly_median"] == 5000
    fullwidth = parse_salary("２万－３万/月")
    assert (fullwidth["monthly_low"], fullwidth["monthly_high"]) == (20000, 30000)
    assert parse_salary("６千-９千/月")["monthly_median"] == 7500


def test_negotiable_has_null_median_and_low_confidence():
    result = parse_salary("面议")
    assert result["status"] == "negotiable"
    assert result["monthly_median"] is None
    assert result["comparable_monthly_median"] is None
    assert result["confidence"] == pytest.approx(0.2)


def test_contradiction_is_unparsed():
    result = parse_salary("12-8K")
    assert result["status"] == "unparsed"
    assert "矛盾" in result["reason"]
    assert result["monthly_median"] is None


def test_period_conflict_is_unparsed():
    result = parse_salary("年薪18万+300元/天")
    assert result["status"] == "unparsed"
    assert "周期矛盾" in result["reason"]


def test_implausible_magnitude_is_unparsed():
    assert parse_salary("1000000元/月")["status"] == "unparsed"
    assert parse_salary("")["status"] == "unparsed"
    assert parse_salary("薪资：见合同")["status"] == "unparsed"


def test_batch_stats_and_unparsed_list():
    batch = parse_many(["8-12K·13薪", "面议", "12-8K", "年薪18万", "没有金额"])
    assert batch["stats"]["total"] == 5
    assert batch["stats"]["parsed"] == 2
    assert batch["stats"]["negotiable"] == 1
    assert batch["stats"]["unparsed"] == 2
    assert batch["stats"]["fail_rate"] == pytest.approx(0.4)
    assert [item["index"] for item in batch["unparsed"]] == [2, 4]


def test_raw_value_and_steps_are_never_lost():
    raw = "底薪8000+提成"
    result = parse_salary(raw)
    assert result["raw"] == raw
    assert any(raw in step for step in result["basis_steps"])
    assert parse_salary(raw) == result  # 确定性


def test_deterministic():
    raws = ["8-12K·13薪", "年薪18万", "面议", "15-25K·14薪", "300元/天", "底薪8000+提成"]
    assert parse_many(raws) == parse_many(raws)
