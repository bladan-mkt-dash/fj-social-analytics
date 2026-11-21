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
from datetime import date
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
from meta_organic_top_views import _preview, fetch_top_organic_by_views
from meta_organic_year_figures import load_year_figures
from organic_hashtags import MIN_USES, hashtag_cloud_figure, hashtag_cloud_table

COLORS = {
    "accent_dark": "#264540",
    "page_bg": "#F4F8FB",
    "views": "#4C78A8",
    "reach": "#F58518",
    "followers": "#54A24B",
    "interactions": "#82A1C2",
    "link_clicks": "#B279A2",
    "visits": "#72B7B2",
    "new_followers": "#54A24B",
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


@st.cache_data(ttl=300, show_spinner=False)
def _cached_posts_catalog() -> pd.DataFrame:
    try:
        _arch = _ROOT / "Data & Architecture"
        if str(_arch) not in sys.path:
            sys.path.insert(0, str(_arch))
        from drawer_a_read import organic_posts_catalog

        frame = organic_posts_catalog()
        if frame is not None and not frame.empty:
            return frame
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_trends() -> pd.DataFrame:
    return load_meta_organic_trends()


@st.cache_data(ttl=3600, show_spinner="Loading all-time top organic posts…")
def _cached_top_views(top_n: int = 5, max_scan: int = 500) -> dict:
    try:
        _arch = _ROOT / "Data & Architecture"
        if str(_arch) not in sys.path:
            sys.path.insert(0, str(_arch))
        from drawer_a_read import organic_top_posts_from_notebook

        bundle = organic_top_posts_from_notebook()
        if bundle and (
            (isinstance(bundle.get("facebook"), pd.DataFrame) and not bundle["facebook"].empty)
            or (isinstance(bundle.get("instagram"), pd.DataFrame) and not bundle["instagram"].empty)
        ):
            return bundle
    except Exception:
        pass
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
    if "Preview" in show.columns:
        show["Preview"] = show["Preview"].map(lambda v: _preview(str(v or "")))
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("URL"),
            "Preview": st.column_config.TextColumn(width="large"),
        },
    )


def _chart_month_ends(df: pd.DataFrame) -> pd.Series:
    """Place each monthly total on the last calendar day of that month."""
    return pd.to_datetime(df["month"]) + pd.offsets.MonthEnd(0)


def _apply_layout(
    fig: go.Figure,
    *,
    title: str,
    since: date | None = None,
    until: date | None = None,
) -> go.Figure:
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
    fig.update_xaxes(
        title_text="Month",
        showgrid=True,
        gridcolor="#E6EEF5",
        tickformat="%b %Y",
        hoverformat="%b %Y",
    )
    if since is not None and until is not None:
        fig.update_xaxes(range=[pd.Timestamp(since), pd.Timestamp(until)])
    return fig


def _reach_figure(
    df: pd.DataFrame,
    *,
    title: str,
    since: date | None = None,
    until: date | None = None,
) -> go.Figure:
    """Dual-axis: views + reach (left), total followers (right)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.update_layout(title=title)
        return fig

    months = _chart_month_ends(df)
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
    _apply_layout(fig, title=title, since=since, until=until)
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


def _engagement_figure(
    df: pd.DataFrame,
    *,
    title: str,
    since: date | None = None,
    until: date | None = None,
) -> go.Figure:
    """Dual-axis: interactions (left), new followers (right)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if df.empty:
        fig.update_layout(title=title)
        return fig

    months = _chart_month_ends(df)
    if "interactions" in df.columns and not df["interactions"].isna().all():
        fig.add_trace(
            go.Scatter(
                x=months,
                y=df["interactions"],
                name="Interactions",
                mode="lines+markers",
                line=dict(color=COLORS["interactions"], width=2.5),
                marker=dict(size=5, color=COLORS["interactions"]),
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
                marker=dict(size=6, color=COLORS["new_followers"]),
                connectgaps=False,
            ),
            secondary_y=True,
        )
    _apply_layout(fig, title=title, since=since, until=until)
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


def _history_bounds(df: pd.DataFrame) -> tuple[date, date]:
    months = pd.to_datetime(df["month"])
    start = months.min().to_period("M").to_timestamp().date()
    end = (months.max().to_period("M").to_timestamp() + pd.offsets.MonthEnd(0)).date()
    return start, end


def _filter_chart_months(df: pd.DataFrame, since: date, until: date) -> pd.DataFrame:
    """Keep months that overlap the inclusive calendar range."""
    if df.empty:
        return df
    starts = pd.to_datetime(df["month"]).dt.to_period("M").dt.to_timestamp()
    ends = starts + pd.offsets.MonthEnd(0)
    mask = (starts.dt.date <= until) & (ends.dt.date >= since)
    return df.loc[mask].copy()


def _render_chart_date_filter(df: pd.DataFrame) -> tuple[date, date]:
    hist_min, hist_max = _history_bounds(df)
    if "meta_organic_chart_since" not in st.session_state:
        st.session_state.meta_organic_chart_since = hist_min
    if "meta_organic_chart_until" not in st.session_state:
        st.session_state.meta_organic_chart_until = hist_max
    st.markdown("**Chart date range**")
    st.caption(
        "Zooms the Facebook and Instagram line charts. "
        "Top 5 posts and hashtag clouds stay all-time and are not affected."
    )
    start_col, end_col = st.columns(2)
    with start_col:
        since = st.date_input(
            "Start date",
            min_value=hist_min,
            max_value=hist_max,
            key="meta_organic_chart_since",
        )
    with end_col:
        until = st.date_input(
            "End date",
            min_value=hist_min,
            max_value=hist_max,
            key="meta_organic_chart_until",
        )
    return since, until


