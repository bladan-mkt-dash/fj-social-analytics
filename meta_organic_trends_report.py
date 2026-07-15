"""
Meta organic trends — Five Journeys Facebook & Instagram.

Monthly tracker history (2023–present):
  • Views, reach, total followers
  • Interactions, link clicks, visits, new followers

Run:

    streamlit run meta_organic_trends_report.py --server.port 8856
    # (private monorepo: streamlit run DC-Live-Dash/meta_organic_trends_report.py --server.port 8856)

Open:

    http://127.0.0.1:8856/
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
# Private monorepo: file lives in DC-Live-Dash/, .env at repo root.
# Public fj-social-analytics: file + .env both at repo root.
_ROOT = _HERE.parent if (_HERE.parent / ".env").exists() and not (_HERE / ".env").exists() else _HERE
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")

from meta_organic_trends_data import load_meta_organic_trends, platform_frame
from meta_organic_top_views import fetch_top_organic_by_views

COLORS = {
    "accent_dark": "#264540",
    "page_bg": "#F4F8FB",
    "views": "#4C78A8",
    "reach": "#F58518",
    "followers": "#54A24B",
    "interactions": "#E45756",
    "link_clicks": "#B279A2",
    "visits": "#72B7B2",
    "new_followers": "#FF9D98",
    "muted": "#6B7C93",
}

CAMPAIGN_BREAKDOWN_URL = "http://127.0.0.1:8854/"


def _inject_styles() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {COLORS["page_bg"]} !important; }}
        h1, h2, h3, p, label {{ color: {COLORS["accent_dark"]} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_trends() -> pd.DataFrame:
    return load_meta_organic_trends()


@st.cache_data(ttl=3600, show_spinner="Scanning organic posts for lifetime views…")
def _cached_top_views(top_n: int = 5, max_scan: int = 500) -> dict:
    return fetch_top_organic_by_views(top_n=top_n, max_scan=max_scan)


def _render_top_views_table(
    df: pd.DataFrame,
    *,
    platform: str,
    excluded: int,
    scanned: int,
    with_views: int,
) -> None:
    st.markdown(f"**Top 5 organic {platform} posts by views (all-time)**")
    st.caption(
        f"Ranked by lifetime views. Boosted/paid creatives excluded "
        f"({excluded} removed). Scanned most recent {scanned} posts from Meta; "
        f"{with_views} had readable view counts. "
        "This is the all-time leaderboard among scanned organic posts."
    )
    if df is None or df.empty:
        st.info(f"No organic {platform} posts with view counts found.")
        return
    show = df.copy()
    if "Views" in show.columns:
        show["Views"] = show["Views"].map(
            lambda v: f"{int(v):,}" if pd.notna(v) else ""
        )
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("URL"),
            "Preview": st.column_config.TextColumn(width="large"),
        },
    )


def _apply_layout(fig: go.Figure, *, title: str) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=18, color=COLORS["accent_dark"])),
        height=440,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor=COLORS["page_bg"],
        font=dict(color=COLORS["accent_dark"]),
    )
    fig.update_xaxes(title_text="Month", showgrid=True, gridcolor="#E6EEF5")
    return fig


def _reach_figure(df: pd.DataFrame, *, title: str) -> go.Figure:
    """Dual-axis: views + reach (left), total followers (right)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.update_layout(title=title)
        return fig

    months = df["month"]
    fig.add_trace(
        go.Scatter(
            x=months,
            y=df["views"],
            name="Views",
            mode="lines+markers",
            line=dict(color=COLORS["views"], width=2.5),
            marker=dict(size=5),
            connectgaps=False,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=months,
            y=df["reach"],
            name="Reach",
            mode="lines+markers",
            line=dict(color=COLORS["reach"], width=2.5),
            marker=dict(size=5),
            connectgaps=False,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=months,
            y=df["followers"],
            name="Total followers",
            mode="lines+markers",
            line=dict(color=COLORS["followers"], width=3),
            marker=dict(size=6),
            connectgaps=False,
        ),
        secondary_y=True,
    )
    _apply_layout(fig, title=title)
    fig.update_yaxes(
        title_text="Views / reach",
        secondary_y=False,
        showgrid=True,
        gridcolor="#E6EEF5",
        tickformat=",",
    )
    fig.update_yaxes(
        title_text="Total followers",
        secondary_y=True,
        showgrid=False,
        tickformat=",",
    )
    return fig


