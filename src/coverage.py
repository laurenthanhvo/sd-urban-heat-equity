#!/usr/bin/env python3
import argparse, sys, logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np
import osmnx as ox
import networkx as nx
from shapely.geometry import Point, Polygon

# OSMnx settings: cache + logs (fast + visible progress)
ox.settings.use_cache = True
ox.settings.log_console = True
ox.settings.log_level = logging.INFO
ox.settings.timeout = 120


def isochrone_polygon(G, center_node, minutes=15):
    """
    Build a walk-time isochrone polygon around a center node.
    Uses travel_time in seconds on the graph, buffers in meters, returns WGS84 polygon.
    """
    cutoff = minutes * 60  # seconds
    subgraph = nx.ego_graph(G, center_node, radius=cutoff, distance="travel_time")

    # nodes GeoDataFrame in WGS84
    nodes = ox.graph_to_gdfs(subgraph, edges=False)

    # buffer IN METERS, then convert back to WGS84
    nodes_m = nodes.to_crs(3857)              # Web Mercator (meters)
    poly_m  = nodes_m.buffer(35).union_all()  # replaces deprecated .unary_union
    poly    = gpd.GeoSeries([poly_m], crs=3857).to_crs(4326).iloc[0]
    return poly


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracts", required=True, help="GeoJSON/GPKG with HVI (must have GEOID, HVI)")
    ap.add_argument("--sites", required=True, help="Cooling sites GeoJSON (EPSG:4326)")
    ap.add_argument("--minutes", type=int, default=15)
    ap.add_argument("--out", default="data/processed/coverage.gpkg")
    args = ap.parse_args()

    # Load inputs and normalize CRS to WGS84
    tracts = gpd.read_file(args.tracts)
    tracts = tracts.to_crs(4326)

    sites = gpd.read_file(args.sites)
    if sites.crs is None:
        sites.set_crs(4326, inplace=True)
    else:
        sites = sites.to_crs(4326)

    if len(sites) == 0:
        raise SystemExit("No sites found in the provided GeoJSON.")

    # Build a SMALL AOI around actual sites (much faster than whole county)
    sites_m  = sites.to_crs(3857)
    tracts_m = tracts.to_crs(3857)

    walk_m_per_min = 80  # ~4.8 km/h
    clip_radius = (args.minutes * walk_m_per_min) * 2  # generous area around sites

    # Buffer sites, intersect with dissolved tracts to keep within study area
    clip_m = sites_m.buffer(clip_radius).union_all().intersection(
        tracts_m.dissolve().geometry.iloc[0]
    )
    clip = gpd.GeoSeries([clip_m], crs=3857).to_crs(4326).iloc[0]

    # Pull walk network just for this clipped AOI (osmnx 2.x)
    G = ox.graph_from_polygon(clip, network_type="walk", retain_all=False)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    # Build isochrones for each site
    polys = []
    for _, row in sites.iterrows():
        try:
            node = ox.nearest_nodes(G, float(row.geometry.x), float(row.geometry.y))
            poly = isochrone_polygon(G, node, minutes=args.minutes)
            polys.append(poly)
        except Exception as e:
            print(f"Skipping site due to error: {e}", file=sys.stderr)

    if not polys:
        raise SystemExit("No coverage polygons were produced. Check your sites geometry.")

    cover = gpd.GeoSeries(polys, crs=4326)
    coverage_union = cover.union_all()  # replaces deprecated .unary_union
    coverage_gdf = gpd.GeoDataFrame(geometry=[coverage_union], crs=4326)

    # Flag tracts by centroid coverage
    # (centroids computed in a projected CRS to avoid geodetic centroid quirks)
    tr_m = tracts.to_crs(3857).copy()
    tr_m["centroid"] = tr_m.geometry.centroid
    tr_cent = tr_m[["GEOID", "centroid"]].copy().set_geometry("centroid").to_crs(4326)
    tr_cent["covered"] = tr_cent.geometry.within(coverage_union)

    tracts_with_cov = tracts.merge(tr_cent[["GEOID", "covered"]], on="GEOID", how="left")
    tracts_with_cov["covered"] = tracts_with_cov["covered"].fillna(False)

    # Write outputs
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    coverage_gdf.to_file(out, layer="coverage", driver="GPKG")
    tracts_with_cov.to_file(out, layer="tracts_with_coverage", driver="GPKG")
    print(f"Wrote {out} with layers: coverage, tracts_with_coverage")


if __name__ == "__main__":
    main()
