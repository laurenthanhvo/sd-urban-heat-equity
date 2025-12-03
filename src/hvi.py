#!/usr/bin/env python3
import argparse
import pandas as pd
import geopandas as gpd
import numpy as np
from pathlib import Path

def zscore(s):
    return (s - s.mean()) / (s.std() + 1e-9)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True, help="Parquet from src.features")
    ap.add_argument("--acs", required=True, help="Parquet from fetch_acs.py")
    ap.add_argument("--out", required=True, help="GeoJSON of tracts with HVI")
    ap.add_argument("--tracts_geom", required=True, help="Tracts geometry file (e.g., tracts_sd.gpkg)")
    args = ap.parse_args()

    feat = pd.read_parquet(args.features)
    acs = pd.read_parquet(args.acs)

    df = feat.merge(acs, on="GEOID", how="left")

    exp_cols = ["LST_mean","LST_p95","NDVI_med"]
    sen_cols = ["pct_age65p","no_vehicle","limited_english"]
    cap_cols = ["renters_pct","crowding_pct","income_median_neg"]

    Xexp = df[exp_cols].apply(zscore)
    Xsen = df[sen_cols].apply(zscore)
    Xcap = df[cap_cols].apply(zscore)
    HVI = 0.4*Xexp.mean(1) + 0.4*Xsen.mean(1) + 0.2*Xcap.mean(1)
    df["HVI"] = (HVI - HVI.min())/(HVI.max()-HVI.min() + 1e-9)

    g = gpd.read_file(args.tracts_geom)
    g = g[["GEOID","geometry"]]
    gdf = g.merge(df, on="GEOID", how="left")
    gdf = gdf.set_crs(g.crs)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(args.out, driver="GeoJSON")
    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
