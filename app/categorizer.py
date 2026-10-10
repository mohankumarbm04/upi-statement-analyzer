"""Merchant extraction and spending categorisation.

Categorisation is two-stage:

1. Keyword rules (fast, precise) matched against the whole narration.
2. A small TF-IDF + logistic regression model on character n-grams as a
   fallback for merchants the rules do not know (handles typos and near
   matches such as "Swigy" -> Food & Dining). Low-confidence predictions fall
   back to "Others" so the app does not guess wildly; users can correct any
   category through the API.
"""

from __future__ import annotations

import re

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline

# Order matters: the first matching category wins, so more specific
# categories (e.g. Groceries for "Swiggy Instamart") come before broader ones.
CATEGORY_RULES: dict[str, list[str]] = {
    "Groceries": [
        "bigbasket", "blinkit", "zepto", "instamart", "dmart", "grofers", "jiomart",
        "reliance fresh", "more retail", "supermarket", "kirana", "natures basket",
        "grocery", "vegetables",
    ],
    "Food & Dining": [
        "swiggy", "zomato", "dominos", "mcdonald", "kfc", "starbucks", "cafe",
        "restaurant", "pizza", "burger", "biryani", "eatsure", "haldiram", "chaayos",
        "barbeque", "bakery", "dhaba", "chai",
    ],
    "Entertainment": [
        "netflix", "spotify", "hotstar", "prime video", "amazon prime", "bookmyshow",
        "youtube", "sonyliv", "zee5", "inox", "pvr", "gaana", "disney",
    ],
    "Travel": [
        "makemytrip", "goibibo", "cleartrip", "airbnb", "oyo", "indigo", "air india",
        "vistara", "irctc", "redbus", "hotel",
    ],
    "Transport": [
        "uber", "ola", "rapido", "metro", "fastag", "indian oil", "iocl", "hpcl",
        "bpcl", "petrol", "fuel", "namma yatri", "parking",
    ],
    "Shopping": [
        "amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "croma",
        "decathlon", "lifestyle", "reliance digital", "vijay sales",
    ],
    "Bills & Utilities": [
        "electricity", "bescom", "airtel", "jio", "vodafone", "bsnl", "broadband",
        "fibernet", "tata power", "water bill", "gas bill", "recharge", "dth",
        "tata sky", "billdesk", "postpaid",
    ],
    "Health": [
        "apollo", "pharmeasy", "1mg", "netmeds", "medplus", "hospital", "clinic",
        "diagnostic", "practo", "pharmacy", "medical",
    ],
    "Education": [
        "udemy", "coursera", "unacademy", "byju", "college", "tuition", "exam fee",
        "nptel", "university", "school",
    ],
    "Rent & Housing": ["rent", "nobroker", "housing society", "maintenance"],
    "Investments": [
        "zerodha", "groww", "upstox", "mutual fund", "sip", "kuvera", "ppf", "nps",
        "smallcase",
    ],
    "Cash & Transfers": ["atm", "cash withdrawal", "self transfer", "neft", "imps", "rtgs"],
}

# Extra merchant names used only to train the fallback model.
EXTRA_EXAMPLES: dict[str, list[str]] = {
    "Food & Dining": [
        "faasos", "behrouz biryani", "subway", "burger king", "pizza hut", "chai point",
        "third wave coffee", "baskin robbins", "wow momo", "cafe coffee day", "theobroma",
    ],
    "Groceries": [
        "spencers", "star bazaar", "licious", "freshtohome", "milkbasket", "country delight",
    ],
    "Transport": [
        "bmtc", "namma metro", "yulu", "bounce", "blu smart", "indrive", "shell petrol",
        "hp petrol pump", "car wash",
    ],
    "Shopping": [
        "reliance trends", "westside", "pantaloons", "bata", "lenskart", "tata cliq",
        "snapdeal", "shoppers stop", "ikea", "pepperfry", "firstcry", "max fashion",
    ],
    "Entertainment": ["apple music", "jiocinema", "bigtree", "steam games", "playstation"],
    "Bills & Utilities": [
        "bwssb", "indane gas", "hp gas", "bharat gas", "mahanagar gas", "act broadband",
        "hathway", "excitel", "insurance premium", "lic premium",
    ],
    "Health": [
        "dr lal pathlabs", "metropolis", "tata 1mg", "cult fit", "gym membership",
        "dental clinic", "eye care", "medical store", "wellness forever", "healthifyme",
    ],
    "Education": [
        "physics wallah", "great learning", "simplilearn", "skillshare", "linkedin learning",
        "college fees", "school fees", "stationery", "bookstore",
    ],
    "Rent & Housing": [
        "house rent", "pg rent", "flat maintenance", "apartment association",
        "urban company", "magicbricks",
    ],
    "Investments": [
        "angel one", "icici direct", "hdfc securities", "axis mutual fund", "sbi mutual fund",
        "recurring deposit", "fixed deposit", "gold bees", "sovereign gold",
    ],
    "Travel": ["yatra", "easemytrip", "ixigo", "akasa air", "spicejet", "taj hotels", "treebo"],
    "Cash & Transfers": ["atm cash", "own account", "neft transfer", "imps transfer"],
}

