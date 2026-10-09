"""CommerceLens Streamlit dashboard (Material 3-inspired UI).

Reads ONLY the pre-aggregated parquet files in dashboard/data/ (built by
scripts/build_dashboard_data.py), so it deploys to Streamlit Community Cloud
without the raw CSVs. Every number shown is computed from those files.

Run locally:  streamlit run dashboard/app.py
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent / "data"

# Chart palette (fixed categorical order) and Material surface tokens.
BLUE, ORANGE, AQUA, YELLOW, RED = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e34948"
BLUE_LIGHT, BLUE_DARK = "#b7d3f6", "#0d366b"
GREY, INK, INK2, OUTLINE = "#9aa3ae", "#1b1f24", "#5b6573", "#e3e7ee"

st.set_page_config(page_title="CommerceLens", page_icon=":material/insights:", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- styling
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..600,0..1,0&display=block');
:root { --p:#2a78d6; --p-cont:#dbe8fb; --on-p-cont:#0d366b; --t:#eb6834; --t-cont:#fde7de; --on-t-cont:#8a2c0a;
        --ok:#138a5e; --ok-cont:#d9f3e9; --surface:#ffffff; --bg:#f4f6fb; --outline:#e3e7ee;
        --ink:#1b1f24; --ink2:#5b6573; --ink3:#8a93a0;
        --shadow:0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.06);
        --shadow-hi:0 2px 6px rgba(16,24,40,.06), 0 16px 36px rgba(16,24,40,.12); }
html, body, .stApp, .stMarkdown, p, li, label, h1, h2, h3, h4, h5, input, textarea { font-family:'Roboto','Segoe UI',sans-serif !important; }
.material-symbols-rounded { font-family:'Material Symbols Rounded' !important; font-weight:normal; font-style:normal; line-height:1;
        letter-spacing:normal; text-transform:none; display:inline-block; white-space:nowrap; -webkit-font-smoothing:antialiased;
        font-feature-settings:'liga'; font-variation-settings:'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 24; }
.block-container { padding-top:1.6rem; padding-bottom:3rem; max-width:1440px; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stSidebar"] { background:var(--surface); border-right:1px solid var(--outline); }

/* sidebar: brand + navigation rail */
.brand { display:flex; align-items:center; gap:.7rem; margin:.1rem 0 1.1rem; }
.brand-logo { width:42px; height:42px; border-radius:14px; display:grid; place-items:center; color:#fff; font-size:24px;
        background:linear-gradient(135deg,#1c5cab,#2a78d6 55%,#5598e7); box-shadow:0 8px 18px rgba(42,120,214,.35); }
.brand-name { font-weight:700; font-size:1.15rem; color:var(--ink); line-height:1.1; }
.brand-tag { font-size:.74rem; color:var(--ink2); }
.nav-label { font-size:.7rem; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--ink3); margin:.3rem 0 .4rem .2rem; }
[data-testid="stSidebar"] div[role="radiogroup"] { gap:2px; }
[data-testid="stSidebar"] label[data-baseweb="radio"] { width:100%; padding:.55rem .85rem; border-radius:999px; margin:0; transition:background .15s ease; }
[data-testid="stSidebar"] label[data-baseweb="radio"] > div:first-child { display:none; }
[data-testid="stSidebar"] label[data-baseweb="radio"]:hover { background:var(--bg); }
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) { background:var(--p-cont); }
[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) p { color:var(--on-p-cont); font-weight:600; }

/* hero */
.hero { position:relative; overflow:hidden; border-radius:28px; padding:30px 34px 26px; color:#fff; margin-bottom:1.1rem;
        background:radial-gradient(circle at 88% 12%, rgba(255,255,255,.22), transparent 38%),
                   radial-gradient(circle at 70% 120%, rgba(27,175,122,.35), transparent 45%),
                   linear-gradient(120deg,#0d366b 0%,#1c5cab 45%,#2a78d6 78%,#5598e7 100%);
        box-shadow:0 18px 40px rgba(13,54,107,.28); animation:rise .5s ease both; }
.hero h1 { color:#fff; font-size:2.5rem; font-weight:700; margin:.1rem 0 0; padding:0; letter-spacing:-.02em; }
.hero-eyebrow { text-transform:uppercase; letter-spacing:.16em; font-size:.72rem; opacity:.85; font-weight:500; }
.hero-sub { font-size:1.08rem; opacity:.96; margin:.1rem 0 .7rem; font-weight:500; }
.hero-q { max-width:860px; opacity:.9; font-size:.95rem; line-height:1.55; margin:0 0 1rem; }
.chips { display:flex; flex-wrap:wrap; gap:8px; }
.chip { background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.3); padding:6px 12px; border-radius:999px;
        font-size:.8rem; display:inline-flex; gap:6px; align-items:center; backdrop-filter:blur(6px); }
.chip .material-symbols-rounded { font-size:16px; }

/* page header */
.page-head { display:flex; align-items:center; gap:14px; margin:.1rem 0 1.1rem; animation:rise .4s ease both; }
.page-icon { width:52px; height:52px; border-radius:16px; display:grid; place-items:center; color:#fff; font-size:28px;
        background:linear-gradient(135deg,#1c5cab,#2a78d6 60%,#5598e7); box-shadow:0 10px 22px rgba(42,120,214,.3); }
.page-head h2 { margin:0; padding:0; font-size:1.6rem; font-weight:700; color:var(--ink); }
.page-head p { margin:.15rem 0 0; color:var(--ink2); font-size:.92rem; }

/* KPI cards */
.kpi-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:16px; margin:.2rem 0 1.2rem; }
@media (max-width:1100px) { .kpi-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
@media (max-width:560px) { .kpi-grid { grid-template-columns:1fr; } }
.kpi { position:relative; overflow:hidden; background:var(--surface); border:1px solid var(--outline); border-radius:22px;
       padding:16px 18px 14px; box-shadow:var(--shadow); transition:transform .18s ease, box-shadow .18s ease; animation:rise .5s ease both; }
.kpi:hover { transform:translateY(-4px); box-shadow:var(--shadow-hi); }
.kpi::after { content:""; position:absolute; right:-36px; bottom:-48px; width:130px; height:130px; border-radius:50%;
       background:var(--p-cont); opacity:.45; }
.kpi-orange::after { background:var(--t-cont); } .kpi-green::after { background:var(--ok-cont); }
.kpi-top { display:flex; align-items:center; gap:10px; position:relative; z-index:1; }
.kpi-icon { width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:22px; background:var(--p-cont); color:var(--p); }
.kpi-orange .kpi-icon { background:var(--t-cont); color:var(--t); } .kpi-green .kpi-icon { background:var(--ok-cont); color:var(--ok); }
.kpi-label { font-size:.82rem; color:var(--ink2); font-weight:500; }
.kpi-value { font-size:1.75rem; font-weight:700; color:var(--ink); margin:.55rem 0 .1rem; letter-spacing:-.015em; position:relative; z-index:1; }
.kpi-bottom { display:flex; flex-direction:column; gap:6px; position:relative; z-index:1; }
.kpi-sub { font-size:.78rem; color:var(--ink2); line-height:1.3; }
.spark { width:100%; height:34px; display:block; }

/* cards (keyed containers) */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card"]),
div[data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-card"]) {
       background:var(--surface); border:1px solid var(--outline) !important; border-radius:22px !important;
       box-shadow:var(--shadow); transition:box-shadow .2s ease; padding:.35rem .5rem .2rem; }
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card"]):hover,
div[data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-card"]):hover { box-shadow:var(--shadow-hi); }
.card-title { display:flex; align-items:center; gap:8px; font-weight:600; font-size:1.02rem; color:var(--ink); }
.card-title .material-symbols-rounded { color:var(--p); font-size:21px; }
.card-sub { color:var(--ink2); font-size:.83rem; margin:.15rem 0 .2rem; }

/* insight + stat tiles */
.insight { background:var(--surface); border:1px solid var(--outline); border-radius:20px; padding:16px 18px; height:100%;
           box-shadow:var(--shadow); border-top:4px solid var(--p); transition:transform .18s ease, box-shadow .18s ease; }
.insight:hover { transform:translateY(-3px); box-shadow:var(--shadow-hi); }
.insight.orange { border-top-color:var(--t); } .insight.green { border-top-color:var(--ok); }
.insight-head { display:flex; align-items:center; gap:8px; font-weight:600; color:var(--ink); margin-bottom:.35rem; }
.insight-head .material-symbols-rounded { font-size:20px; color:var(--p); }
.insight.orange .insight-head .material-symbols-rounded { color:var(--t); } .insight.green .insight-head .material-symbols-rounded { color:var(--ok); }
.insight-big { font-size:1.55rem; font-weight:700; color:var(--ink); }
.insight p { margin:.2rem 0 0; color:var(--ink2); font-size:.86rem; line-height:1.45; }
.stat-grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px; margin:.4rem 0 .6rem; }
.stat { background:var(--bg); border-radius:14px; padding:10px 12px; }
.stat-label { font-size:.74rem; color:var(--ink2); }
.stat-value { font-size:1.2rem; font-weight:700; color:var(--ink); }
.stat-note { font-size:.72rem; color:var(--ink3); }
.stat.bad .stat-value { color:#c2410c; } .stat.good .stat-value { color:var(--ok); }
.big-stat { font-size:2.2rem; font-weight:700; color:var(--p); letter-spacing:-.02em; line-height:1.1; }
.big-stat.orange { color:var(--t); } .big-stat.green { color:var(--ok); }
.big-label { color:var(--ink2); font-size:.82rem; }
/* What-if row: top-align the four blocks and reserve equal caption height so the numbers share a baseline */
.st-key-card_sim [data-testid="stHorizontalBlock"] { align-items:flex-start; }
.st-key-card_sim .big-label { min-height:2.6em; }
.pill-tag { display:inline-flex; align-items:center; gap:6px; background:var(--p-cont); color:var(--on-p-cont); border-radius:999px;
            padding:4px 10px; font-size:.76rem; font-weight:500; }

/* findings */
.finding { background:var(--surface); border:1px solid var(--outline); border-radius:22px; padding:18px 20px; box-shadow:var(--shadow);
           height:100%; transition:transform .18s ease, box-shadow .18s ease; }
.finding:hover { transform:translateY(-3px); box-shadow:var(--shadow-hi); }
.finding-top { display:flex; align-items:center; gap:10px; margin-bottom:.5rem; }
.finding-num { width:34px; height:34px; border-radius:11px; display:grid; place-items:center; font-weight:700; color:#fff;
               background:linear-gradient(135deg,#1c5cab,#2a78d6); flex:none; }
.finding h4 { margin:0; padding:0; font-size:1.02rem; color:var(--ink); }
.finding .problem { color:var(--ink3); font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; margin:.1rem 0 .4rem; }
.finding .body { color:var(--ink); font-size:.9rem; line-height:1.5; }
.finding .so-what { background:var(--bg); border-radius:12px; padding:9px 12px; margin:.6rem 0 .5rem; font-size:.86rem; color:var(--ink2); }
.finding .action { background:var(--p-cont); color:var(--on-p-cont); border-radius:12px; padding:9px 12px; font-size:.86rem;
                   display:flex; gap:8px; align-items:flex-start; }
.finding .action .material-symbols-rounded { font-size:18px; margin-top:1px; }

[data-testid="stExpander"] details { border-radius:18px; border:1px solid var(--outline); background:var(--surface); }
@keyframes rise { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:none; } }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

pio.templates["material"] = go.layout.Template(layout=go.Layout(
    font=dict(family="Roboto, Segoe UI, sans-serif", size=13, color=INK),
    title=dict(font=dict(size=15, color=INK), x=0, xanchor="left"),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    colorway=[BLUE, ORANGE, AQUA, YELLOW, "#e87ba4", "#008300", "#4a3aa7", RED],
    xaxis=dict(gridcolor="#eef1f5", linecolor=OUTLINE, zeroline=False, automargin=True),
    yaxis=dict(gridcolor="#eef1f5", linecolor=OUTLINE, zeroline=False, automargin=True),
    hoverlabel=dict(bgcolor="white", bordercolor=OUTLINE, font=dict(family="Roboto, sans-serif", size=13, color=INK)),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=8, r=12, t=36, b=8),
    barcornerradius=5,
    bargap=0.3,
))
pio.templates.default = "material"
PLURAL = {"Category": "categories", "Seller": "sellers", "State": "states"}
PLOTLY_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


# ---------------------------------------------------------------- helpers
@st.cache_data
def load() -> dict[str, pd.DataFrame]:
    """Load every parquet file in dashboard/data into a dict keyed by file stem."""
    return {p.stem: pd.read_parquet(p) for p in sorted(DATA_DIR.glob("*.parquet"))}


def html(markup: str) -> None:
    """Render raw HTML (kept on one line so Markdown never treats it as a code block)."""
    st.markdown(markup, unsafe_allow_html=True)


def icon(name: str) -> str:
    return f'<span class="material-symbols-rounded">{name}</span>'


def card(key: str):
    """A Material 'elevated card': Streamlit's bordered container, restyled via its st-key-card_* class."""
    return st.container(border=True, key=f"card_{key}")


