#!/usr/bin/env python3
import argparse, sys, logging
from pathlib import Path

import pandas as pd
import geopandas as gpd
import numpy as np
import osmnx as ox
import networkx as nx

# OSMnx settings 
ox.settings.use_cache = True
ox.settings.log_console = True
ox.settings.log_level = logging.INFO
ox.settings.timeout = 120


# Helpers 
def isochrone_polygon(G, center_node, minutes=15):
    """Walk-time isochrone polygon (minutes). Buffers in meters, returns WGS84."""
    cutoff = minutes * 60  # seconds
    subgraph = nx.ego_graph(G, center_node, radius=cutoff, distance="travel_time")
    nodes = ox.graph_to_gdfs(subgraph, edges=False)
    nodes_m = nodes.to_crs(3857)
    poly_m = nodes_m.buffer(35).union_all()  # replaces deprecated unary_union
    poly = gpd.GeoSeries([poly_m], crs=3857).to_crs(4326).iloc[0]
    return poly


def build_graph_from_aoi(aoi):
    """OSMnx 2.x: build walk graph from polygon AOI."""
    G = ox.graph_from_polygon(aoi, network_type="walk", retain_all=False)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    return G


def build_weights(
    tracts_gdf: gpd.GeoDataFrame,
    weight_by: str = "hvi",
    risk_path: Path = Path("data/processed/tracts_risk.geojson"),
    equity_csv: str | None = None,
    equity_weight: float = 1.0,
) -> pd.Series:
    """
    Returns a per-tract weight aligned to tracts_gdf['GEOID'].

    weight_by: "hvi" (default) or "risk". If "risk" and the risk file exists,
               uses RISK (0–1) and falls back to HVI where missing.
    equity_csv: optional CSV with columns GEOID, ej (0/1). When provided,
                multiplies weight in EJ tracts by equity_weight (e.g., 1.5).
    """
    if "GEOID" not in tracts_gdf.columns:
        raise ValueError("Tracts dataframe must contain a 'GEOID' column")

    idx = tracts_gdf["GEOID"].astype(str)
    # Base = HVI in 0–1 if present; otherwise 1.0 as a neutral baseline
    if "HVI" in tracts_gdf.columns:
        base = pd.Series(tracts_gdf["HVI"].astype(float).values, index=idx)
    else:
        base = pd.Series(1.0, index=idx)

    if str(weight_by).lower().startswith("risk") and risk_path.exists():
        try:
            r = gpd.read_file(risk_path)[["GEOID", "RISK"]].set_index("GEOID")["RISK"].astype(float)
            base = r.reindex(idx).fillna(base)
            print("[opt] using risk-weighted objective (RISK 0–1, fallback = HVI)")
        except Exception as e:
            print(f"[opt] risk file unreadable, falling back to HVI: {e}", file=sys.stderr)
    else:
        print("[opt] using HVI-weighted objective")

    w = base.clip(0, 1)

    # Optional equity bump
    if equity_csv:
        p = Path(equity_csv)
        if p.exists():
            try:
                ej = pd.read_csv(p, dtype={"GEOID": str})
                if "ej" in ej.columns:
                    ej = ej.set_index("GEOID")["ej"].fillna(0).astype(float)
                    bump = 1.0 + (float(equity_weight) - 1.0) * ej.reindex(idx).fillna(0.0)
                    w = (w * bump).astype(float)
                    print(f"[opt] equity bump enabled: x{equity_weight} in EJ tracts from {p}")
                else:
                    print(f"[opt] equity CSV missing 'ej' column → ignored: {p}", file=sys.stderr)
            except Exception as e:
                print(f"[opt] failed to read equity CSV → ignored: {e}", file=sys.stderr)
        else:
            print(f"[opt] equity CSV not found → ignored: {p}", file=sys.stderr)

    return w.fillna(0.0)


