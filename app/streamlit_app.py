import math
import colorsys
from pathlib import Path

import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.features import GeoJson, GeoJsonTooltip
from streamlit_folium import st_folium

st.set_page_config(page_title="SD Heat Vulnerability & Cooling Optimization", layout="wide") 
st.title("San Diego — Heat Vulnerability Index (HVI) & Cooling Coverage")
st.caption(f"Loaded script: {__file__}")  

# Utils
def _safe_float(v, default=0.0):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default

def plt_color(value):
    v = _safe_float(value, 0.0)         # safe convert
    v = max(0.0, min(1.0, v))           # clamp 0–1
    hue = (2.0/3.0) * (1.0 - v)         # blue→red
    r,g,b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

def load_gdf(p):
    p = Path(p)
    if not p.exists():
        return None
    return gpd.read_file(p)

# Sidebar 
st.sidebar.header("Data Inputs")
tracts_path   = st.sidebar.text_input("Tracts with HVI (GeoJSON)", "data/processed/tracts_hvi.geojson")
sites_path    = st.sidebar.text_input("Existing Cooling Sites (GeoJSON)", "data/processed/cooling_sites.geojson")
opt_sites_in  = st.sidebar.text_input("Optimized Sites (optional, GeoJSON)", "data/processed/optimized_k5.geojson")

# Controls
k        = st.sidebar.slider("New sites (k)", 1, 30, 5)
minutes  = st.sidebar.slider("Walk minutes", 5, 30, 15, step=5)
show_sites = st.sidebar.checkbox("Show existing sites", True)
show_opt   = st.sidebar.checkbox("Show optimized sites", True)

# If a precomputed optimized_k{k}.geojson exists, use it automatically
auto_opt_path = Path(f"data/processed/optimized_k{k}.geojson")
opt_sites_path = str(auto_opt_path if auto_opt_path.exists() else Path(opt_sites_in))

# Load data 
g_tracts = load_gdf(tracts_path)
if g_tracts is None:
    st.error(f"Tracts file not found: {tracts_path}")
    st.stop()

g_tracts = g_tracts.to_crs(4326)
g_sites  = load_gdf(sites_path)
g_opt    = load_gdf(opt_sites_path)
if g_sites is not None: g_sites = g_sites.to_crs(4326)
if g_opt   is not None: g_opt   = g_opt.to_crs(4326)

# CDC Heat & Health Index (tract-level, derived from ZCTAs)
_hhi_csv = Path("data/processed/hhi_tract.csv")
if _hhi_csv.exists():
    hhi_df = pd.read_csv(_hhi_csv, dtype={"GEOID": str})
    # be tolerant about the column name coming from your ingest
    if "CDC_HHI" not in hhi_df.columns:
        for cand in ["HHI", "hhi", "HHI_norm", "index", "hhi_score"]:
            if cand in hhi_df.columns:
                hhi_df = hhi_df.rename(columns={cand: "CDC_HHI"})
                break
    if "CDC_HHI" in hhi_df.columns:
        g_tracts = g_tracts.merge(hhi_df[["GEOID", "CDC_HHI"]], on="GEOID", how="left")

# Map init (with fallback center) 
try:
    ctr = g_tracts.geometry.union_all().centroid
    center = [ctr.y, ctr.x]
    if not all(map(math.isfinite, center)):
        raise ValueError
except Exception:
    center = [32.8, -117.1]   # San Diego fallback

m = folium.Map(location=center, zoom_start=10, tiles="cartodbpositron")

#  Baseline coverage (if present) 
_cov = Path("data/processed/coverage.gpkg")
if _cov.exists():
    try:
        cov = gpd.read_file(_cov, layer="coverage").to_crs(4326)
        folium.GeoJson(
            cov.to_json(),
            name="15-min Coverage (baseline)",
            style_function=lambda f: {"color": "#555", "weight": 1, "fillOpacity": 0.03},
        ).add_to(m)
    except Exception as e:
        st.sidebar.warning(f"Could not read baseline coverage: {e}")