def card_title(icon_name: str, title: str, sub: str = "") -> None:
    html(f'<div class="card-title">{icon(icon_name)}{title}</div>' + (f'<div class="card-sub">{sub}</div>' if sub else ""))


def page_head(icon_name: str, title: str, sub: str) -> None:
    html(f'<div class="page-head"><div class="page-icon">{icon(icon_name)}</div><div><h2>{title}</h2><p>{sub}</p></div></div>')


def chart(fig: go.Figure, height: int, key: str | None = None, select: bool = False):
    """Render a Plotly figure with the Material template; optionally return click selections."""
    fig.update_layout(template="material", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return st.plotly_chart(fig, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key,
                           on_select="rerun" if select else "ignore", selection_mode="points")


def selected_points(event) -> list:
    """Points the user clicked in a selectable chart (empty list if none)."""
    try:
        return list(event.selection.points)
    except AttributeError:
        return []


def sparkline(values, color: str, width: int = 200, height: int = 34) -> str:
    """Tiny inline SVG trend line with a soft area fill."""
    v = np.asarray(pd.Series(values).dropna(), dtype=float)
    if len(v) < 2:
        return ""
    lo, hi = v.min(), v.max()
    span = (hi - lo) or 1.0
    xs = np.linspace(2, width - 3, len(v))
    ys = height - 4 - (v - lo) / span * (height - 10)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"2,{height} {pts} {width - 3},{height}"
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="{color}" fill-opacity="0.13"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="3" fill="{color}"/></svg>')


def kpi(icon_name: str, label: str, value: str, sub: str = "", spark: str = "", tone: str = "blue") -> str:
    return (f'<div class="kpi kpi-{tone}"><div class="kpi-top"><span class="kpi-icon material-symbols-rounded">{icon_name}</span>'
            f'<span class="kpi-label">{label}</span></div><div class="kpi-value">{value}</div>'
            f'<div class="kpi-bottom"><span class="kpi-sub">{sub}</span>{spark}</div></div>')


def stat_grid(items: list[tuple]) -> str:
    """items: (label, value, note, tone) with tone in {'', 'good', 'bad'}."""
    cells = "".join(f'<div class="stat {tone}"><div class="stat-label">{label}</div><div class="stat-value">{value}</div>'
                    f'<div class="stat-note">{note}</div></div>' for label, value, note, tone in items)
    return f'<div class="stat-grid">{cells}</div>'


def brl(x: float) -> str:
    """Format Brazilian reais compactly."""
    if abs(x) >= 1e6:
        return f"R${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"R${x / 1e3:,.1f}k"
    return f"R${x:,.0f}"


def two_prop_p(x1: float, n1: float, x2: float, n2: float) -> float:
    """Two-sided p-value of a two-proportion z-test (same test as notebook 02)."""
    p = (x1 + x2) / (n1 + n2)
    z = (x1 / n1 - x2 / n2) / math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return math.erfc(abs(z) / math.sqrt(2))


def seg(label: str, options: list, default, key: str, fmt=None):
    """Segmented control that never returns None (re-selecting the active option keeps it)."""
    value = st.segmented_control(label, options, default=default, key=key, format_func=fmt,
                                 label_visibility="collapsed")
    return value if value is not None else default


# ---------------------------------------------------------------- data + shared numbers
d = load()
k = d["kpis"].iloc[0]
lv = d["late_vs_ontime"].set_index("delivery")
late, ontime = lv.loc["Late"], lv.loc["On time or early"]
n_low_late = late.orders * late.pct_low_review / 100
n_low_ontime = ontime.orders * ontime.pct_low_review / 100
overall_low = 100 * (n_low_late + n_low_ontime) / (late.orders + ontime.orders)
freq = d["order_frequency"]
one_time = freq.loc[freq["orders_per_customer"] == "1", "pct_of_customers"].iloc[0]
so = d["state_ops"].merge(d["revenue_by_state"][["customer_state", "customers", "avg_order_value", "pct_of_revenue"]],
                          on="customer_state", how="left")
national_late = float(k.late_delivery_pct)
# Default spotlight: the highest-revenue state whose late rate is above the national rate.
default_spot = so[so["late_pct"] > national_late].sort_values("revenue", ascending=False)["customer_state"].iloc[0]

PAGES = {
    "overview": ":material/space_dashboard: Overview",
    "revenue": ":material/payments: Revenue",
    "customers": ":material/groups: Customers & RFM",
    "drivers": ":material/local_shipping: Satisfaction drivers",
    "model": ":material/model_training: Risk model",
    "findings": ":material/lightbulb: Findings",
}

with st.sidebar:
    html(f'<div class="brand"><div class="brand-logo">{icon("insights")}</div>'
         f'<div><div class="brand-name">CommerceLens</div><div class="brand-tag">Revenue &amp; Retention Analytics</div></div></div>')
    html('<div class="nav-label">Navigate</div>')
    # Deep links: ?page=model opens that page directly, and the URL follows navigation.
    start = st.query_params.get("page", "overview")
    page = st.radio("Navigate", list(PAGES), format_func=PAGES.get, label_visibility="collapsed",
                    index=list(PAGES).index(start) if start in PAGES else 0)
    st.query_params["page"] = page
    st.divider()
    html('<div class="nav-label">Controls</div>')
    states_by_rev = so.sort_values("revenue", ascending=False)["customer_state"].tolist()
    spotlight = st.selectbox(":material/location_on: Spotlight a state", states_by_rev,
                             index=states_by_rev.index(default_spot),
                             help="Highlighted in orange on every state chart.")
    hide_edges = st.toggle(":material/filter_alt: Exclude sparse edge months", value=True,
                           help="Months with < 500 delivered orders (late 2016, end of 2018).")
    st.divider()
    st.caption(f"Olist Brazilian E-Commerce · {pd.Timestamp(k.first_order_date):%b %Y} – "
               f"{pd.Timestamp(k.last_order_date):%b %Y} · Revenue = item price on delivered orders · "
               "Customers = customer_unique_id")

monthly = d["monthly_trend"]
ops = d["monthly_ops"]
if hide_edges:
    monthly = monthly[~monthly["is_partial_edge"]]
    ops = ops[~ops["is_partial_edge"]]
months = pd.to_datetime(monthly["month"])


# ---------------------------------------------------------------- pages
def page_overview() -> None:
    html(
        '<div class="hero"><div class="hero-eyebrow">E-commerce analytics · Olist Brazil</div>'
        '<h1>CommerceLens</h1><div class="hero-sub">CommerceLens — E-Commerce Revenue &amp; Retention Analytics</div>'
        '<p class="hero-q">Where is revenue concentrated, and which operational factors — delivery time, freight cost, '
        'product category, region — drive customer satisfaction and repeat purchases?</p><div class="chips">'
        f'<span class="chip">{icon("receipt_long")}{k.delivered_orders:,.0f} delivered orders</span>'
        f'<span class="chip">{icon("calendar_month")}{pd.Timestamp(k.first_order_date):%b %Y} – {pd.Timestamp(k.last_order_date):%b %Y}</span>'
        f'<span class="chip">{icon("groups")}{k.customers:,.0f} customers</span>'
        f'<span class="chip">{icon("database")}DuckDB SQL · LightGBM · SHAP</span></div></div>'
    )

    full = d["monthly_trend"][~d["monthly_trend"]["is_partial_edge"]]
    fm = pd.to_datetime(full["month"])
    jan_aug = lambda y: full[(fm.dt.year == y) & (fm.dt.month <= 8)]["revenue"].sum()  # noqa: E731
    growth = 100 * (jan_aug(2018) / jan_aug(2017) - 1)
    delivered_pct = d["funnel"].set_index("stage").loc["Delivered to customer", "pct_of_purchased"]
    peak_late = ops.loc[ops["late_pct"].idxmax()]
    peak_low = ops.loc[ops["pct_low_review"].idxmax()]
    cards = [
        kpi("payments", "Revenue", brl(k.revenue), f"+{growth:.0f}% Jan–Aug 2018 vs 2017", sparkline(monthly["revenue"], BLUE)),
        kpi("receipt_long", "Delivered orders", f"{k.delivered_orders:,.0f}", f"{delivered_pct:.1f}% of purchases delivered",
            sparkline(monthly["orders"], BLUE)),
        kpi("shopping_bag", "Avg order value", f"R${k.avg_order_value:,.2f}",
            f"R${monthly['avg_order_value'].min():,.0f}–R${monthly['avg_order_value'].max():,.0f} by month",
            sparkline(monthly["avg_order_value"], BLUE)),
        kpi("groups", "Customers", f"{k.customers:,.0f}", f"{one_time:.1f}% bought only once", tone="green"),
        kpi("repeat", "Repeat customers", f"{k.repeat_customer_pct:.1f}%", "2+ delivered orders", tone="green"),
        kpi("star", "Avg review", f"{k.avg_review_score:.2f} / 5", "delivered orders", sparkline(ops["avg_review"], AQUA), tone="green"),
        kpi("schedule", "Late deliveries", f"{k.late_delivery_pct:.1f}%",
            f"peak {peak_late.late_pct:.1f}% ({pd.Timestamp(peak_late.month):%b %Y})", sparkline(ops["late_pct"], ORANGE), tone="orange"),
        kpi("sentiment_dissatisfied", "1-2★ reviews", f"{overall_low:.1f}%",
            f"peak {peak_low.pct_low_review:.1f}% ({pd.Timestamp(peak_low.month):%b %Y})", sparkline(ops["pct_low_review"], ORANGE),
            tone="orange"),
    ]
    html('<div class="kpi-grid">' + "".join(cards) + "</div>")

    so_i = so.set_index("customer_state")
    rj, sp = so_i.loc[default_spot], so_i.loc["SP"]
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="insight orange"><div class="insight-head">{icon("bolt")}Late delivery drives bad reviews</div>'
                f'<div class="insight-big">{late.pct_low_review:.0f}% vs {ontime.pct_low_review:.0f}%</div>'
                f'<p>of late vs on-time orders get a 1-2★ review — {late.pct_low_review / ontime.pct_low_review:.1f}x the rate.</p></div>',
                unsafe_allow_html=True)
    c2.markdown(f'<div class="insight"><div class="insight-head">{icon("map")}Lateness is regional</div>'
                f'<div class="insight-big">{default_spot} {rj.late_pct:.1f}% late</div>'
                f'<p>vs {sp.late_pct:.1f}% in SP — {default_spot} carries {rj.pct_of_revenue:.1f}% of revenue.</p></div>',
                unsafe_allow_html=True)
    c3.markdown(f'<div class="insight green"><div class="insight-head">{icon("loyalty")}Retention is structural</div>'
                f'<div class="insight-big">{one_time:.1f}% one-time</div>'
                f'<p>of customers never order again; first-order experience barely moves it.</p></div>',
                unsafe_allow_html=True)
    st.write("")

    c1, c2 = st.columns([2, 3])
    with c1, card("funnel"):
        card_title("filter_alt", "Order fulfilment funnel", "Built from lifecycle timestamps, not just final status")
        f = d["funnel"]
        fig = go.Figure(go.Funnel(
            y=f["stage"], x=f["orders"], texttemplate="%{value:,}<br>%{percentInitial:.1%}",
            marker=dict(color=[BLUE_DARK, "#1c5cab", "#256abf", BLUE]), connector=dict(fillcolor="#eef3fb"),
            hovertemplate="%{y}<br>%{x:,} orders<br>%{percentInitial:.1%} of purchased<extra></extra>",
        ))
        fig.update_layout(margin=dict(l=8, r=8, t=8, b=8))
        chart(fig, 330)
    with c2, card("ops"):
        card_title("monitoring", "Operations health by month", "Spikes in lateness line up with spikes in bad reviews")
        metric = seg("Metric", ["late_pct", "pct_low_review", "avg_delivery_days", "avg_review"], "late_pct", "ops_metric",
                     fmt={"late_pct": "Late %", "pct_low_review": "1-2★ %", "avg_delivery_days": "Delivery days",
                          "avg_review": "Avg review"}.get)
        color = ORANGE if metric in ("late_pct", "pct_low_review") else BLUE
        m = pd.to_datetime(ops["month"])
        fig = go.Figure(go.Scatter(x=m, y=ops[metric], mode="lines+markers", line=dict(color=color, width=2.5, shape="spline"),
                                   marker=dict(size=7, color=color, line=dict(color="white", width=1.5)),
                                   fill="tozeroy", fillcolor="rgba(235,104,52,0.08)" if color == ORANGE else "rgba(42,120,214,0.08)",
                                   customdata=ops["orders"], hovertemplate="%{x|%b %Y}<br>%{y:.2f}<br>%{customdata:,} orders<extra></extra>"))
        top = ops.loc[ops[metric].idxmax() if metric != "avg_review" else ops[metric].idxmin()]
        fig.add_annotation(x=pd.Timestamp(top.month), y=top[metric], text=f"{'low' if metric == 'avg_review' else 'peak'} "
                           f"{pd.Timestamp(top.month):%b %Y}", showarrow=True, arrowhead=0, ay=-32, bgcolor="white",
                           bordercolor=OUTLINE, borderpad=4, font=dict(size=12))
        lo_y = ops[metric].min() * 0.9 if metric == "avg_review" else 0
        fig.update_yaxes(range=[lo_y, ops[metric].max() * 1.18], ticksuffix="%" if metric in ("late_pct", "pct_low_review") else "")
        fig.update_layout(margin=dict(l=8, r=8, t=16, b=8))
        chart(fig, 285)


