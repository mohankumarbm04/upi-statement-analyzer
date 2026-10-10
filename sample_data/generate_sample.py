"""Generate a realistic, fully synthetic bank statement for demos and tests.

Run from the project root:  python sample_data/generate_sample.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

START = date(2026, 4, 1)
END = date(2026, 9, 30)
OPENING_BALANCE = 50_000.00
OUTPUT = Path(__file__).parent / "sample_statement.csv"

FRIENDS = ["RAHUL SHARMA", "PRIYA NAIR", "ANKIT VERMA", "SNEHA REDDY", "KARTHIK IYER"]
HANDLES = ["okaxis", "ybl", "oksbi", "okicici", "paytm"]


def upi(merchant: str, note: str = "Payment", handle: str | None = None) -> str:
    ref = random.randint(10**11, 10**12 - 1)
    return f"UPI/DR/{ref}/{merchant}/{handle or random.choice(HANDLES)}/{note}"


# (date, narration, debit, credit)
events: list[tuple[date, str, float, float]] = []


def add(day: date, narration: str, debit: float = 0.0, credit: float = 0.0) -> None:
    events.append((day, narration, round(debit, 2), round(credit, 2)))


# --- Monthly fixed items -------------------------------------------------
month = date(START.year, START.month, 1)
while month <= END:
    y, m = month.year, month.month
    add(date(y, m, 1), "NEFT-CR-ACME TECHNOLOGIES SALARY", credit=85_000)
    add(date(y, m, 3), upi("CULT FIT", "Membership", "ybl"), 1_500)
    add(date(y, m, 5), upi("LANDLORD RAMESH KUMAR", "Rent", "ybl"), 22_000)
    add(date(y, m, 7), "ACH/DR/ZERODHA BROKING SIP", 5_000)
    add(date(y, m, 8), upi("AIRTEL", "Postpaid bill", "airtel"), 599)
    add(date(y, m, 12), upi("BESCOM", "Electricity bill", "billdesk"), random.randint(1_100, 1_500))
    add(date(y, m, 14), upi("NETFLIX", "Subscription", "okaxis"), 649)
    add(date(y, m, 16), upi("SPOTIFY", "Subscription", "okaxis"), 119)
    if m in (6, 9):
        add(date(y, m, 28), "CREDIT INTEREST CAPITALISED", credit=random.randint(380, 520))
    month = date(y + (m == 12), (m % 12) + 1, 1)

# --- Day-to-day spending -------------------------------------------------
day = START
while day <= END:
    if random.random() < 0.45:
        add(day, upi(random.choice(["SWIGGY", "ZOMATO"])), random.randint(150, 650))
    if random.random() < 0.30:
        add(day, upi(random.choice(["BLINKIT", "ZEPTO", "BIGBASKET"])), random.randint(200, 1_400))
    if random.random() < 0.35:
        add(day, upi(random.choice(["UBER", "RAPIDO", "OLA"])), random.randint(80, 450))
    if random.random() < 0.12:
        shop = random.choice(["AMAZON PAY", "FLIPKART", "MYNTRA"])
        add(day, upi(shop), random.randint(300, 3_500))
    if random.random() < 0.15:
        add(day, upi(random.choice(["CHAI POINT", "STARBUCKS"])), random.randint(120, 450))
    if random.random() < 0.04:
        add(day, upi(random.choice(["PHARMEASY", "APOLLO PHARMACY"])), random.randint(150, 900))
    if random.random() < 0.08:
        note = random.choice(["Dinner split", "Movie", "Trip", "Gift"])
        add(day, upi(random.choice(FRIENDS), note), random.randint(100, 2_000))
    if random.random() < 0.02:
        add(day, "ATM WDL/CASH/BLR MG ROAD", random.choice([2_000, 5_000]))
    day += timedelta(days=1)

# --- A few deliberate anomalies for the demo -----------------------------
add(date(2026, 7, 18), upi("CROMA", "Payment", "okicici"), 48_999)
add(date(2026, 8, 9), upi("SWIGGY", "Payment", "okaxis"), 749)
add(date(2026, 8, 9), upi("SWIGGY", "Payment", "okaxis"), 749)
add(date(2026, 9, 21), upi("UBER", "Airport trip", "okaxis"), 4_250)

# --- Write CSV with a running balance ------------------------------------
events.sort(key=lambda e: (e[0], e[3] == 0))  # credits first on the same day
balance = OPENING_BALANCE

with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["Date", "Narration", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    for when, narration, debit, credit in events:
        balance += credit - debit
        writer.writerow(
            [
                when.strftime("%d/%m/%Y"),
                narration,
                f"{debit:.2f}" if debit else "",
                f"{credit:.2f}" if credit else "",
                f"{balance:.2f}",
            ]
        )

print(f"Wrote {len(events)} transactions to {OUTPUT}")
