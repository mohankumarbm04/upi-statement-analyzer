import datetime as dt

import pytest

from app.parser import StatementParseError, parse_statement


def test_debit_credit_columns():
    csv = (
        "Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        '01/04/2026,UPI/DR/123456789012/SWIGGY/okaxis/Payment,"1,250.50",,"48,749.50"\n'
        '02/04/2026,NEFT-CR-ACME SALARY,,"85,000.00","133,749.50"\n'
    )
    df = parse_statement(csv)

    assert len(df) == 2
    assert df.loc[0, "type"] == "debit"
    assert df.loc[0, "amount"] == 1250.50
    assert df.loc[1, "type"] == "credit"
    assert df.loc[1, "amount"] == 85000.0
    assert df.loc[1, "balance"] == 133749.50
    # Indian statements are day-first: 01/04 is 1 April, not 4 January.
    assert df.loc[0, "date"].date() == dt.date(2026, 4, 1)


def test_single_signed_amount_column():
    df = parse_statement("Date,Description,Amount\n05/01/2026,Coffee,-250\n06/01/2026,Refund,100\n")

    assert list(df["type"]) == ["debit", "credit"]
    assert list(df["amount"]) == [250.0, 100.0]


def test_amount_with_dr_cr_column():
    csv = (
        "Txn Date,Particulars,Amount,Dr/Cr\n"
        "05/01/2026,Groceries,500,Dr\n"
        "06/01/2026,Salary,9000,Cr\n"
        "07/01/2026,Mystery,1,??\n"
    )
    df = parse_statement(csv)

    assert list(df["type"]) == ["debit", "credit"]  # unknown type row is dropped


def test_skips_preamble_above_header():
    csv = (
        "Account Statement\n"
        "Account No: XXXXXX1234\n"
        "Period: 01/01/2026 to 31/01/2026\n"
        "\n"
        "Date,Narration,Debit,Credit\n"
        "02/01/2026,Chai,20,\n"
    )
    df = parse_statement(csv)

    assert len(df) == 1
    assert df.loc[0, "amount"] == 20.0


def test_iso_dates_are_not_swapped():
    df = parse_statement("Date,Narration,Debit,Credit\n2026-01-05,Chai,20,\n")

    assert df.loc[0, "date"].date() == dt.date(2026, 1, 5)


def test_rupee_symbol_and_rs_prefix():
    csv = (
        "Date,Narration,Debit,Credit\n"
        '01/01/2026,A,"₹1,200",\n'
        "02/01/2026,B,Rs. 300,\n"
    )
    df = parse_statement(csv)

    assert list(df["amount"]) == [1200.0, 300.0]


def test_rows_sorted_by_date():
    df = parse_statement("Date,Narration,Debit,Credit\n03/01/2026,B,2,\n01/01/2026,A,1,\n")

    assert list(df["description"]) == ["A", "B"]


def test_latin1_bytes_are_decoded():
    df = parse_statement(b"Date,Narration,Debit,Credit\n01/01/2026,Caf\xe9,100,\n")

    assert df.loc[0, "description"] == "Café"


def test_missing_balance_column_gives_nan():
    df = parse_statement("Date,Narration,Debit,Credit\n01/01/2026,A,10,\n")

    assert df["balance"].isna().all()


@pytest.mark.parametrize(
    "content, message",
    [
        ("", "empty"),
        ("Foo,Bar\n1,2\n", "header"),
        ("Date,Narration\n01/01/2026,A\n", "amount"),
        ("Date,Narration,Debit,Credit\n", "No valid"),
        ("Date,Narration,Debit,Credit\nnot a date,A,10,\n", "No valid"),
    ],
)
def test_invalid_files_raise_clear_errors(content, message):
    with pytest.raises(StatementParseError, match=message):
        parse_statement(content)


def test_sample_statement_parses(sample_bytes):
    df = parse_statement(sample_bytes)

    assert len(df) == 317
    assert set(df["type"]) == {"debit", "credit"}
    assert df["amount"].gt(0).all()
    assert df["date"].is_monotonic_increasing