def page_revenue() -> None:
    page_head("payments", "Revenue concentration", "Where the money is — by category, seller and region")
    with card("rev_controls"):
        c1, c2 = st.columns([2, 3])
        with c1:
            dim = seg("Break down by", ["Category", "Seller", "State"], "Category", "rev_dim",
                      fmt={"Category": ":material/category: Category", "Seller": ":material/storefront: Seller",
                           "State": ":material/map: State"}.get)
        max_n = {"Category": 30, "Seller": 50, "State": 27}[dim]
        top_n = c2.slider("Show top N", 5, max_n, min(15, max_n), key=f"topn_{dim}")

    if dim == "Category":
        df = d["pareto_category"].rename(columns={"category": "label", "cumulative_pct_of_categories": "cum_entities"})
    elif dim == "Seller":
        df = d["pareto_seller"].rename(columns={"cumulative_pct_of_sellers": "cum_entities"})
        df["label"] = "Seller #" + df["rank"].astype(str) + " (" + df["seller_state"] + ")"
    else:
        df = d["revenue_by_state"].rename(columns={"customer_state": "label"})
        df["cum_entities"] = 100 * df["rank"] / len(df)
    top = df.head(top_n)
    top_share = top["pct_of_revenue"].sum()

    c1, c2 = st.columns([3, 2])
    with c1, card("rev_bars"):
        card_title("leaderboard", f"Top {top_n} {PLURAL[dim]} by revenue",
                   f"Together {top_share:.1f}% of revenue" + (" · click a bar to inspect it" if dim != "Seller" else ""))
        t = top.iloc[::-1]
        colors = [ORANGE if (dim == "State" and lbl == spotlight) else BLUE for lbl in t["label"]]
        fig = go.Figure(go.Bar(
            x=t["revenue"], y=t["label"], orientation="h", marker_color=colors,
            text=[f"{v:.1f}%" for v in t["pct_of_revenue"]], textposition="outside", cliponaxis=False,
            customdata=np.c_[t["orders"], t["pct_of_revenue"]],
            hovertemplate="<b>%{y}</b><br>Revenue: R$%{x:,.0f}<br>Share: %{customdata[1]:.2f}%<br>Orders: %{customdata[0]:,}<extra></extra>",
        ))
        fig.update_xaxes(tickprefix="R$", showgrid=True)
        fig.update_yaxes(showgrid=False)
        fig.update_layout(margin=dict(l=8, r=40, t=8, b=8))
        event = chart(fig, max(360, 24 * top_n + 60), key=f"rev_bar_{dim}", select=dim != "Seller")
    points = selected_points(event)
    picked = points[0]["y"] if points else top.iloc[0]["label"]

    with c2, card("rev_detail"):
        if dim == "Seller":
            card_title("storefront", "Seller concentration")
            sellers = d["pareto_seller"]
            top20 = sellers.loc[sellers["cumulative_pct_of_sellers"] <= 20, "revenue"].sum() / sellers["revenue"].sum() * 100
            n80 = int((sellers["cumulative_pct"] < 80).sum() + 1)
            tiers = d["seller_tiers"].set_index("seller_tier")
            html(stat_grid([
                ("Active sellers", f"{len(sellers):,}", "delivered orders", ""),
                ("Top 20% of sellers", f"{top20:.1f}%", "of revenue", ""),
                ("Sellers covering 80%", f"{n80:,}", f"{100 * n80 / len(sellers):.1f}% of sellers", ""),
                (f"Top {top_n} sellers", f"{top_share:.1f}%", "of revenue", ""),
                ("Late rate · top 20%", f"{tiers.loc['Top 20% sellers', 'late_pct']:.1f}%", "", ""),
                ("Late rate · other 80%", f"{tiers.loc['Other 80% sellers', 'late_pct']:.1f}%", "", ""),
            ]))
            st.caption("Seller IDs are anonymised to rank + state. Lateness is similar across tiers: fix lanes, not sellers.")
        elif dim == "Category":
            card_title("category", picked.replace("_", " ").title(), "Category profile · click another bar to switch")
            row = df.set_index("label").loc[picked]
            ops_row = d["category_ops"].set_index("category")
            items = [("Revenue", brl(row.revenue), f"rank #{int(row['rank'])}", ""),
                     ("Share of revenue", f"{row.pct_of_revenue:.2f}%", f"{int(row.orders):,} orders", "")]
            if picked in ops_row.index:
                o = ops_row.loc[picked]
                items += [("1-2★ rate", f"{o.pct_low_review:.1f}%", f"overall {overall_low:.1f}%",
                           "bad" if o.pct_low_review > overall_low else "good"),
                          ("Late rate", f"{o.late_pct:.1f}%", f"overall {national_late:.1f}%",
                           "bad" if o.late_pct > national_late else "good"),
                          ("Freight / price", f"{o.freight_pct_of_price:.1f}%", f"avg item R${o.avg_item_price:,.0f}", ""),
                          ("Delivery time", f"{o.avg_delivery_days:.1f} days", f"avg review {o.avg_review:.2f}", "")]
                html(stat_grid(items))
            else:
                html(stat_grid(items))
                st.caption("Operational metrics are shown only for categories with 300+ orders.")
        else:
            card_title("location_on", f"State · {picked}", "Regional profile · click another bar to switch")
            o = so.set_index("customer_state").loc[picked]
            html(stat_grid([
                ("Revenue", brl(o.revenue), f"{o.pct_of_revenue:.1f}% of total", ""),
                ("Customers", f"{o.customers:,.0f}", f"AOV R${o.avg_order_value:,.0f}", ""),
                ("Late rate", f"{o.late_pct:.1f}%", f"national {national_late:.1f}%", "bad" if o.late_pct > national_late else "good"),
                ("1-2★ rate", f"{o.pct_low_review:.1f}%", f"overall {overall_low:.1f}%", "bad" if o.pct_low_review > overall_low else "good"),
                ("Delivery time", f"{o.avg_delivery_days:.1f} days", "purchase → delivery", ""),
                ("Freight / price", f"{o.freight_pct_of_price:.1f}%", "order level", ""),
            ]))

    c1, c2 = st.columns([2, 3])
    with c1, card("pareto"):
        card_title("stacked_line_chart", "Pareto curve", f"Top {top_n} {PLURAL[dim]} = {top_share:.1f}% of revenue")
        fig = go.Figure()
        fig.add_scatter(x=df["cum_entities"], y=df["cumulative_pct"], mode="lines", line=dict(color=BLUE, width=3, shape="spline"),
                        fill="tozeroy", fillcolor="rgba(42,120,214,0.10)", name=dim,
                        hovertemplate="Top %{x:.1f}% of " + PLURAL[dim] + " → %{y:.1f}% of revenue<extra></extra>")
        fig.add_scatter(x=[0, 100], y=[0, 100], mode="lines", line=dict(color=GREY, dash="dot", width=1), name="Even", hoverinfo="skip")
        mark = df.iloc[top_n - 1]
        fig.add_scatter(x=[mark.cum_entities], y=[mark.cumulative_pct], mode="markers", name=f"Top {top_n}",
                        marker=dict(size=14, color=ORANGE, line=dict(color="white", width=3)),
                        hovertemplate=f"Top {top_n}: %{{y:.1f}}% of revenue<extra></extra>")
        fig.add_hline(y=80, line=dict(color=GREY, width=1, dash="dash"), annotation_text="80%", annotation_position="bottom right")
        fig.update_xaxes(ticksuffix="%", range=[0, 100], title=f"% of {PLURAL[dim]} (ranked)")
        fig.update_yaxes(ticksuffix="%", range=[0, 102], title="% of revenue")
        fig.update_layout(showlegend=False, margin=dict(l=8, r=8, t=12, b=8))
        chart(fig, 360)
    with c2, card("trend"):
        card_title("trending_up", "Monthly trend", "Drag the range slider to zoom · delivered orders by purchase month")
        cc1, cc2 = st.columns([3, 2])
        with cc1:
            metric = seg("Metric", ["revenue", "orders", "avg_order_value"], "revenue", "trend_metric",
                         fmt={"revenue": "Revenue", "orders": "Orders", "avg_order_value": "Avg order value"}.get)
        smooth = cc2.toggle("3-month average", value=False, key="trend_smooth")
        y = monthly[metric]
        fig = go.Figure()
        fig.add_bar(x=months, y=y, marker_color=BLUE_LIGHT, name="Monthly",
                    hovertemplate="%{x|%b %Y}: %{y:,.0f}<extra></extra>")
        if smooth:
            fig.add_scatter(x=months, y=y.rolling(3).mean(), mode="lines", line=dict(color=BLUE_DARK, width=3, shape="spline"),
                            name="3-month avg", hovertemplate="%{x|%b %Y} 3-mo avg: %{y:,.0f}<extra></extra>")
        peak = monthly.loc[y.idxmax()]
        fig.add_annotation(x=pd.Timestamp(peak.month), y=peak[metric], text=f"peak {pd.Timestamp(peak.month):%b %Y}",
                           showarrow=True, arrowhead=0, ay=-30, bgcolor="white", bordercolor=OUTLINE, borderpad=4)
        fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.08, bgcolor="#eef3fb"))
        fig.update_yaxes(tickprefix="R$" if metric != "orders" else "")
        fig.update_layout(margin=dict(l=8, r=8, t=24, b=8))
        chart(fig, 330)