def _render_hashtag_cloud(stats: pd.DataFrame, *, platform: str) -> None:
    st.markdown(f"**{platform} hashtag cloud**")
    st.caption(
        "Top 30 hashtags by average views on organic posts that used the tag "
        f"(boosted excluded; used on at least {MIN_USES} posts). "
        "Type size is that same average — tags that tended to get seen, not the ones used most. "
        "All-time — not affected by the chart date range."
    )
    if stats is None or stats.empty:
        st.info(f"No hashtags found in organic {platform} captions.")
        return
    st.plotly_chart(
        hashtag_cloud_figure(stats, platform=platform),
        use_container_width=True,
    )


def _platform_section(
    df: pd.DataFrame,
    *,
    platform: str,
    caption: str,
    top_views: pd.DataFrame,
    paid_excluded: int,
    scanned: int,
    with_views: int,
    hashtags: pd.DataFrame,
    since: date,
    until: date,
) -> None:
    st.subheader(f"{platform} — Five Journeys")
    st.caption(caption)
    if df.empty:
        st.info(f"No {platform} monthly rows in this chart date range.")
    else:
        st.plotly_chart(
            _reach_figure(
                df,
                title=f"{platform} organic — views, reach, followers",
                since=since,
                until=until,
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
    if not df.empty:
        st.plotly_chart(
            _engagement_figure(
                df,
                title=f"{platform} organic — interactions & new followers",
                since=since,
                until=until,
            ),
            use_container_width=True,
        )
    _render_hashtag_cloud(hashtags, platform=platform)


def _fmt_count(value: object) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,}"


def _fmt_growth(value: object) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,}"


def _render_organic_year_figures() -> None:
    st.subheader("Organic performance, separate from ads")
    st.markdown(
        "Figures for **2024**, **2025**, and **2026 year to date** "
        "(January 1 through November 17). "
        "These leave out ad activity. Meta’s Reach total includes ads, "
        "and Meta no longer provides a unique organic reach number, "
        "so the organic total is **views that did not come from ads**."
    )
    payload = load_year_figures()
    if not payload:
        st.info("Organic year figures have not been saved yet.")
        return
    rows = payload.get("rows") or []
    show = []
    for item in rows:
        metric = str(item.get("metric") or "")
        fmt = _fmt_growth if metric == "Follower growth" else _fmt_count
        show.append(
            {
                "Platform": item.get("platform"),
                "Figure": metric,
                "2024": fmt(item.get("2024")),
                "2025": fmt(item.get("2025")),
                "2026 YTD": fmt(item.get("2026")),
            }
        )
    st.dataframe(pd.DataFrame(show), use_container_width=True, hide_index=True)
    for note in payload.get("footnotes") or []:
        st.caption(note)


def main(*, standalone: bool = True) -> None:
    if standalone:
        st.set_page_config(
            page_title="Meta Organic Trends",
            page_icon="📈",
            layout="wide",
        )
    _inject_styles()

    st.title("Meta organic trends")
    st.caption(
        "Five Journeys Facebook and Instagram, monthly, through November 17, 2026. "
        "The Reach and view totals in the charts include ad activity. "
        "Organic results, with ads removed, are at the bottom of the page."
    )
    if standalone:
        st.link_button(
            "← Back to Campaign Breakdown",
            CAMPAIGN_BREAKDOWN_URL,
            type="secondary",
        )

    with st.spinner("Loading Monthly Tracker history…"):
        try:
            df = _cached_trends()
        except Exception as exc:
            st.error(f"Could not load Meta organic trends.\n\n{exc}")
            st.stop()

    if df.empty:
        st.warning("No Meta organic monthly rows found in PostgreSQL or the tracker sheets.")
        st.stop()

    if st.button("Refresh data"):
        _cached_trends.clear()
        _cached_top_views.clear()
        _cached_posts_catalog.clear()
        st.rerun()

    since, until = _render_chart_date_filter(df)
    if since > until:
        st.error("Start date must be on or before end date.")
        st.stop()

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
    fb = _filter_chart_months(platform_frame(df, "Facebook"), since, until)
    ig = _filter_chart_months(platform_frame(df, "Instagram"), since, until)
    posts = _cached_posts_catalog()
    fb_tags = hashtag_cloud_table(posts, "Facebook")
    ig_tags = hashtag_cloud_table(posts, "Instagram")

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
        hashtags=fb_tags,
        since=since,
        until=until,
    )
    _platform_section(
        ig,
        platform="Instagram",
        caption="Reach is monthly account reach; views are impressions/views from the tracker.",
        top_views=ig_top,
        paid_excluded=int(top_meta.get("ig_paid_excluded") or 0),
        scanned=int(top_meta.get("ig_scanned") or 0),
        with_views=int(top_meta.get("ig_with_views") or 0),
        hashtags=ig_tags,
        since=since,
        until=until,
    )

    with st.expander("Data table"):
        show = df.copy()
        show["month"] = show["month"].dt.strftime("%Y-%m")
        st.caption("Full monthly history. Chart date range does not filter this table.")
        st.dataframe(show, use_container_width=True, hide_index=True)

    _render_organic_year_figures()

    st.caption(
        "Monthly charts: PostgreSQL Drawer A (nightly from the Digital Cross-Channel "
        "Tracker, 2023–2026) and the Meta Graph API. "
        "Total followers are end-of-month counts; other series are monthly totals. "
        "Those Reach and view totals include ad activity. "
        "The organic table above removes ads and runs through November 17, 2026."
    )


if __name__ == "__main__":
    main()