# Tracts (HVI / Risk / CDC HHI) 

# Try to join in predicted risk (if not already present)
risk_path = Path("data/processed/tracts_risk.geojson")
if "RISK" not in g_tracts.columns and risk_path.exists():
    g_risk = gpd.read_file(risk_path)[["GEOID", "RISK"]]
    g_tracts = g_tracts.merge(g_risk, on="GEOID", how="left")

# Sidebar radio: show CDC HHI only if present
options = ["HVI", "Risk (predicted events per 10k)"]
if "CDC_HHI" in g_tracts.columns:
    options.append("CDC HHI")

default_idx = 1 if ("RISK" in g_tracts.columns and g_tracts["RISK"].notna().any()) else 0
color_by = st.sidebar.radio("Color tracts by", options, index=default_idx)

metric_map = {
    "HVI": "HVI",
    "Risk (predicted events per 10k)": "RISK",
    "CDC HHI": "CDC_HHI"
}
metric_col = metric_map[color_by]
layer_name = f"Tracts ({'Risk' if metric_col=='RISK' else ('CDC HHI' if metric_col=='CDC_HHI' else 'HVI')})"

def style_fn_factory(metric):
    def _fn(feat):
        raw = feat["properties"].get(metric)
        try:
            v = float(raw) if raw is not None else 0.0
        except Exception:
            v = 0.0
        return {"fillColor": plt_color(v), "color": "#333", "weight": 0.4, "fillOpacity": 0.65}
    return _fn

tip_cols = [c for c in ["GEOID", "HVI", "RISK", "CDC_HHI"] if c in g_tracts.columns]
tooltip = GeoJsonTooltip(fields=tip_cols, aliases=tip_cols, localize=True)

GeoJson(
    g_tracts.to_json(),
    name=layer_name,
    style_function=style_fn_factory(metric_col),
    tooltip=tooltip,
).add_to(m)

# Existing sites 
if show_sites and g_sites is not None and len(g_sites) > 0:
    fg = folium.FeatureGroup(name="Existing sites")
    for _, r in g_sites.iterrows():
        folium.CircleMarker(
            [r.geometry.y, r.geometry.x],
            radius=4, color="#0057ff", fill=True, fill_opacity=0.9,
            popup=r.get("name","Site")
        ).add_to(fg)
    fg.add_to(m)
elif show_sites and (g_sites is None or len(g_sites) == 0):
    st.sidebar.info(f"No sites found in {sites_path}")

# Optimized sites (friendlier popup) 
if show_opt and g_opt is not None and len(g_opt) > 0:
    # If optimized points don't already carry tract info, join it from tracts
    lower_cols = {c.lower() for c in g_opt.columns}
    if not ({"geoid", "hvi"} <= lower_cols) and len(g_tracts) > 0:
        # prepare tracts to join
        join_cols = g_tracts[["GEOID", "HVI", "geometry"]].rename(
            columns={"GEOID": "geoid", "HVI": "hvi"}
        )

        # project both to meters, join, then back to WGS84
        _utm = 32611  # UTM zone 11N (San Diego)
        g_opt_utm  = g_opt.to_crs(_utm)
        join_utm   = join_cols.to_crs(_utm)

        g_opt = gpd.sjoin_nearest(
            g_opt_utm, join_utm[["geoid", "hvi", "geometry"]],
            how="left", distance_col="dist_m"
        ).to_crs(4326)

        if "index_right" in g_opt.columns:
            g_opt = g_opt.drop(columns=["index_right"])

    # draw optimized points
    fg2 = folium.FeatureGroup(name=f"Optimized (k={k})")
    for _, r in g_opt.iterrows():
        geoid = r.get("geoid") or r.get("GEOID") or "unknown"
        hvi_v = r.get("hvi") if "hvi" in r else r.get("HVI")

        base = (r.get("name") or "").strip()
        if base.startswith("Cand_"):  # hide opaque ids
            base = ""

        popup_txt = base or f"New site — tract {geoid}"
        try:
            if hvi_v is not None:
                popup_txt += f"\nHVI: {float(hvi_v):.3f}"
        except Exception:
            pass

        folium.CircleMarker(
            [r.geometry.y, r.geometry.x],
            radius=5, color="#e31a1c", fill=True, fill_opacity=0.95,
            popup=popup_txt,
        ).add_to(fg2)

    fg2.add_to(m)