def page_customers() -> None:
    page_head("groups", "Customers & RFM", "Who buys, how often, and which segments carry the revenue")
    seg_df = d["rfm_segments"]
    c1, c2 = st.columns([2, 3])
    with c1, card("freq"):
        card_title("repeat", "Orders per customer", "Why RFM segments on Recency × Monetary only")
        fig = go.Figure(go.Pie(
            labels=[f"{o} order{'s' if o != '1' else ''}" for o in freq["orders_per_customer"]], values=freq["customers"],
            hole=0.68, sort=False, marker=dict(colors=[BLUE, ORANGE, AQUA, YELLOW], line=dict(color="white", width=3)),
            textinfo="none", hovertemplate="%{label}: %{value:,} customers (%{percent})<extra></extra>",
        ))
        fig.add_annotation(text=f"<b>{one_time:.1f}%</b><br><span style='font-size:12px;color:{INK2}'>bought once</span>",
                           showarrow=False, font=dict(size=26, color=INK))
        fig.update_layout(legend=dict(orientation="v", x=1.0, y=0.5, yanchor="middle"), margin=dict(l=8, r=8, t=8, b=8))
        chart(fig, 330)
    with c2, card("treemap"):
        card_title("grid_view", "RFM segment map", "Area = customers · colour = average spend · hover for detail")
        fig = go.Figure(go.Treemap(
            labels=seg_df["segment"], parents=[""] * len(seg_df), values=seg_df["customers"],
            marker=dict(colors=seg_df["avg_monetary"], colorscale=[[0, "#cde2fb"], [1, "#1c5cab"]], line=dict(color="white", width=3),
                        pad=dict(t=4, l=4, r=4, b=4), colorbar=dict(title="Avg R$", thickness=10)),
            customdata=np.c_[seg_df["pct_of_customers"], seg_df["pct_of_revenue"], seg_df["avg_monetary"], seg_df["median_recency_days"]],
            texttemplate="<b>%{label}</b><br>%{customdata[0]:.1f}% of customers<br>%{customdata[1]:.1f}% of revenue",
            hovertemplate="<b>%{label}</b><br>%{value:,} customers<br>Avg spend R$%{customdata[2]:.0f}<br>"
                          "Median recency %{customdata[3]:.0f} days<extra></extra>",
            tiling=dict(pad=4), root=dict(color="rgba(0,0,0,0)"),
        ))
        fig.update_layout(margin=dict(l=4, r=4, t=4, b=4))
        chart(fig, 330)

    playbook = {
        "Champions": ("workspace_premium", "Recent and high-spend. Protect them: early access, referral asks, priority support."),
        "At risk, high value": ("warning", "High spend, but gone quiet. Win them back with personalised reactivation offers."),
        "Potential loyalists": ("trending_up", "Mid-recency, high spend. Nudge a second purchase with cross-sell from their first category."),
        "Hibernating": ("bedtime", "Old and low spend. Low-cost reminders only; do not overspend here."),
        "Recent, low spend": ("rocket_launch", "Just arrived. Onboarding flows and a second-order incentive."),
        "Needs attention": ("notifications_active", "Mid-recency, low spend. Time-boxed offers before they go dormant."),
    }
    with card("segment_detail"):
        card_title("person_search", "Segment explorer", "Pick a segment to see its profile and the recommended play")
        pick = st.pills("Segment", seg_df["segment"].tolist(), default="At risk, high value", key="rfm_pick",
                        label_visibility="collapsed") or "At risk, high value"
        r = seg_df.set_index("segment").loc[pick]
        c1, c2 = st.columns([3, 2])
        with c1:
            html(stat_grid([
                ("Customers", f"{r.customers:,.0f}", f"{r.pct_of_customers:.1f}% of base", ""),
                ("Revenue", brl(r.revenue), f"{r.pct_of_revenue:.1f}% of total", ""),
                ("Avg spend", f"R${r.avg_monetary:,.0f}", "per customer", ""),
                ("Median recency", f"{r.median_recency_days:.0f} days", f"{r.pct_repeat_buyers:.1f}% repeat buyers", ""),
            ]))
        with c2:
            ic, text = playbook[pick]
            html(f'<div class="finding"><div class="finding-top"><div class="finding-num">{icon(ic)}</div><h4>Recommended play</h4></div>'
                 f'<div class="body">{text}</div></div>')
        s = seg_df.sort_values("pct_of_revenue")
        fig = go.Figure()
        fig.add_bar(y=s["segment"], x=s["pct_of_customers"], orientation="h", name="% of customers", marker_color=BLUE_LIGHT)
        fig.add_bar(y=s["segment"], x=s["pct_of_revenue"], orientation="h", name="% of revenue",
                    marker_color=[ORANGE if x == pick else BLUE for x in s["segment"]])
        fig.update_xaxes(ticksuffix="%")
        fig.update_layout(barmode="group", margin=dict(l=8, r=8, t=30, b=8))
        chart(fig, 330)


