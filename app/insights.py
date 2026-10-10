"""Spending insights computed from a categorised transactions DataFrame.

All functions expect the columns produced by ``parser.parse_statement`` and
``categorizer.categorize_dataframe``: date, description, merchant, category,
amount, type.
"""

from __future__ import annotations

import pandas as pd


def _debits(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["type"] == "debit"]


def summary(df: pd.DataFrame) -> dict:
    """Headline numbers for the statement period."""
    if df.empty:
        return {
            "transactions": 0,
            "start_date": None,
            "end_date": None,
            "total_spent": 0.0,
            "total_income": 0.0,
            "net": 0.0,
            "savings_rate_pct": None,
            "avg_daily_spend": 0.0,
            "largest_expense": None,
        }

    debits = _debits(df)
    spent = float(debits["amount"].sum())
    income = float(df.loc[df["type"] == "credit", "amount"].sum())
    days = max((df["date"].max() - df["date"].min()).days + 1, 1)

    largest = None
    if not debits.empty:
        row = debits.loc[debits["amount"].idxmax()]
        largest = {
            "date": row["date"].date().isoformat(),
            "merchant": str(row["merchant"]),
            "category": str(row["category"]),
            "amount": round(float(row["amount"]), 2),
        }

    return {
        "transactions": int(len(df)),
        "start_date": df["date"].min().date().isoformat(),
        "end_date": df["date"].max().date().isoformat(),
        "total_spent": round(spent, 2),
        "total_income": round(income, 2),
        "net": round(income - spent, 2),
        "savings_rate_pct": round((income - spent) / income * 100, 1) if income > 0 else None,
        "avg_daily_spend": round(spent / days, 2),
        "largest_expense": largest,
    }


def monthly(df: pd.DataFrame) -> list[dict]:
    """Income, spending and net per calendar month."""
    if df.empty:
        return []
    tmp = df.assign(month=df["date"].dt.strftime("%Y-%m"), amount=df["amount"].astype(float))
    pivot = tmp.pivot_table(
        index="month", columns="type", values="amount", aggfunc="sum", fill_value=0.0
    )
    for column in ("debit", "credit"):
        if column not in pivot:
            pivot[column] = 0.0
    return [
        {
            "month": str(month),
            "spent": round(float(row["debit"]), 2),
            "income": round(float(row["credit"]), 2),
            "net": round(float(row["credit"] - row["debit"]), 2),
        }
        for month, row in pivot.sort_index().iterrows()
    ]


def by_category(df: pd.DataFrame) -> list[dict]:
    """Spending per category, largest first, with share of total spend."""
    debits = _debits(df)
    if debits.empty:
        return []
    grouped = (
        debits.groupby("category")
        .agg(amount=("amount", "sum"), transactions=("amount", "size"))
        .sort_values("amount", ascending=False)
    )
    total = float(grouped["amount"].sum())
    return [
        {
            "category": str(category),
            "amount": round(float(row["amount"]), 2),
            "share_pct": round(float(row["amount"]) / total * 100, 1),
            "transactions": int(row["transactions"]),
        }
        for category, row in grouped.iterrows()
    ]


def top_merchants(df: pd.DataFrame, n: int = 10) -> list[dict]:
    """Merchants you spent the most with."""
    debits = _debits(df)
    if debits.empty:
        return []
    grouped = (
        debits.groupby("merchant")
        .agg(amount=("amount", "sum"), transactions=("amount", "size"))
        .sort_values("amount", ascending=False)
        .head(n)
    )
    return [
        {
            "merchant": str(merchant),
            "amount": round(float(row["amount"]), 2),
            "transactions": int(row["transactions"]),
        }
        for merchant, row in grouped.iterrows()
    ]


def detect_anomalies(
    df: pd.DataFrame,
    z_threshold: float = 3.5,
    min_group: int = 5,
    min_amount: float = 500.0,
    duplicate_min_amount: float = 200.0,
) -> pd.DataFrame:
    """Flag unusual debits.

    Two checks:
    * Statistical outliers within a category, using the modified z-score
      (median / MAD), which is robust to the outliers it is trying to find.
    * Possible duplicate charges: same merchant, amount and day.

    Returns the flagged rows with an extra ``reason`` column.
    """
    debits = _debits(df)
    reasons: dict[int, list[str]] = {}

    for category, group in debits.groupby("category"):
        if len(group) < min_group:
            continue
        median = group["amount"].median()
        mad = (group["amount"] - median).abs().median()
        scale = mad if mad > 0 else group["amount"].std(ddof=0)
        if not scale or scale <= 0:
            continue
        z = 0.6745 * (group["amount"] - median) / scale
        flagged = group[(z > z_threshold) & (group["amount"] >= min_amount)]
        for idx, row in flagged.iterrows():
            reasons.setdefault(idx, []).append(
                f"Unusually high for {category}: ₹{row['amount']:,.0f} vs typical ₹{median:,.0f}"
            )

    duplicates = debits[
        (debits["amount"] >= duplicate_min_amount)
        & debits.duplicated(subset=["merchant", "amount", "date"], keep="first")
    ]
    for idx in duplicates.index:
        reasons.setdefault(idx, []).append(
            "Possible duplicate charge (same merchant, amount and day)"
        )

    if not reasons:
        return df.iloc[0:0].assign(reason=pd.Series(dtype=str))

    out = df.loc[sorted(reasons)].copy()
    out["reason"] = [" · ".join(reasons[i]) for i in out.index]
    return out.sort_values("amount", ascending=False)


def recurring(
    df: pd.DataFrame,
    min_months: int = 3,
    tolerance: float = 0.1,
    min_consistent: float = 0.8,
    max_per_month: float = 1.5,
) -> list[dict]:
    """Detect subscriptions and other recurring payments.

    A merchant counts as recurring when it appears in at least ``min_months``
    different months, roughly once a month, with a consistent amount.
    """
    debits = _debits(df)
    if debits.empty:
        return []
    debits = debits.assign(month=debits["date"].dt.strftime("%Y-%m"))

    rows: list[dict] = []
    for merchant, group in debits.groupby("merchant"):
        if merchant == "Unknown":
            continue
        months = group["month"].nunique()
        if months < min_months or len(group) / months > max_per_month:
            continue
        median = float(group["amount"].median())
        consistent = float(((group["amount"] - median).abs() <= tolerance * median).mean())
        if consistent < min_consistent:
            continue
        rows.append(
            {
                "merchant": str(merchant),
                "category": str(group["category"].mode().iat[0]),
                "typical_amount": round(median, 2),
                "months_seen": int(months),
                "last_paid": group["date"].max().date().isoformat(),
            }
        )
    return sorted(rows, key=lambda r: r["typical_amount"], reverse=True)
