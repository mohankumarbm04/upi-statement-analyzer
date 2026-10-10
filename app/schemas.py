"""Pydantic response / request models for the API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploaded_at: dt.datetime


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: dt.date
    description: str
    merchant: str
    category: str
    amount: float
    type: str
    balance: float | None = None


class CategoryUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=60, examples=["Food & Dining"])


class LargestExpense(BaseModel):
    date: dt.date
    merchant: str
    category: str
    amount: float


class SummaryOut(BaseModel):
    transactions: int
    start_date: dt.date | None
    end_date: dt.date | None
    total_spent: float
    total_income: float
    net: float
    savings_rate_pct: float | None
    avg_daily_spend: float
    largest_expense: LargestExpense | None


class UploadOut(BaseModel):
    statement: StatementOut
    summary: SummaryOut


class MonthlyOut(BaseModel):
    month: str
    spent: float
    income: float
    net: float


class CategoryOut(BaseModel):
    category: str
    amount: float
    share_pct: float
    transactions: int


class MerchantOut(BaseModel):
    merchant: str
    amount: float
    transactions: int


class AnomalyOut(TransactionOut):
    reason: str


class RecurringOut(BaseModel):
    merchant: str
    category: str
    typical_amount: float
    months_seen: int
    last_paid: dt.date
