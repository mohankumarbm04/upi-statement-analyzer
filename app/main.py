"""FastAPI application: upload statements, browse and analyse transactions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__, insights, service
from app.database import Statement, Transaction, get_db, init_db
from app.parser import StatementParseError
from app.schemas import (
    AnomalyOut,
    CategoryOut,
    CategoryUpdate,
    MerchantOut,
    MonthlyOut,
    RecurringOut,
    StatementOut,
    SummaryOut,
    TransactionOut,
    UploadOut,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

DB = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="UPI Statement Analyzer",
    description=(
        "Upload a bank or UPI statement (CSV) and get automatic categorisation, "
        "monthly trends, subscription detection and anomaly alerts."
    ),
    version=__version__,
    lifespan=lifespan,
)


def _require_statement(db: Session, statement_id: int) -> Statement:
    statement = service.get_statement(db, statement_id)
    if statement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Statement {statement_id} not found")
    return statement


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post(
    "/statements",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    tags=["statements"],
)
async def upload_statement(db: DB, file: Annotated[UploadFile, File(...)]) -> UploadOut:
    """Upload a CSV statement. It is parsed, categorised and stored."""
    filename = file.filename or "statement.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv files are supported")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 5 MB")
    if not content.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty")

    try:
        statement = service.ingest_statement(db, filename, content)
    except StatementParseError as exc:
        raise HTTPException(422, str(exc)) from exc

    summary = insights.summary(service.statement_to_df(db, statement.id))
    return UploadOut(statement=StatementOut.model_validate(statement), summary=summary)


@app.get("/statements", response_model=list[StatementOut], tags=["statements"])
def list_statements(db: DB) -> list[Statement]:
    return list(db.execute(select(Statement).order_by(Statement.id.desc())).scalars())


@app.delete(
    "/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["statements"]
)
def delete_statement(statement_id: int, db: DB) -> None:
    db.delete(_require_statement(db, statement_id))
    db.commit()


@app.get(
    "/statements/{statement_id}/transactions",
    response_model=list[TransactionOut],
    tags=["transactions"],
)
def list_transactions(
    statement_id: int,
    db: DB,
    category: str | None = None,
    type: Literal["debit", "credit"] | None = None,
    q: Annotated[str | None, Query(description="Search merchant or description")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Transaction]:
    _require_statement(db, statement_id)
    query = select(Transaction).where(Transaction.statement_id == statement_id)
    if category:
        query = query.where(Transaction.category == category)
    if type:
        query = query.where(Transaction.type == type)
    if q:
        pattern = f"%{q}%"
        query = query.where(
            Transaction.merchant.ilike(pattern) | Transaction.description.ilike(pattern)
        )
    query = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).offset(offset)
    )
    return list(db.execute(query).scalars())


@app.patch("/transactions/{transaction_id}", response_model=TransactionOut, tags=["transactions"])
def update_category(transaction_id: int, body: CategoryUpdate, db: DB) -> Transaction:
    """Correct the category of a transaction."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transaction {transaction_id} not found")
    transaction.category = body.category.strip()
    db.commit()
    return transaction


@app.get("/statements/{statement_id}/summary", response_model=SummaryOut, tags=["insights"])
def get_summary(statement_id: int, db: DB) -> dict:
    _require_statement(db, statement_id)
    return insights.summary(service.statement_to_df(db, statement_id))


@app.get("/statements/{statement_id}/monthly", response_model=list[MonthlyOut], tags=["insights"])
def get_monthly(statement_id: int, db: DB) -> list[dict]:
    _require_statement(db, statement_id)
    return insights.monthly(service.statement_to_df(db, statement_id))


@app.get(
    "/statements/{statement_id}/categories", response_model=list[CategoryOut], tags=["insights"]
)
def get_categories(statement_id: int, db: DB) -> list[dict]:
    _require_statement(db, statement_id)
    return insights.by_category(service.statement_to_df(db, statement_id))


@app.get(
    "/statements/{statement_id}/merchants", response_model=list[MerchantOut], tags=["insights"]
)
def get_top_merchants(
    statement_id: int, db: DB, n: Annotated[int, Query(ge=1, le=50)] = 10
) -> list[dict]:
    _require_statement(db, statement_id)
    return insights.top_merchants(service.statement_to_df(db, statement_id), n)


@app.get(
    "/statements/{statement_id}/anomalies", response_model=list[AnomalyOut], tags=["insights"]
)
def get_anomalies(statement_id: int, db: DB) -> list[dict]:
    _require_statement(db, statement_id)
    flagged = insights.detect_anomalies(service.statement_to_df(db, statement_id))
    flagged = flagged.assign(date=flagged["date"].dt.date)
    records = flagged.drop(columns=["id"]).reset_index()
    # NaN is not valid JSON; statements without a balance column need null instead.
    records = records.astype(object).where(records.notna(), None)
    return records.to_dict(orient="records")


@app.get(
    "/statements/{statement_id}/recurring", response_model=list[RecurringOut], tags=["insights"]
)
def get_recurring(statement_id: int, db: DB) -> list[dict]:
    _require_statement(db, statement_id)
    return insights.recurring(service.statement_to_df(db, statement_id))