# After coverage for current k 
_after = Path(f"data/processed/coverage_after_k{k}.gpkg")
if _after.exists():
    try:
        cov_after = gpd.read_file(_after, layer="coverage").to_crs(4326)
        folium.GeoJson(
            cov_after.to_json(),
            name=f"{minutes}-min Coverage (after, k={k})",
            style_function=lambda f: {"color": "#e31a1c", "weight": 2, "fillOpacity": 0.05},
        ).add_to(m)
    except Exception as e:
        st.sidebar.warning(f"Could not read after-coverage for k={k}: {e}")

# Coverage summary (single block) 
from pathlib import Path
import pandas as _pd
import geopandas as _gpd

def _read_summary_csv(gpkg_path: str):
    csvp = Path(gpkg_path.replace(".gpkg", "_summary.csv"))
    return _pd.read_csv(csvp) if csvp.exists() else None

base_sum  = _read_summary_csv("data/processed/coverage.gpkg")
after_sum = _read_summary_csv(f"data/processed/coverage_after_k{k}.gpkg")

st.markdown("### Coverage summary")
c1, c2, c3, c4 = st.columns(4)

if base_sum is not None:
    c1.metric("Tracts covered (baseline)",
              f"{float(base_sum.iloc[0]['pct_tracts_covered']):.1f}%")

if after_sum is not None:
    pct_after = float(after_sum.iloc[0]['pct_tracts_covered'])
    pct_base  = float(base_sum.iloc[0]['pct_tracts_covered']) if base_sum is not None else 0.0
    c2.metric(f"Tracts covered (after, k={k})",
              f"{pct_after:.1f}%",
              delta=f"{(pct_after - pct_base):+.1f} pp")

    if 'pct_pop_covered' in after_sum.columns and _pd.notna(after_sum.iloc[0]['pct_pop_covered']):
        c3.metric("Population covered (after)",
                  f"{float(after_sum.iloc[0]['pct_pop_covered']):.1f}%")

# Compute HVI-weighted coverage (after) and show “top uncovered” table
g_after = None
_after_gpkg = Path(f"data/processed/coverage_after_k{k}.gpkg")
if _after_gpkg.exists():
    try:
        g_after = _gpd.read_file(_after_gpkg, layer="tracts_with_coverage")
        w = g_after["HVI"].clip(0, 1)
        hvi_w = 100.0 * (g_after["covered"] * w).sum() / (w.sum() + 1e-9)
        c4.metric("HVI-weighted coverage (after)", f"{hvi_w:.1f}%")
    except Exception as e:
        st.sidebar.warning(f"Could not compute HVI-weighted coverage: {e}")

if g_after is not None:
    todo = (g_after.loc[~g_after["covered"], ["GEOID", "HVI"]]
                  .sort_values("HVI", ascending=False)
                  .head(10))
    st.caption("Highest-HVI tracts still uncovered")
    st.dataframe(todo, hide_index=True)

# Brief helper text under the metrics
st.markdown(
"""
* **Tracts covered**: share of tracts whose **centroid** falls inside the walk catchments.
* **Population covered**: share of residents inside the catchments (if population was available during coverage).
* **HVI-weighted coverage**: after-k coverage where tracts with higher **HVI (0–1)** count more.
"""
)