_NOISE_WORDS = {
    "upi", "dr", "cr", "p2a", "p2m", "p2p", "payment", "pos", "neft", "imps", "rtgs",
    "ach", "ecs", "txn", "ref", "to", "from", "by", "via", "paid", "for",
}


def _compile(keyword: str) -> re.Pattern[str]:
    """Prefix match for long keywords, whole-word match for short ones."""
    escaped = re.escape(keyword.lower())
    suffix = "" if len(keyword) >= 5 else r"\b"
    return re.compile(rf"\b{escaped}{suffix}")


_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [_compile(k) for k in keywords] for category, keywords in CATEGORY_RULES.items()
}


def rule_category(text: str) -> str | None:
    """Return the first category whose keyword matches ``text`` (lower-cased)."""
    for category, patterns in _PATTERNS.items():
        if any(p.search(text) for p in patterns):
            return category
    return None


def _tidy(value: str) -> str:
    value = value.split("@")[0]
    value = re.sub(r"[^A-Za-z&.' ]+", " ", value)
    words = [w.capitalize() for w in value.split()]
    return " ".join(words) or "Unknown"


def extract_merchant(description: str | None) -> str:
    """Best-effort merchant / counterparty name from a bank narration."""
    desc = (description or "").strip()
    if not desc:
        return "Unknown"

    if re.search(r"\batm\b", desc, re.IGNORECASE):
        return "ATM Withdrawal"

    if desc.upper().startswith("UPI"):
        if "/" in desc:
            parts = [p.strip() for p in desc.split("/")]
            for i, part in enumerate(parts):
                if part.isdigit() and len(part) >= 9 and i + 1 < len(parts) and parts[i + 1]:
                    return _tidy(parts[i + 1])
        elif "-" in desc:
            for part in (p.strip() for p in desc.split("-")[1:]):
                looks_like_name = part and not part.isdigit() and "@" not in part
                if looks_like_name and part.lower() not in _NOISE_WORDS:
                    return _tidy(part)

    tokens = re.findall(r"[A-Za-z][A-Za-z&.']+", desc)
    # Drop noise words and masked card numbers such as "XXXXXX".
    tokens = [t for t in tokens if t.lower() not in _NOISE_WORDS and len(set(t.lower())) > 1]
    return _tidy(" ".join(tokens[:2])) if tokens else "Unknown"


class Categorizer:
    """Rule-based categoriser with a character n-gram ML fallback."""

    def __init__(self, use_ml: bool = True, threshold: float = 0.6) -> None:
        # 0.6 was chosen empirically: misspelled merchants ("Swigy", "Dominoz")
        # score ~0.7-0.9 while personal names (UPI transfers to friends) stay
        # at or below ~0.5, so they correctly fall through to "Others".
        self.use_ml = use_ml
        self.threshold = threshold
        self._model: Pipeline | None = None

    @staticmethod
    def _fit() -> Pipeline:
        texts: list[str] = []
        labels: list[str] = []
        for source in (CATEGORY_RULES, EXTRA_EXAMPLES):
            for category, examples in source.items():
                texts.extend(e.lower() for e in examples)
                labels.extend([category] * len(examples))
        model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)),
            LogisticRegression(C=20, max_iter=2000),
        )
        model.fit(texts, labels)
        return model

    def predict_ml(self, merchant: str) -> str | None:
        """Predict a category from a merchant name, or None if not confident."""
        if self._model is None:
            self._model = self._fit()
        probabilities = self._model.predict_proba([merchant.lower()])[0]
        best = int(probabilities.argmax())
        if probabilities[best] >= self.threshold:
            return str(self._model.classes_[best])
        return None

    def categorize(
        self, description: str | None, txn_type: str = "debit", merchant: str | None = None
    ) -> str:
        if txn_type == "credit":
            return "Income"
        category = rule_category((description or "").lower())
        if category:
            return category
        if self.use_ml:
            name = merchant or extract_merchant(description)
            if name != "Unknown":
                category = self.predict_ml(name)
                if category:
                    return category
        return "Others"


default_categorizer = Categorizer()


def categorize_dataframe(df: pd.DataFrame, categorizer: Categorizer | None = None) -> pd.DataFrame:
    """Return a copy of ``df`` with ``merchant`` and ``category`` columns added."""
    engine = categorizer or default_categorizer
    out = df.copy()
    out["merchant"] = out["description"].map(extract_merchant)
    out["category"] = [
        engine.categorize(desc, kind, merchant)
        for desc, kind, merchant in zip(
            out["description"], out["type"], out["merchant"], strict=True
        )
    ]
    return out