# Main 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracts", required=True, help="GeoJSON with tracts (must include GEOID, HVI)")
    ap.add_argument("--sites", required=True, help="Candidate sites (points)")
    ap.add_argument("--k", type=int, required=True, help="How many sites to select")
    ap.add_argument("--minutes", type=int, default=15, help="Walk minutes for isochrone")
    ap.add_argument("--out", required=True, help="Output GeoJSON for selected sites")

    # NEW: objective weighting & equity options
    ap.add_argument("--weight_by", choices=["hvi", "risk"], default="hvi",
                    help="Objective weight per tract (HVI or RISK if available)")
    ap.add_argument("--equity_csv", default=None,
                    help="Optional CSV with columns GEOID,ej(0/1) to up-weight EJ tracts")
    ap.add_argument("--equity_weight", type=float, default=1.0,
                    help="Multiply weight in EJ tracts (e.g., 1.5)")

    args = ap.parse_args()

    tracts = gpd.read_file(args.tracts).to_crs(4326)
    sites = gpd.read_file(args.sites)
    if sites.crs is None:
        sites.set_crs(4326, inplace=True)
    else:
        sites = sites.to_crs(4326)

    if len(sites) == 0:
        raise SystemExit("No candidate sites found.")

    print(f"[opt] candidates: {len(sites)}, k={args.k}, minutes={args.minutes}")

    # Small AOI around candidates (MUCH faster than whole county)
    sites_m = sites.to_crs(3857)
    tracts_m = tracts.to_crs(3857)
    walk_m_per_min = 80
    clip_radius = (args.minutes * walk_m_per_min) * 2  # generous
    clip_m = sites_m.buffer(clip_radius).union_all().intersection(
        tracts_m.dissolve().geometry.iloc[0]
    )
    aoi = gpd.GeoSeries([clip_m], crs=3857).to_crs(4326).iloc[0]

    print("[opt] building walk graph for AOI…")
    G = build_graph_from_aoi(aoi)
    print("[opt] graph ready")

    # Precompute isochrones per candidate
    polys = []
    for i, (_, r) in enumerate(sites.iterrows(), 1):
        try:
            node = ox.nearest_nodes(G, float(r.geometry.x), float(r.geometry.y))
            poly = isochrone_polygon(G, node, minutes=args.minutes)
            polys.append(poly)
            if i % 5 == 0 or i == len(sites):
                print(f"[opt] isochrones: {i}/{len(sites)}")
        except Exception as e:
            print(f"[opt] skip site {i}/{len(sites)}: {e}", file=sys.stderr)

    if not polys:
        raise SystemExit("No isochrones were created.")

    # Prepare tract centroids + weights
    tr_m = tracts.to_crs(3857).copy()
    tr_m["centroid"] = tr_m.geometry.centroid
    cent = tr_m[["GEOID", "centroid"]].copy().set_geometry("centroid").to_crs(4326)
    cent["GEOID"] = cent["GEOID"].astype(str)

    weights_series = build_weights(
        tracts_gdf=tracts,
        weight_by=args.weight_by,
        risk_path=Path("data/processed/tracts_risk.geojson"),
        equity_csv=args.equity_csv,
        equity_weight=args.equity_weight,
    )
    # align weights to centroid order
    cent["weight"] = weights_series.reindex(cent["GEOID"]).fillna(0.0).values

    # For each candidate, which centroids are inside its isochrone?
    covered_by = []
    for j, poly in enumerate(polys):
        covered_by.append(cent.geometry.within(poly).values)
    covered_by = np.vstack(covered_by)  # shape: [num_candidates, num_centroids]
    weights = cent["weight"].to_numpy()

    # Greedy selection: pick k sites maximizing weighted coverage
    chosen = []
    remaining = np.ones(len(cent), dtype=bool)
    for _ in range(min(args.k, len(sites))):
        gains = (covered_by[:, remaining] * weights[remaining]).sum(axis=1)
        if chosen:
            gains[chosen] = -1.0  # avoid picking same site twice
        j = int(np.argmax(gains))
        chosen.append(j)
        newly = covered_by[j] & remaining
        remaining[newly] = False
        print(f"[opt] pick #{len(chosen)} -> candidate {j} (+{weights[newly].sum():.2f} weight)")

    # Save
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = sites.iloc[chosen].copy()
    result.to_file(out, driver="GeoJSON")
    print(f"[opt] wrote {out} (selected {len(result)} sites)")


if __name__ == "__main__":
    main()