#  Legend + controls 
legend_title = {"HVI": "HVI", "RISK": "Risk (predicted)", "CDC_HHI": "CDC HHI"}.get(metric_col, "HVI")
stops = ", ".join([f"{plt_color(i/10)} {i*10}%" for i in range(11)])

legend_html = f"""
{{% macro html(this, kwargs) %}}
<div style="position: fixed; bottom: 40px; left: 20px; z-index: 9999;
            background: white; padding: 10px 12px; border: 1px solid #999; border-radius: 8px;">
  <b>{legend_title}</b>
  <div style="width:220px; height:12px; background: linear-gradient(to right, {stops}); margin:6px 0;"></div>
  <div style="display:flex; justify-content:space-between; font-size:12px;">
    <span>Low</span><span>High</span>
  </div>
</div>
{{% endmacro %}}
"""

from branca.element import Template, MacroElement
macro = MacroElement()
macro._template = Template(legend_html)
m.get_root().add_child(macro)

folium.LayerControl(collapsed=False).add_to(m)

#  RENDER MAP 
st_folium(m, use_container_width=True, returned_objects=[], key="main_map")

# Notes / Help 
st.markdown("### How to read & use this map")

st.markdown(
"""
**Purpose.** Help San Diego identify neighborhoods most exposed to extreme heat and propose **equitable** locations for new **cooling centers, shade structures, and urban greening**—to reduce heat illness and advance environmental justice.

#### Map layers (toggle in the legend)
- **Tracts (HVI / Risk / CDC HHI)** – Colored polygons:
  - **HVI (0–1)**: local Heat Vulnerability Index (higher = hotter + more sensitive + lower adaptive capacity).
  - **Risk (0–1)**: predicted **heat-related events per 10k** (if modeled from outcomes; otherwise a proxy).
  - **CDC HHI (0–1)**: CDC’s 2024 **Heat & Health Index**, mapped from ZCTA (ZIP) to tracts (higher = worse).
- **Existing sites** – Blue dots: current cooling resources (e.g., libraries, rec centers).
- **Optimized (k=…)** – Red dots: model-recommended **new** sites that add the most coverage in higher-need areas.
- **15-min Coverage (baseline / after)** – Outlines showing where people can walk to a site within the chosen minutes.

Use the **sidebar**:
- **Color tracts by**: switch between **HVI**, **Risk**, and **CDC HHI** depending on your question:
  - *HVI* to explore structural vulnerability,
  - *Risk* to prioritize likely **health impact**,
  - *CDC HHI* to align with a national heat-health index.
- **New sites (k)** and **Walk minutes** to test scenarios.

#### How to analyze (quick workflow)
1. **Find gaps**: Turn on **baseline coverage** and scan for **yellow–red tracts outside** the coverage area.
2. **Test improvements**: Turn on **Optimized (k=…)** and the **after** coverage layer to see where access increases.
3. **Prioritize actions**:
   - High-need tracts **outside** coverage → consider **new cooling centers** or **temporary cooling**.
   - High-need tracts **near edges** → add **shade/greening** (trees, bus-stop shade, misting) along walk routes.
   - If you enabled equity weighting in optimization, recommendations will tilt toward **historically underserved** tracts.

#### What the metrics mean (top of page)
- **Tracts covered (baseline / after)**: % of tracts whose centroid is within walking catchments.  
  The green Δ is the **percentage-point** gain from the added sites.
- **Population covered (after)**: % of residents inside the catchments (if population was available).
- **HVI-weighted coverage (after)**: after-k coverage where higher-HVI tracts count more—emphasizes equity.

#### Caveats
- Walk access uses the street/path network and typical speeds; **site hours/capacity** aren’t modeled.
- **HVI / Risk / CDC HHI** are **relative** indexes (0–1), not probabilities of illness.
- Results depend on data vintages, geocoding, and boundaries; ground-truth with local knowledge before siting projects.

**Tip:** Click any tract or point for details. Try different **k** and **walk-minute** settings, then compare **baseline vs after** coverage.
"""
)