def page_drivers() -> None:
    page_head("local_shipping", "Satisfaction drivers", "What actually moves review scores — and what doesn't")

    @st.fragment
    def simulator() -> None:
        with card("sim"):
            card_title("tune", "What-if: cut late deliveries",
                       "Scenario assumes rescued orders are reviewed like today's on-time orders (upper bound, see Layer 2)")
            cut = st.slider("Reduce late deliveries by", 0, 100, 50, 5, format="%d%%", key="sim_cut")
            moved = late.orders * cut / 100
            low_now = n_low_late + n_low_ontime
            low_new = (late.orders - moved) * late.pct_low_review / 100 + (ontime.orders + moved) * ontime.pct_low_review / 100
            total = late.orders + ontime.orders
            avg_now = (late.orders * late.avg_review + ontime.orders * ontime.avg_review) / total
            avg_new = ((late.orders - moved) * late.avg_review + (ontime.orders + moved) * ontime.avg_review) / total
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="big-stat">{moved:,.0f}</div><div class="big-label">orders rescued from lateness</div>',
                        unsafe_allow_html=True)
            c2.markdown(f'<div class="big-stat green">−{low_now - low_new:,.0f}</div><div class="big-label">fewer 1-2★ reviews '
                        f'({100 * (low_now - low_new) / low_now:.1f}% of all)</div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="big-stat orange">{100 * low_new / total:.1f}%</div><div class="big-label">1-2★ rate '
                        f'(from {100 * low_now / total:.1f}%)</div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="big-stat">{avg_new:.2f}</div><div class="big-label">avg review (from {avg_now:.2f})</div>',
                        unsafe_allow_html=True)

    simulator()
    st.write("")

    with card("delay"):
        card_title("schedule", "Delivery delay vs review", "Actual minus estimated delivery date · orange = late")
        metric = seg("Metric", ["pct_low_review", "avg_review", "pct_five_star"], "pct_low_review", "delay_metric",
                     fmt={"pct_low_review": "1-2★ rate", "avg_review": "Avg review", "pct_five_star": "5★ rate"}.get)
        dl = d["delay_vs_review"]
        suffix = "" if metric == "avg_review" else "%"
        fig = go.Figure(go.Bar(
            x=dl["delay_bucket"], y=dl[metric], marker_color=[ORANGE if "late" in b else BLUE for b in dl["delay_bucket"]],
            text=[f"{v:.2f}" if metric == "avg_review" else f"{v:.0f}%" for v in dl[metric]], textposition="outside", cliponaxis=False,
            customdata=np.c_[dl["orders"], dl["pct_of_orders"]],
            hovertemplate="<b>%{x}</b><br>%{y:.2f}" + suffix + "<br>%{customdata[0]:,} orders (%{customdata[1]:.1f}%)<extra></extra>",
        ))
        fig.update_yaxes(ticksuffix=suffix, range=[0, dl[metric].max() * 1.18])
        fig.update_layout(margin=dict(l=8, r=8, t=16, b=8))
        chart(fig, 340)

    c1, c2 = st.columns([3, 2])
    with c1, card("states"):
        card_title("public", "Region: lateness vs bad reviews", "Bubble = orders · click a state to profile it")
        is_spot = so["customer_state"] == spotlight
        # Label only states worth reading: big markets, very late ones, and the spotlight.
        show = (so["orders"] >= 3000) | (so["late_pct"] >= 2 * national_late) | is_spot
        fig = go.Figure(go.Scatter(
            x=so["late_pct"], y=so["pct_low_review"], mode="markers+text", text=np.where(show, so["customer_state"], ""),
            textposition="top center",
            textfont=dict(size=11, color=INK2),
            marker=dict(size=np.sqrt(so["orders"]) / 2.2 + 8, color=np.where(is_spot, ORANGE, BLUE), opacity=0.85,
                        line=dict(color="white", width=2)),
            customdata=np.c_[so["orders"], so["avg_delivery_days"], so["revenue"]],
            hovertext=so["customer_state"],
            hovertemplate="<b>%{hovertext}</b><br>Late %{x:.1f}% · 1-2★ %{y:.1f}%<br>%{customdata[0]:,} orders · "
                          "%{customdata[1]:.1f} days avg<extra></extra>",
        ))
        fig.add_vline(x=national_late, line=dict(color=GREY, dash="dot", width=1), annotation_text="national late %")
        fig.update_xaxes(ticksuffix="%", title="Late-delivery rate")
        fig.update_yaxes(ticksuffix="%", title="1-2★ review rate")
        fig.update_layout(margin=dict(l=8, r=8, t=16, b=8))
        event = chart(fig, 420, key="state_scatter", select=True)
    pts = selected_points(event)
    picked = so.iloc[pts[0]["point_index"]]["customer_state"] if pts else spotlight
    with c2, card("state_profile"):
        o = so.set_index("customer_state").loc[picked]
        rank = int(so.sort_values("revenue", ascending=False)["customer_state"].tolist().index(picked)) + 1
        card_title("location_on", f"State profile · {picked}", f"#{rank} by revenue · spotlight via the sidebar or click a bubble")
        html(stat_grid([
            ("Late rate", f"{o.late_pct:.1f}%", f"national {national_late:.1f}%", "bad" if o.late_pct > national_late else "good"),
            ("1-2★ rate", f"{o.pct_low_review:.1f}%", f"overall {overall_low:.1f}%", "bad" if o.pct_low_review > overall_low else "good"),
            ("Delivery time", f"{o.avg_delivery_days:.1f} days", "purchase → delivery", ""),
            ("Freight / price", f"{o.freight_pct_of_price:.1f}%", "order level", ""),
            ("Revenue", brl(o.revenue), f"{o.pct_of_revenue:.1f}% of total", ""),
            ("Avg review", f"{o.avg_review:.2f}", f"{o.orders:,.0f} orders", ""),
        ]))
        corr = np.corrcoef(so["late_pct"], so["pct_low_review"])[0, 1]
        html(f'<span class="pill-tag">{icon("insights")}State late % vs 1-2★ %: r = {corr:.2f} (unweighted)</span>')

    c1, c2 = st.columns(2)
    with c1, card("cats"):
        cats = d["category_ops"]
        card_title("category", "1-2★ rate by category", f"Top categories by revenue · orange = above the {overall_low:.1f}% overall rate")
        n = st.slider("Categories (top by revenue)", 5, len(cats), 12, key="cat_n")
        t = cats.head(n).iloc[::-1]
        fig = go.Figure(go.Bar(
            x=t["pct_low_review"], y=t["category"].str.replace("_", " "), orientation="h",
            marker_color=[ORANGE if v > overall_low else BLUE for v in t["pct_low_review"]],
            customdata=np.c_[t["late_pct"], t["avg_delivery_days"], t["freight_pct_of_price"], t["pct_of_revenue"]],
            hovertemplate="<b>%{y}</b><br>1-2★ %{x:.1f}% · late %{customdata[0]:.1f}%<br>%{customdata[1]:.1f} days · "
                          "freight %{customdata[2]:.1f}% of price<br>%{customdata[3]:.1f}% of revenue<extra></extra>",
        ))
        fig.add_vline(x=overall_low, line=dict(color=GREY, dash="dash", width=1))
        fig.update_xaxes(ticksuffix="%")
        fig.update_layout(margin=dict(l=8, r=8, t=8, b=8))
        chart(fig, max(320, 24 * n + 40))
    with c2, card("freight"):
        card_title("savings", "Freight share vs bad reviews", "On-time orders only — lateness removed")
        fr = d["freight_vs_review"]
        fig = go.Figure()
        fig.add_bar(x=fr["freight_share_of_price"], y=fr["pct_low_review_on_time"], name="1-2★ rate, on-time orders",
                    marker_color=BLUE, text=[f"{v:.1f}%" for v in fr["pct_low_review_on_time"]], textposition="outside")
        fig.add_scatter(x=fr["freight_share_of_price"], y=[late.pct_low_review] * len(fr), mode="lines", name="Late orders (any freight)",
                        line=dict(color=ORANGE, dash="dash", width=2))
        fig.update_yaxes(ticksuffix="%", range=[0, late.pct_low_review * 1.15])
        fig.update_xaxes(title="Freight as % of item price")
        chart(fig, 330)
        gap_fr = fr.iloc[-1].pct_low_review_on_time - fr.iloc[0].pct_low_review_on_time
        html(f'<span class="pill-tag">{icon("compare_arrows")}Freight gap {gap_fr:.2f} pts vs lateness gap '
             f'{late.pct_low_review - ontime.pct_low_review:.1f} pts</span>')

    with card("repeat"):
        card_title("replay", "Does a bad first order stop customers coming back?", "180-day repeat rate · 95% confidence intervals")
        rep = d["first_order_vs_repeat"]
        r_all = rep[rep["dimension"] == "All eligible customers"].iloc[0]
        rep = rep[rep["dimension"] != "All eligible customers"].copy()
        p = rep["repeat_rate_180d_pct"] / 100
        rep["ci95"] = 100 * 1.96 * np.sqrt(p * (1 - p) / rep["customers"])
        rep["label"] = rep["dimension"].str.replace("First order ", "") + " · " + rep["value"]
        fig = go.Figure(go.Bar(x=rep["label"], y=rep["repeat_rate_180d_pct"], marker_color=BLUE,
                               error_y=dict(type="data", array=rep["ci95"], color=GREY, thickness=1.5, width=6),
                               customdata=rep["customers"],
                               hovertemplate="%{x}<br>%{y:.2f}% repeat · n = %{customdata:,}<extra></extra>"))
        fig.add_hline(y=r_all.repeat_rate_180d_pct, line=dict(color=GREY, dash="dash", width=1),
                      annotation_text=f"all customers {r_all.repeat_rate_180d_pct:.2f}%")
        fig.update_yaxes(ticksuffix="%")
        chart(fig, 300)
        r = d["first_order_vs_repeat"].set_index(["dimension", "value"])
        rl, ro = r.loc[("First order delivery", "Late")], r.loc[("First order delivery", "On time or early")]
        html(f'<span class="pill-tag">{icon("science")}Late vs on-time first order: p = '
             f'{two_prop_p(rl.returned, rl.customers, ro.returned, ro.customers):.3f} — not a significant retention lever</span>')


