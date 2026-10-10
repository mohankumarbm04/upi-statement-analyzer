import pytest

from app import insights
from app.categorizer import categorize_dataframe
from app.charts import THEMES, monthly_chart, ranked_bar_chart
from app.formatting import inr
from app.parser import parse_statement


@pytest.fixture(scope="module")
def sample_df(sample_bytes):
    return categorize_dataframe(parse_statement(sample_bytes))


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "₹0"),
        (999, "₹999"),
        (1000, "₹1,000"),
        (132000, "₹1,32,000"),
        (1234567.8, "₹12,34,568"),
        (-4500, "-₹4,500"),
    ],
)
def test_inr_uses_indian_grouping(value, expected):
    assert inr(value) == expected


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_monthly_chart_structure(sample_df, mode):
    theme = THEMES[mode]
    fig = monthly_chart(insights.monthly(sample_df), theme)

    assert [t.name for t in fig.data] == ["Spent", "Income"]
    assert [t.marker.color for t in fig.data] == theme["series"]
    assert fig.layout.showlegend is True  # two series always get a legend
    assert len(fig.data[0].x) == 6
    assert fig.layout.hovermode == "x unified"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ranked_bar_chart_structure(sample_df, mode):
    theme = THEMES[mode]
    rows = insights.by_category(sample_df)
    fig = ranked_bar_chart(rows, "category", theme, max_rows=5)

    (bars,) = fig.data
    assert bars.orientation == "h"
    assert list(bars.y) == [r["category"] for r in rows[:5]]
    assert bars.marker.color == theme["series"][0]  # one hue: length carries magnitude
    assert fig.layout.yaxis.autorange == "reversed"  # largest at the top
    assert fig.layout.showlegend is False  # single series needs no legend
    assert "₹1,32,000" in bars.text[0]  # labelled at the bar end


def test_themes_define_the_same_tokens():
    assert THEMES["light"].keys() == THEMES["dark"].keys()
    assert THEMES["light"]["series"] != THEMES["dark"]["series"]
