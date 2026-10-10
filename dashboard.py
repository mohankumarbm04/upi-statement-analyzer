"""Streamlit dashboard: drop in a bank statement CSV and explore your spending.

Run with:  streamlit run dashboard.py

Everything is processed in memory for the current session; nothing is stored.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app import insights
from app.categorizer import categorize_dataframe
from app.charts import THEMES, monthly_chart, ranked_bar_chart
from app.formatting import inr
from app.parser import StatementParseError, parse_statement

SAMPLE_PATH = Path(__file__).parent / "sample_data" / "sample_statement.csv"
CHART_CONFIG = {"displayModeBar": False}

st.set_page_config(page_title="UPI Statement Analyzer", page_icon="₹", layout="wide")


@st.cache_data(show_spinner=False)
def load(content: bytes) -> pd.DataFrame:
    return categorize_dataframe(parse_statement(content))


def current_theme() -> dict:
    try:
        return THEMES["dark" if st.context.theme.type == "dark" else "light"]
    except Exception:
        return THEMES["light"]


def table_view(rows: list[dict], label: str = "Table view") -> None:
    """Accessible fallback: every chart has its data available as a table."""
    with st.expander(label):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# --- Sidebar: input ---------------------------------------------------------
with st.sidebar:
    st.header("Your statement")
    upload = st.file_uploader("Bank / UPI statement (CSV)", type="csv")
    st.caption(
        "Needs a date column, a narration/description column and either "
        "debit + credit columns or a single amount column. Processed in memory only."
    )

if upload is not None:
    content, source = upload.getvalue(), upload.name
else:
    content, source = SAMPLE_PATH.read_bytes(), "synthetic sample data"

st.title("UPI & bank statement analyzer")
st.caption(f"Showing: {source}")
if upload is None:
    st.info("This is demo data. Upload your own CSV from the sidebar to analyse it.")

try:
    df = load(content)
except StatementParseError as exc:
    st.error(f"Could not read that file: {exc}")
    st.stop()

# --- Date filter (one row above the charts) ---------------------------------
first_day, last_day = df["date"].min().date(), df["date"].max().date()
selected = st.date_input(
    "Date range", value=(first_day, last_day), min_value=first_day, max_value=last_day
)
if isinstance(selected, tuple) and len(selected) == 2:
    start, end = selected
else:
    start, end = first_day, last_day

view = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)]
if view.empty:
    st.warning("No transactions in that date range.")
    st.stop()

theme = current_theme()
stats = insights.summary(view)

# --- KPI row ----------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total spent", inr(stats["total_spent"]))
k2.metric("Total income", inr(stats["total_income"]))
rate = stats["savings_rate_pct"]
k3.metric("Savings rate", f"{rate:.1f}%" if rate is not None else "n/a")
k4.metric("Avg daily spend", inr(stats["avg_daily_spend"]))

overview, transactions, alerts = st.tabs(["Overview", "Transactions", "Subscriptions & alerts"])

# --- Overview ---------------------------------------------------------------
with overview:
    st.subheader("Income vs spending by month")
    monthly_rows = insights.monthly(view)
    st.plotly_chart(
        monthly_chart(monthly_rows, theme), width="stretch", theme=None, config=CHART_CONFIG
    )
    table_view(monthly_rows, "Monthly table")

    left, right = st.columns(2)
    with left:
        st.subheader("Where your money goes")
        category_rows = insights.by_category(view)
        st.plotly_chart(
            ranked_bar_chart(category_rows, "category", theme, max_rows=12),
            width="stretch",
            theme=None,
            config=CHART_CONFIG,
        )
        table_view(category_rows, "Category table")
    with right:
        st.subheader("Top merchants")
        merchant_rows = insights.top_merchants(view, 8)
        st.plotly_chart(
            ranked_bar_chart(merchant_rows, "merchant", theme, max_rows=8),
            width="stretch",
            theme=None,
            config=CHART_CONFIG,
        )
        table_view(merchant_rows, "Merchant table")

# --- Transactions -----------------------------------------------------------
with transactions:
    f1, f2, f3 = st.columns([2, 1, 2])
    chosen = f1.multiselect("Category", sorted(view["category"].unique()))
    kind = f2.radio("Type", ["All", "Spent", "Income"], horizontal=True)
    search = f3.text_input("Search merchant or narration")

    rows = view
    if chosen:
        rows = rows[rows["category"].isin(chosen)]
    if kind != "All":
        rows = rows[rows["type"] == ("debit" if kind == "Spent" else "credit")]
    if search:
        mask = rows["merchant"].str.contains(search, case=False, regex=False) | rows[
            "description"
        ].str.contains(search, case=False, regex=False)
        rows = rows[mask]

    shown = rows.assign(date=rows["date"].dt.date)[
        ["date", "merchant", "category", "amount", "type", "description"]
    ].sort_values("date", ascending=False)
    st.caption(f"{len(shown)} transactions")
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config={"amount": st.column_config.NumberColumn("Amount (₹)", format="%.2f")},
    )
    st.download_button(
        "Download categorised CSV",
        shown.to_csv(index=False).encode("utf-8"),
        file_name="categorised_transactions.csv",
        mime="text/csv",
    )

# --- Subscriptions & alerts -------------------------------------------------
with alerts:
    st.subheader("Recurring payments")
    recurring_rows = insights.recurring(view)
    if recurring_rows:
        monthly_cost = sum(r["typical_amount"] for r in recurring_rows)
        st.metric("Estimated fixed monthly outgoings", inr(monthly_cost))
        st.dataframe(
            pd.DataFrame(recurring_rows).rename(
                columns={
                    "merchant": "Merchant",
                    "category": "Category",
                    "typical_amount": "Typical amount (₹)",
                    "months_seen": "Months seen",
                    "last_paid": "Last paid",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.write("No recurring payments detected in this range (needs 3+ months of data).")

    st.subheader("Unusual transactions")
    flagged = insights.detect_anomalies(view)
    if flagged.empty:
        st.success("Nothing unusual found.")
    else:
        st.warning(f"{len(flagged)} transactions look unusual. Worth a quick check.")
        st.dataframe(
            flagged.assign(date=flagged["date"].dt.date)[
                ["date", "merchant", "category", "amount", "reason"]
            ],
            hide_index=True,
            width="stretch",
        )
