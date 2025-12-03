#!/usr/bin/env python3
import argparse, re
from pathlib import Path
import pandas as pd
import geopandas as gpd
import numpy as np

# Helpers
def pick(df, *cands):
    cols = {c.lower(): c for c in df.columns}
    for cand in cands:
        if cand in cols:
            return cols[cand]
    # fuzzy contains
    for k,v in cols.items():
        if any(c in k for c in cands):
            return v
    raise KeyError(f"None of {cands} found in: {list(df.columns)[:8]} ...")

def as_num(s):
    return pd.to_numeric(s, errors="coerce").replace([np.inf,-np.inf], np.nan)

def norm01(series):
    s = as_num(series)
    lo, hi = np.nanpercentile(s, [1, 99])
    s = s.clip(lo, hi)
    return (s - s.min()) / (s.max() - s.min() + 1e-12)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", default="data/raw/hhi_2024_zcta.xlsx")
    ap.add_argument("--xwalk", default="data/raw/zip_tract_xwalk.csv")
    ap.add_argument("--tracts", default="data/processed/tracts_hvi.geojson")
    ap.add_argument("--county_fips", default="06073", help="5-digit county FIPS (San Diego=06073)")
    ap.add_argument("--out_csv", default="data/processed/hhi_tract.csv")
    ap.add_argument("--out_geojson", default="data/processed/tracts_hvi_hhi.geojson")
    args = ap.parse_args()

    # Read HHI (ZCTA)
    print("[hhi] reading:", args.excel)
    df = pd.read_excel(args.excel, dtype=str)

    zcol = pick(df, "zcta5", "zcta", "zip", "zipcode")
    df[zcol] = df[zcol].str.extract(r"(\d{5})")
    df = df[df[zcol].notna()].copy()
    df[zcol] = df[zcol].astype(str).str.zfill(5)

    rank_col = None
    for c in df.columns:
        lc = c.lower()
        if ("overall" in lc) and ("rank" in lc):
            rank_col = c
            break
    if rank_col is not None:
        print(f"[hhi] using rank column: {rank_col}")
        hhi01 = 1.0 - norm01(df[rank_col])  # higher = worse; invert rank so higher=more risk
    else:
        score_col = None
        for c in df.columns:
            lc = c.lower()
            if ("overall" in lc) and (("score" in lc) or ("index" in lc)):
                score_col = c
                break
        if score_col is None:
            # fallback: first numeric column after zcta
            num_cols = [c for c in df.columns if c != zcol]
            for c in num_cols:
                if pd.api.types.is_numeric_dtype(as_num(df[c])):
                    score_col = c; break
        print(f"[hhi] using score column: {score_col}")
        hhi01 = norm01(df[score_col])

    zcta_hhi = df[[zcol]].copy()
    zcta_hhi["CDC_HHI"] = hhi01.astype(float)

    # Read crosswalk ZIP -> TRACT
    print("[hhi] reading ZIP-TRACT crosswalk:", args.xwalk)
    xw = pd.read_csv(args.xwalk, dtype=str)

    zip_c  = pick(xw, "zip", "zipcode", "zcta", "zcta5")
    tr_c   = pick(xw, "tract", "tract_geoid", "geoid", "census_tract")
    # a weight column for apportioning (RES_RATIO or TOT_RATIO or RESIDENTIAL_RATIO etc.)
    try:
        w_c = pick(xw, "res_ratio", "tot_ratio", "residential_ratio", "res_ratio_1")
    except KeyError:
        # if none exist, use equal weights
        xw["__w__"] = 1.0
        w_c = "__w__"

    # standardize
    xw["ZIP"]   = xw[zip_c].str.extract(r"(\d{5})")
    xw["TRACT"] = xw[tr_c].str.extract(r"(\d{11})")
    xw["W"]     = as_num(xw[w_c]).fillna(0.0)

    # limit to county if requested
    if args.county_fips:
        xw = xw[xw["TRACT"].str.startswith(args.county_fips)]

    # Allocate ZCTA HHI to tracts 
    m = xw.merge(zcta_hhi, left_on="ZIP", right_on=zcol, how="left")
    m["w_hhi"] = m["W"] * m["CDC_HHI"]
    g = (m.groupby("TRACT", as_index=False)
           .agg(CDC_HHI=("w_hhi","sum"), W=("W","sum")))
    g["CDC_HHI"] = (g["CDC_HHI"] / (g["W"] + 1e-12)).fillna(0.0)

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    g.rename(columns={"TRACT":"GEOID"}).to_csv(out_csv, index=False)
    print(f"[hhi] wrote tract CSV → {out_csv} ({len(g)} rows)")

    # Merge into your tracts for convenience 
    tr = gpd.read_file(args.tracts)
    tr = tr.merge(g.rename(columns={"TRACT":"GEOID"}), on="GEOID", how="left")
    out_geojson = Path(args.out_geojson)
    tr.to_file(out_geojson, driver="GeoJSON")
    print(f"[hhi] wrote merged tracts → {out_geojson} with CDC_HHI column")

if __name__ == "__main__":
    main()
