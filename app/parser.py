"""Parse bank / UPI statement CSV exports into one clean, uniform DataFrame.

Indian banks export statements in many shapes: separate debit/credit columns,
a single signed amount, a Dr/Cr type column, preamble lines above the header,
rupee symbols and thousands separators. This module normalises all of them to:

    date (datetime64), description (str), amount (float > 0),
    type ("debit" | "credit"), balance (float, NaN when absent)
"""

from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd


class StatementParseError(ValueError):
    """Raised when a statement file cannot be understood."""


_ALIASES: dict[str, list[str]] = {
    "date": [
        "date",
        "txn date",
        "transaction date",
        "tran date",
        "value date",
        "posting date",
    ],
    "description": [
        "description",
        "narration",
        "particulars",
        "details",
        "transaction details",
        "transaction remarks",
        "remarks",
    ],
    "debit": [
        "debit",
        "debit amount",
        "withdrawal",
        "withdrawals",
        "withdrawal amt.",
        "withdrawal amount",
        "dr",
    ],
    "credit": [
        "credit",
        "credit amount",
        "deposit",
        "deposits",
        "deposit amt.",
        "deposit amount",
        "cr",
    ],
    "amount": ["amount", "txn amount", "transaction amount"],
    "type": ["type", "dr/cr", "cr/dr", "transaction type", "txn type"],
    "balance": ["balance", "closing balance", "running balance", "balance amt."],
}

_HEADER_SCAN_LINES = 30
_AMOUNT_NOISE = re.compile(r"(?i)rs\.?|inr|[₹,\s]")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _norm(name: object) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _find_header_row(lines: list[str]) -> int:
    date_names = set(_ALIASES["date"])
    desc_names = set(_ALIASES["description"])
    for i, line in enumerate(lines[:_HEADER_SCAN_LINES]):
        cells = {_norm(cell.strip().strip('"')) for cell in line.split(",")}
        if cells & date_names and cells & desc_names:
            return i
    raise StatementParseError(
        "Could not find a header row. The file needs a date column and a "
        "description/narration column."
    )


def _pick(columns: dict[str, str], key: str) -> str | None:
    for alias in _ALIASES[key]:
        if alias in columns:
            return columns[alias]
    return None


def _to_number(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(_AMOUNT_NOISE, "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _to_dates(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    present = text[~text.isin(["", "nan", "NaN", "None"])]
    if not present.empty and present.str.match(_ISO_DATE).all():
        return pd.to_datetime(text.str[:10], format="%Y-%m-%d", errors="coerce")
    return pd.to_datetime(text, dayfirst=True, errors="coerce", format="mixed")


def parse_statement(content: bytes | str) -> pd.DataFrame:
    """Parse raw CSV content into a normalised transactions DataFrame."""
    text = _decode(content)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise StatementParseError("The file is empty.")

    header_idx = _find_header_row(lines)
    try:
        raw = pd.read_csv(
            io.StringIO("\n".join(lines[header_idx:])),
            dtype=str,
            skipinitialspace=True,
            on_bad_lines="skip",
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise StatementParseError(f"Could not read CSV: {exc}") from exc

    columns = {_norm(c): c for c in raw.columns}
    date_col = _pick(columns, "date")
    desc_col = _pick(columns, "description")
    debit_col = _pick(columns, "debit")
    credit_col = _pick(columns, "credit")
    amount_col = _pick(columns, "amount")
    type_col = _pick(columns, "type")
    balance_col = _pick(columns, "balance")

    if date_col is None or desc_col is None:
        raise StatementParseError("Missing a date or description column.")

    out = pd.DataFrame(
        {
            "date": _to_dates(raw[date_col]),
            "description": raw[desc_col].fillna("").astype(str).str.strip(),
        }
    )

    if debit_col and credit_col:
        debit = _to_number(raw[debit_col]).fillna(0).abs()
        credit = _to_number(raw[credit_col]).fillna(0).abs()
        out["amount"] = debit.where(debit > 0, credit)
        out["type"] = np.where(debit > 0, "debit", "credit")
    elif amount_col:
        amount = _to_number(raw[amount_col])
        out["amount"] = amount.abs()
        if type_col:
            kind = raw[type_col].astype(str).str.strip().str.lower()
            is_debit = kind.str.match(r"^(dr|debit|d\b|withdraw)")
            is_credit = kind.str.match(r"^(cr|credit|c\b|deposit)")
            out["type"] = np.select([is_debit, is_credit], ["debit", "credit"], default="")
        else:
            out["type"] = np.where(amount < 0, "debit", "credit")
    else:
        raise StatementParseError(
            "Could not find amount columns. "
            "Expected debit/credit columns or a single amount column."
        )

    out["balance"] = _to_number(raw[balance_col]) if balance_col else np.nan

    out = out.dropna(subset=["date", "amount"])
    out = out[(out["amount"] > 0) & out["type"].isin(["debit", "credit"])]
    if out.empty:
        raise StatementParseError("No valid transactions were found in the file.")

    return out.sort_values("date", kind="stable").reset_index(drop=True)
