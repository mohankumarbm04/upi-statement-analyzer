import pandas as pd
import pytest

from app import insights


def make_df(rows):
    """rows: (date, merchant, category, amount, type)"""
    df = pd.DataFrame(rows, columns=["date", "merchant", "category", "amount", "type"])
    df["date"] = pd.to_datetime(df["date"])
    df["description"] = df["merchant"]
    df["balance"] = float("nan")
    return df


BASIC = make_df(
    [
        ("2026-01-01", "Acme", "Income", 1000, "credit"),
        ("2026-01-02", "Swiggy", "Food & Dining", 200, "debit"),
        ("2026-01-10", "Uber", "Transport", 300, "debit"),
    ]
)


def test_summary_numbers():
    s = insights.summary(BASIC)

    assert s["transactions"] == 3
    assert s["total_spent"] == 500
    assert s["total_income"] == 1000
    assert s["net"] == 500
    assert s["savings_rate_pct"] == 50.0
    assert s["avg_daily_spend"] == 50.0  # 500 over 10 days
    assert s["largest_expense"]["merchant"] == "Uber"
    assert (s["start_date"], s["end_date"]) == ("2026-01-01", "2026-01-10")


def test_summary_without_income_has_no_savings_rate():
    df = make_df([("2026-01-01", "Uber", "Transport", 300, "debit")])

    assert insights.summary(df)["savings_rate_pct"] is None


def test_summary_of_empty_frame_is_zeroed():
    s = insights.summary(make_df([]))

    assert s["transactions"] == 0
    assert s["total_spent"] == 0.0
    assert s["largest_expense"] is None


def test_monthly_groups_and_orders():
    df = make_df(
        [
            ("2026-02-03", "Uber", "Transport", 100, "debit"),
            ("2026-01-05", "Acme", "Income", 900, "credit"),
            ("2026-01-09", "Uber", "Transport", 400, "debit"),
        ]
    )
    result = insights.monthly(df)

    assert [r["month"] for r in result] == ["2026-01", "2026-02"]
    assert result[0] == {"month": "2026-01", "spent": 400.0, "income": 900.0, "net": 500.0}
    assert result[1]["income"] == 0.0


def test_by_category_sorted_with_shares():
    result = insights.by_category(BASIC)

    assert [r["category"] for r in result] == ["Transport", "Food & Dining"]
    assert sum(r["share_pct"] for r in result) == pytest.approx(100.0, abs=0.2)
    assert result[0]["share_pct"] == 60.0


def test_top_merchants_respects_limit():
    assert [r["merchant"] for r in insights.top_merchants(BASIC, n=1)] == ["Uber"]


# --- anomalies ---------------------------------------------------------------
def shopping(amounts, start="2026-03-01"):
    days = pd.date_range(start, periods=len(amounts)).strftime("%Y-%m-%d")
    return [(d, "Amazon", "Shopping", a, "debit") for d, a in zip(days, amounts, strict=True)]


def test_flags_statistical_outlier_only():
    df = make_df(shopping([1000, 1100, 900, 1050, 950, 30000]))
    flagged = insights.detect_anomalies(df)

    assert list(flagged["amount"]) == [30000]
    assert "Unusually high for Shopping" in flagged.iloc[0]["reason"]


def test_small_groups_are_not_judged():
    df = make_df(shopping([1000, 1100, 30000]))

    assert insights.detect_anomalies(df).empty


def test_small_amounts_are_not_flagged_even_if_relatively_large():
    amounts = [100, 110, 105, 95, 100, 400]
    df = make_df(
        [(f"2026-03-0{i}", "Cafe", "Food & Dining", a, "debit") for i, a in enumerate(amounts, 1)]
    )

    assert insights.detect_anomalies(df).empty


def test_flags_duplicate_charge_same_day():
    df = make_df(
        [
            ("2026-03-01", "Swiggy", "Food & Dining", 749, "debit"),
            ("2026-03-01", "Swiggy", "Food & Dining", 749, "debit"),
            ("2026-03-02", "Swiggy", "Food & Dining", 749, "debit"),  # different day: fine
        ]
    )
    flagged = insights.detect_anomalies(df)

    assert len(flagged) == 1
    assert "duplicate" in flagged.iloc[0]["reason"].lower()


def test_cheap_repeat_purchases_are_not_duplicates():
    df = make_df([("2026-03-01", "Metro", "Transport", 40, "debit")] * 2)

    assert insights.detect_anomalies(df).empty


def test_no_anomalies_still_has_reason_column():
    assert "reason" in insights.detect_anomalies(BASIC).columns


# --- recurring ---------------------------------------------------------------
def test_detects_monthly_subscription():
    df = make_df(
        [(f"2026-0{m}-14", "Netflix", "Entertainment", 649, "debit") for m in range(1, 5)]
    )
    result = insights.recurring(df)

    assert result == [
        {
            "merchant": "Netflix",
            "category": "Entertainment",
            "typical_amount": 649.0,
            "months_seen": 4,
            "last_paid": "2026-04-14",
        }
    ]


def test_ignores_variable_spend_short_history_and_frequent_merchants():
    variable = [
        ("2026-01-05", "Swiggy", "Food & Dining", 200, "debit"),
        ("2026-02-05", "Swiggy", "Food & Dining", 450, "debit"),
        ("2026-03-05", "Swiggy", "Food & Dining", 380, "debit"),
        ("2026-04-05", "Swiggy", "Food & Dining", 120, "debit"),
    ]
    short = [(f"2026-0{m}-03", "Gym", "Health", 1500, "debit") for m in (1, 2)]
    frequent = [
        (f"2026-0{m}-{d:02d}", "Chai", "Food & Dining", 50, "debit")
        for m in range(1, 5)
        for d in (1, 8, 15, 22)
    ]

    assert insights.recurring(make_df(variable + short + frequent)) == []