def _engagement_figure(df: pd.DataFrame, *, title: str) -> go.Figure:
    """Dual-axis: interactions (left), new followers (right)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.update_layout(title=title)
        return fig

    months = df["month"]
    if "interactions" in df.columns and not df["interactions"].isna().all():
        fig.add_trace(
            go.Scatter(
                x=months,
                y=df["interactions"],
                name="Interactions",
                mode="lines+markers",
                line=dict(color=COLORS["interactions"], width=2.5),
                marker=dict(size=5),
                connectgaps=False,
            ),
            secondary_y=False,
        )
    if "new_followers" in df.columns and not df["new_followers"].isna().all():
        fig.add_trace(
            go.Scatter(
                x=months,
                y=df["new_followers"],
                name="New followers",
                mode="lines+markers",
                line=dict(color=COLORS["new_followers"], width=3),
                marker=dict(size=6),
                connectgaps=False,
            ),
            secondary_y=True,
        )
    _apply_layout(fig, title=title)
    fig.update_yaxes(
        title_text="Interactions",
        secondary_y=False,
        showgrid=True,
        gridcolor="#E6EEF5",
        tickformat=",",
    )
    fig.update_yaxes(
        title_text="New followers",
        secondary_y=True,
        showgrid=False,
        tickformat=",",
    )
    return fig


def _platform_section(
    df: pd.DataFrame,
    *,
    platform: str,
    caption: str,
    top_views: pd.DataFrame,
    paid_excluded: int,
    scanned: int,
    with_views: int,
) -> None:
    st.subheader(f"{platform} — Five Journeys")
    st.caption(caption)
    st.plotly_chart(
        _reach_figure(
            df, title=f"{platform} organic — views, reach, followers"
        ),
        use_container_width=True,
    )
    _render_top_views_table(
        top_views,
        platform=platform,
        excluded=paid_excluded,
        scanned=scanned,
        with_views=with_views,
    )
    st.plotly_chart(
        _engagement_figure(
            df,
            title=f"{platform} organic — interactions & new followers",
        ),
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Meta Organic Trends",
        page_icon="📈",
        layout="wide",
    )
    _inject_styles()

    st.title("Meta organic trends")
    st.caption(
        "Five Journeys Facebook and Instagram — monthly tracker history "
        "(2023–present): reach metrics and engagement metrics."
    )
    st.link_button(
        "← Back to Campaign Breakdown",
        CAMPAIGN_BREAKDOWN_URL,
        type="secondary",
    )

    with st.spinner("Loading Monthly Tracker history…"):
        try:
            df = _cached_trends()
        except Exception as exc:
            st.error(f"Could not load tracker sheets.\n\n{exc}")
            st.stop()

    if df.empty:
        st.warning("No Meta organic monthly rows found in the tracker sheets.")
        st.stop()

    if st.button("Refresh data"):
        _cached_trends.clear()
        _cached_top_views.clear()
        st.rerun()

    with st.spinner("Loading all-time top organic posts by views…"):
        try:
            top_bundle = _cached_top_views()
        except Exception as exc:
            st.warning(f"Could not load top posts by views.\n\n{exc}")
            top_bundle = {
                "facebook": pd.DataFrame(),
                "instagram": pd.DataFrame(),
                "meta": {},
            }

    top_meta = top_bundle.get("meta") if isinstance(top_bundle.get("meta"), dict) else {}
    fb_top = top_bundle.get("facebook")
    ig_top = top_bundle.get("instagram")
    if not isinstance(fb_top, pd.DataFrame):
        fb_top = pd.DataFrame()
    if not isinstance(ig_top, pd.DataFrame):
        ig_top = pd.DataFrame()
    fb = platform_frame(df, "Facebook")
    ig = platform_frame(df, "Instagram")

    _platform_section(
        fb,
        platform="Facebook",
        caption=(
            "Reach uses tracker “People Reached” / “Viewers”. "
            "Views begin in 2025 (not a separate row in 2023–2024)."
        ),
        top_views=fb_top,
        paid_excluded=int(top_meta.get("fb_paid_excluded") or 0),
        scanned=int(top_meta.get("fb_scanned") or 0),
        with_views=int(top_meta.get("fb_with_views") or 0),
    )
    _platform_section(
        ig,
        platform="Instagram",
        caption="Reach is monthly account reach; views are impressions/views from the tracker.",
        top_views=ig_top,
        paid_excluded=int(top_meta.get("ig_paid_excluded") or 0),
        scanned=int(top_meta.get("ig_scanned") or 0),
        with_views=int(top_meta.get("ig_with_views") or 0),
    )

    with st.expander("Data table"):
        show = df.copy()
        show["month"] = show["month"].dt.strftime("%Y-%m")
        st.dataframe(show, use_container_width=True, hide_index=True)

    st.caption(
        "Source: Digital Cross-Channel Tracker → Monthly Tracker "
        "(2023 sheet + 2024–2026 trackers). Total followers are end-of-month counts; "
        "other series are monthly totals."
    )


if __name__ == "__main__":
    main()
