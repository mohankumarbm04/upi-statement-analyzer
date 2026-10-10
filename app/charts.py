"""Plotly chart builders for the dashboard.

Design rules followed (see README "Design notes"):
* Form follows the data's job: grouped columns for two series over time,
  single-hue horizontal bars for rankings (magnitude), never pies.
* Thin marks with rounded data-ends, recessive gridlines, ink for text
  (never the series colour), a legend whenever there are two or more series.
* Palettes were validated for colour-blind separation and contrast in both
  light and dark mode.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.formatting import inr

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

THEMES: dict[str, dict] = {
    "light": {
        "series": ["#2a78d6", "#eb6834"],
        "primary": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "baseline": "#c3c2b7",
        "surface": "#fcfcfb",
    },
    "dark": {
        "series": ["#3987e5", "#d95926"],
        "primary": "#f0efec",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "baseline": "#383835",
        "surface": "#1a1a19",
    },
}


def _base_layout(fig: go.Figure, theme: dict, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 8, "t": 8, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 13, "color": theme["secondary"]},
        hoverlabel={
            "bgcolor": theme["surface"],
            "bordercolor": theme["grid"],
            "font": {"family": FONT, "color": theme["primary"]},
        },
        barcornerradius=4,
        showlegend=False,
    )
    return fig


def monthly_chart(rows: list[dict], theme: dict) -> go.Figure:
    """Grouped columns: spending vs income per month."""
    labels = [pd.Timestamp(f"{r['month']}-01").strftime("%b %Y") for r in rows]
    fig = go.Figure()
    for name, key, color in (
        ("Spent", "spent", theme["series"][0]),
        ("Income", "income", theme["series"][1]),
    ):
        fig.add_bar(
            name=name,
            x=labels,
            y=[r[key] for r in rows],
            marker_color=color,
            customdata=[inr(r[key]) for r in rows],
            hovertemplate="%{customdata}<extra>" + name + "</extra>",
        )

    _base_layout(fig, theme, height=320)
    fig.update_layout(
        barmode="group",
        bargap=0.35,
        bargroupgap=0.08,
        hovermode="x unified",
        showlegend=True,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.14,
            "yanchor": "bottom",
            "font": {"color": theme["secondary"]},
        },
        margin={"l": 0, "r": 8, "t": 36, "b": 0},
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor=theme["baseline"],
        ticks="",
        tickfont={"color": theme["muted"]},
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=theme["grid"],
        gridwidth=1,
        zeroline=False,
        showline=False,
        ticks="",
        tickprefix="₹",
        tickformat="~s",
        tickfont={"color": theme["muted"]},
    )
    return fig


def ranked_bar_chart(
    rows: list[dict], label_key: str, theme: dict, max_rows: int = 10
) -> go.Figure:
    """Single-hue horizontal bars, largest first, with the value labelled at the bar end."""
    rows = rows[:max_rows]
    labels = [r[label_key] for r in rows]
    values = [r["amount"] for r in rows]
    text = [
        f"{inr(r['amount'])}  ·  {r['share_pct']:.0f}%" if "share_pct" in r else inr(r["amount"])
        for r in rows
    ]
    custom = [[inr(r["amount"]), r["transactions"]] for r in rows]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=theme["series"][0],
            text=text,
            textposition="outside",
            textfont={"color": theme["secondary"], "size": 12},
            cliponaxis=False,
            customdata=custom,
            hovertemplate=(
                "%{y}<br>%{customdata[0]} across %{customdata[1]} transactions<extra></extra>"
            ),
        )
    )
    _base_layout(fig, theme, height=44 + 34 * max(len(rows), 1))
    fig.update_layout(bargap=0.4, margin={"l": 0, "r": 8, "t": 4, "b": 0})
    fig.update_xaxes(visible=False, range=[0, (max(values) if values else 1) * 1.45])
    fig.update_yaxes(
        autorange="reversed",
        showgrid=False,
        zeroline=False,
        linecolor=theme["baseline"],
        ticks="",
        tickfont={"color": theme["secondary"]},
    )
    return fig