def page_model() -> None:
    page_head("model_training", "Low-review risk model",
              "LightGBM scores every order at purchase time — no delivery dates, delay or review data used")
    metrics = d["model_metrics"]
    main = metrics[(metrics["model"] == "LightGBM") & metrics["evaluation"].str.startswith("Stratified")].iloc[0]
    oot = metrics[metrics["evaluation"].str.startswith("Out-of-time")].iloc[0]
    logit = metrics[metrics["model"] == "Logistic regression"].iloc[0]
    curve = d["model_capture_curve"]
    c10 = curve.iloc[9]
    html('<div class="kpi-grid">' + "".join([
        kpi("query_stats", "ROC-AUC (test)", f"{main.roc_auc:.3f}", f"logistic {logit.roc_auc:.3f} · no-skill 0.500"),
        kpi("track_changes", "PR-AUC (test)", f"{main.pr_auc:.3f}", f"{main.pr_auc_lift:.2f}x the {main.positive_rate:.1%} base rate"),
        kpi("history", "Out-of-time ROC-AUC", f"{oot.roc_auc:.3f}", f"PR-AUC {oot.pr_auc:.3f} · trained before May 2018", tone="orange"),
        kpi("radar", "Caught in top 10%", f"{c10.recall_at_top:.1%}", f"of low reviews · {c10.precision_at_top:.1%} precision", tone="green"),
    ]) + "</div>")

    @st.fragment
    def triage() -> None:
        with card("triage"):
            card_title("tune", "Triage simulator", "If ops reviews the riskiest X% of orders at checkout, what do they catch?")
            pct = st.slider("Flag the riskiest share of orders", 1, 50, 10, format="%d%%", key="triage_pct")
            row = curve.iloc[pct - 1]
            full = d["monthly_trend"][~d["monthly_trend"]["is_partial_edge"]]
            per_month = full["orders"].mean()
            flagged = per_month * pct / 100
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="big-stat">{flagged:,.0f}</div><div class="big-label">orders flagged / month '
                        f'(avg {per_month:,.0f} delivered)</div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="big-stat green">{row.recall_at_top:.1%}</div><div class="big-label">of all 1-2★ reviews caught</div>',
                        unsafe_allow_html=True)
            c3.markdown(f'<div class="big-stat orange">{row.precision_at_top:.1%}</div><div class="big-label">of flagged orders '
                        f'turn out 1-2★</div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="big-stat">{row.lift_vs_random:.1f}x</div><div class="big-label">better than random picking</div>',
                        unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_scatter(x=curve["top_frac"] * 100, y=curve["recall_at_top"] * 100, mode="lines", name="LightGBM",
                            line=dict(color=BLUE, width=3, shape="spline"), fill="tozeroy",
                            fillcolor="rgba(42,120,214,0.08)",
                            hovertemplate="Flag top %{x:.0f}% → catch %{y:.1f}% of low reviews<extra></extra>")
            fig.add_scatter(x=[0, 100], y=[0, 100], mode="lines", name="Random", line=dict(color=GREY, dash="dot", width=1.5),
                            hoverinfo="skip")
            fig.add_scatter(x=[pct], y=[row.recall_at_top * 100], mode="markers", name="Your setting",
                            marker=dict(size=16, color=ORANGE, line=dict(color="white", width=3)),
                            hovertemplate="Top %{x:.0f}% → %{y:.1f}%<extra></extra>")
            fig.add_vline(x=pct, line=dict(color=ORANGE, width=1, dash="dot"))
            fig.update_xaxes(ticksuffix="%", title="Share of orders flagged (riskiest first)", range=[0, 100])
            fig.update_yaxes(ticksuffix="%", title="Share of low reviews caught", range=[0, 102])
            chart(fig, 330)

    triage()
    st.write("")

    c1, c2 = st.columns(2)
    with c1, card("curves"):
        card_title("show_chart", "Model vs baseline", "Stratified 20% test set")
        kind = seg("Curve", ["ROC", "PR"], "ROC", "curve_kind", fmt={"ROC": "ROC curve", "PR": "Precision-recall"}.get)
        cv = d["model_curves"]
        fig = go.Figure()
        for model_name, color in [("LightGBM", BLUE), ("Logistic regression", ORANGE)]:
            c = cv[(cv["model"] == model_name) & (cv["curve"] == kind)]
            fig.add_scatter(x=c["x"], y=c["y"], mode="lines", name=model_name, line=dict(color=color, width=2.5))
        if kind == "ROC":
            fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="No skill", line=dict(color=GREY, dash="dot", width=1.5))
            fig.update_xaxes(title="False positive rate"); fig.update_yaxes(title="True positive rate")
        else:
            fig.add_hline(y=main.positive_rate, line=dict(color=GREY, dash="dot", width=1.5), annotation_text="no skill")
            fig.update_xaxes(title="Recall"); fig.update_yaxes(title="Precision")
        chart(fig, 360)
    with c2, card("shap_imp"):
        card_title("psychology", "What drives predicted risk (SHAP)", "Mean |SHAP| on 5,000 test orders")
        n = st.slider("Features", 5, len(d["shap_importance"]), 12, key="shap_n")
        imp = d["shap_importance"].head(n).iloc[::-1]
        fig = go.Figure(go.Bar(x=imp["mean_abs_shap"], y=imp["feature"], orientation="h",
                               marker=dict(color=imp["mean_abs_shap"], colorscale=[[0, "#9ec5f4"], [1, "#1c5cab"]]),
                               hovertemplate="%{y}: %{x:.3f}<extra></extra>"))
        fig.update_xaxes(title="Mean |SHAP| (log-odds)")
        chart(fig, max(300, 22 * n + 40))

    c1, c2 = st.columns([3, 2])
    with c1, card("beeswarm"):
        card_title("scatter_plot", "SHAP beeswarm", "Each dot is an order · right = raises risk · colour = feature value")
        bee = d["shap_beeswarm"]
        order = [f for f in d["shap_importance"]["feature"] if f in set(bee["feature"])]
        pick = st.pills("Features", order, default=order[:6], selection_mode="multi", key="bee_pick",
                        label_visibility="collapsed") or order[:6]
        feats = [f for f in order if f in pick]
        pos = {f: i for i, f in enumerate(feats[::-1])}
        b = bee[bee["feature"].isin(feats)]
        rng = np.random.default_rng(42)
        yj = b["feature"].map(pos) + rng.uniform(-0.32, 0.32, len(b))
        fig = go.Figure(go.Scattergl(
            x=b["shap_value"], y=yj, mode="markers",
            marker=dict(size=5, color=b["feature_scaled"], colorscale=[[0, BLUE], [0.5, "#c9c3d6"], [1, RED]], opacity=0.65,
                        colorbar=dict(title="Value", tickvals=[0, 1], ticktext=["Low", "High"], thickness=10)),
            customdata=np.c_[b["feature"], b["feature_value"]],
            hovertemplate="%{customdata[0]} = %{customdata[1]:,.1f}<br>SHAP %{x:+.3f}<extra></extra>",
        ))
        fig.add_vline(x=0, line=dict(color=GREY, width=1))
        fig.update_yaxes(tickvals=list(pos.values()), ticktext=list(pos.keys()), showgrid=False)
        fig.update_xaxes(title="SHAP value (log-odds)")
        chart(fig, max(300, 48 * len(feats) + 80))
    with c2, card("shap_state"):
        card_title("map", "Customer state effect", f"Average SHAP per state · {spotlight} highlighted")
        se = d["shap_state_effect"].sort_values("mean_shap")
        fig = go.Figure(go.Bar(x=se["mean_shap"], y=se["customer_state"], orientation="h",
                               marker_color=[ORANGE if s == spotlight else (RED if v > 0 else BLUE)
                                             for s, v in zip(se["customer_state"], se["mean_shap"])],
                               customdata=se["orders"], hovertemplate="%{y}: %{x:+.3f} (n = %{customdata})<extra></extra>"))
        fig.add_vline(x=0, line=dict(color=GREY, width=1))
        fig.update_xaxes(title="Mean SHAP (+ raises risk)")
        chart(fig, 380)

    with st.expander(":material/table: Target comparison, baselines and caveats"):
        st.dataframe(d["model_target_comparison"].round(4), hide_index=True, use_container_width=True)
        st.dataframe(metrics.round(4), hide_index=True, use_container_width=True)
        st.caption("Repeat purchase was modelled too and rejected: too rare and too weakly predictable to act on. "
                   "The random split is optimistic because purchase_month partly encodes period-specific logistics shocks "
                   "(Nov 2017, Feb–Mar 2018); the out-of-time score is the fair estimate. SHAP explains the model, not causality.")


