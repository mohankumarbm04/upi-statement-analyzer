import pandas as pd
import pytest

from app.categorizer import Categorizer, categorize_dataframe, extract_merchant

RULES_ONLY = Categorizer(use_ml=False)
WITH_ML = Categorizer()


@pytest.mark.parametrize(
    "description, expected",
    [
        ("UPI/DR/412345678901/SWIGGY/okaxis/Payment", "Swiggy"),
        ("UPI-ZOMATO-zomato@hdfcbank-412345678901-Payment", "Zomato"),
        ("NEFT-CR-ACME TECHNOLOGIES SALARY", "Acme Technologies"),
        ("ATM WDL/CASH/BLR MG ROAD", "ATM Withdrawal"),
        ("POS 4567XXXXXX1234 AMAZON PAY INDIA", "Amazon Pay"),
        ("", "Unknown"),
        (None, "Unknown"),
    ],
)
def test_extract_merchant(description, expected):
    assert extract_merchant(description) == expected


@pytest.mark.parametrize(
    "description, expected",
    [
        ("UPI/DR/412345678901/SWIGGY/okaxis/Payment", "Food & Dining"),
        ("UPI/DR/412345678901/BLINKIT/okaxis/Payment", "Groceries"),
        ("UPI/DR/412345678901/UBER/ybl/Payment", "Transport"),
        ("UPI/DR/412345678901/NETFLIX/ybl/Subscription", "Entertainment"),
        ("UPI/DR/412345678901/BESCOM/billdesk/Electricity bill", "Bills & Utilities"),
        ("UPI/DR/412345678901/LANDLORD RAMESH KUMAR/ybl/Rent", "Rent & Housing"),
        ("ACH/DR/ZERODHA BROKING SIP", "Investments"),
        ("ATM WDL/CASH/BLR MG ROAD", "Cash & Transfers"),
        # Priority: the more specific category must win.
        ("SWIGGY INSTAMART ORDER", "Groceries"),
        ("AMAZON PRIME MEMBERSHIP", "Entertainment"),
    ],
)
def test_keyword_rules(description, expected):
    assert RULES_ONLY.categorize(description) == expected


def test_credits_are_always_income():
    assert RULES_ONLY.categorize("NEFT-CR-ACME SALARY", "credit") == "Income"
    assert RULES_ONLY.categorize("SWIGGY REFUND", "credit") == "Income"


def test_short_keywords_match_whole_words_only():
    # "ola" must not match inside "coolant".
    assert RULES_ONLY.categorize("COOLANT SERVICE CENTRE") == "Others"
    assert RULES_ONLY.categorize("UPI/DR/412345678901/OLA/ybl/Ride") == "Transport"


def test_ml_fallback_handles_typos():
    assert RULES_ONLY.categorize("UPI/DR/412345678901/SWIGY/okaxis/Payment") == "Others"
    assert WITH_ML.categorize("UPI/DR/412345678901/SWIGY/okaxis/Payment") == "Food & Dining"


@pytest.mark.parametrize("name", ["RAHUL SHARMA", "ANKIT VERMA", "DEEPA MENON", "PRIYA NAIR"])
def test_personal_transfers_are_not_guessed(name):
    # Regression: "Ankit Verma" used to be classified as Groceries at a 0.5 threshold.
    description = f"UPI/DR/412345678901/{name}/okaxis/Dinner split"
    assert WITH_ML.categorize(description) == "Others"


def test_categorize_dataframe_adds_columns():
    df = pd.DataFrame(
        {
            "description": ["UPI/DR/412345678901/SWIGGY/okaxis/Payment", "NEFT-CR-ACME SALARY"],
            "type": ["debit", "credit"],
        }
    )
    out = categorize_dataframe(df)

    assert list(out["merchant"]) == ["Swiggy", "Acme Salary"]
    assert list(out["category"]) == ["Food & Dining", "Income"]
    assert "category" not in df.columns  # input is not mutated
