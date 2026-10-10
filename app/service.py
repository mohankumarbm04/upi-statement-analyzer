"""Glue between the pure analysis code and the database."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categorizer import categorize_dataframe
from app.database import Statement, Transaction
from app.parser import parse_statement


def ingest_statement(db: Session, filename: str, content: bytes) -> Statement:
    """Parse, categorise and store an uploaded statement.

    Raises ``StatementParseError`` if the file cannot be understood.
    """
    df = categorize_dataframe(parse_statement(content))

    statement = Statement(filename=filename)
    statement.transactions = [
        Transaction(
            date=row.date.date(),
            description=row.description[:500],
            merchant=row.merchant[:120],
            category=row.category,
            amount=float(row.amount),
            type=row.type,
            balance=None if pd.isna(row.balance) else float(row.balance),
        )
        for row in df.itertuples(index=False)
    ]
    db.add(statement)
    db.commit()
    return statement


def get_statement(db: Session, statement_id: int) -> Statement | None:
    return db.get(Statement, statement_id)


def statement_to_df(db: Session, statement_id: int) -> pd.DataFrame:
    """Load a statement's transactions as the DataFrame the insights expect."""
    query = (
        select(Transaction)
        .where(Transaction.statement_id == statement_id)
        .order_by(Transaction.date, Transaction.id)
    )
    rows = db.execute(query).scalars()
    records = [
        {
            "id": t.id,
            "date": pd.Timestamp(t.date),
            "description": t.description,
            "merchant": t.merchant,
            "category": t.category,
            "amount": t.amount,
            "type": t.type,
            "balance": t.balance,
        }
        for t in rows
    ]
    columns = ["id", "date", "description", "merchant", "category", "amount", "type", "balance"]
    df = pd.DataFrame.from_records(records, columns=columns)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("id", drop=False)