def page_findings() -> None:
    page_head("lightbulb", "Findings & recommendations", "Problem → finding → so what → action, each tied to a computed number")
    so_i = so.set_index("customer_state")
    rj, sp = so_i.loc[default_spot], so_i.loc["SP"]
    share_low_late = 100 * n_low_late / (n_low_late + n_low_ontime)
    co = d["category_ops"]
    worst = co[co["pct_of_revenue"] >= 1].sort_values("pct_low_review", ascending=False).iloc[0]
    fr_lo, fr_hi = d["freight_vs_review"].iloc[0], d["freight_vs_review"].iloc[-1]
    tiers = d["seller_tiers"].set_index("seller_tier")
    t_top, t_rest = tiers.loc["Top 20% sellers"], tiers.loc["Other 80% sellers"]
    r = d["first_order_vs_repeat"].set_index(["dimension", "value"])
    rl, ro = r.loc[("First order delivery", "Late")], r.loc[("First order delivery", "On time or early")]
    p_late = two_prop_p(rl.returned, rl.customers, ro.returned, ro.customers)
    at_risk = d["rfm_segments"].set_index("segment").loc["At risk, high value"]

    findings = [
        ("Which operational factor hurts satisfaction most?", "Late delivery is the #1 driver",
         f"Late orders are {late.pct_of_orders:.1f}% of orders but get 1-2★ reviews {late.pct_low_review:.1f}% of the time vs "
         f"{ontime.pct_low_review:.1f}% on time, generating {share_low_late:.1f}% of all low reviews.",
         "Lateness is the biggest lever on ratings — see the what-if simulator on the Satisfaction page.",
         "Make on-time delivery the lead satisfaction KPI; flag at-risk orders at purchase and notify customers proactively."),
        ("Is lateness a regional problem?", "Lateness is regional",
         f"{default_spot} ({rj.pct_of_revenue:.1f}% of revenue) is late {rj.late_pct:.1f}% of the time vs {sp.late_pct:.1f}% in SP, "
         f"with {rj.pct_low_review:.1f}% vs {sp.pct_low_review:.1f}% low reviews.",
         "A lane-level fix is more efficient than a platform-wide one.",
         f"Audit carriers and delivery-date promises on SP→{default_spot} and North-East lanes first."),
        ("Which categories pair revenue with poor experience?", "Some categories carry a penalty",
         f"{worst.category.replace('_', ' ')}: {worst.pct_low_review:.1f}% low reviews vs {overall_low:.1f}% overall, "
         f"{worst.avg_delivery_days:.1f} avg delivery days.",
         "Bulky, slow-shipping categories hide a satisfaction penalty in the average.",
         "Set category-specific delivery promises and packaging standards."),
        ("Does freight cost drive dissatisfaction?", "Freight price is a weak driver",
         f"On on-time orders, low reviews go from {fr_lo.pct_low_review_on_time:.1f}% to {fr_hi.pct_low_review_on_time:.1f}% "
         f"as freight rises from <10% to 50%+ of price.",
         "Subsidising shipping would buy little rating improvement.",
         "Fund delivery reliability, not freight subsidies; test free-shipping thresholds for conversion instead."),
        ("Is seller concentration an operational risk?", "Fix lanes, not sellers",
         f"The top 20% of sellers make {t_top.pct_of_revenue:.1f}% of revenue and are late {t_top.late_pct:.1f}% of the time "
         f"vs {t_rest.late_pct:.1f}% for the rest.",
         "Lateness is not a small-seller problem; pruning the tail won't fix it.",
         "Protect key sellers with account management and per-seller on-time scorecards."),
        ("Why don't customers come back?", "Retention is structurally low",
         f"{one_time:.1f}% of customers buy once. A late first order gives {rl.repeat_rate_180d_pct:.2f}% 180-day repeat vs "
         f"{ro.repeat_rate_180d_pct:.2f}% on time (p = {p_late:.3f}).",
         "Better delivery protects ratings but will not create loyalty on its own.",
         f"Build lifecycle CRM, starting with 'At risk, high value' customers ({at_risk.pct_of_revenue:.1f}% of revenue)."),
    ]
    for i in range(0, len(findings), 2):
        cols = st.columns(2)
        for col, (num, (problem, title, finding, so_what, action)) in zip(cols, enumerate(findings[i:i + 2], start=i + 1)):
            col.markdown(
                f'<div class="finding"><div class="finding-top"><div class="finding-num">{num}</div><h4>{title}</h4></div>'
                f'<div class="problem">{problem}</div><div class="body">{finding}</div>'
                f'<div class="so-what"><b>So what:</b> {so_what}</div>'
                f'<div class="action">{icon("arrow_forward")}<span>{action}</span></div></div>',
                unsafe_allow_html=True)
        st.write("")

    with st.expander(":material/info: Method & limitations"):
        st.markdown(
            "- **Correlation, not causation.** Late → low review is plausibly causal (reviews follow delivery), but lanes, "
            "categories and sellers are intertwined; scenario numbers are upper bounds.\n"
            "- **One-time-buyer skew.** Most customers buy once, so RFM uses Recency × Monetary and repeat purchase is not modelled.\n"
            "- **2016–2018 Brazil marketplace data**; sparse edge months are excluded from trends.\n"
            "- Satisfaction is measured on delivered orders with a review; freight's effect on *conversion* is not observable here."
        )


{"overview": page_overview, "revenue": page_revenue, "customers": page_customers,
 "drivers": page_drivers, "model": page_model, "findings": page_findings}[page]()

html(f'<div style="text-align:center;color:{INK2};font-size:.78rem;margin-top:2rem">'
     "Data: Olist Brazilian E-Commerce Public Dataset (Kaggle, CC BY-NC-SA 4.0) · "
     "every figure is computed from the dataset by the SQL and Python in this repository</div>")
