#!/usr/bin/env python3
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
import shutil

IN_HVI  = Path("data/processed/tracts_hvi.geojson")    
FEATS   = Path("data/processed/tract_features.parquet")  
OUT_HVI = IN_HVI                                      

def z(x):
    x = pd.Series(x).astype(float)
    return (x - x.mean()) / (x.std(ddof=0) + 1e-9)

def minmax01(x):
    x = pd.Series(x).astype(float)
    lo, hi = np.nanpercentile(x, [1, 99])
    x = x.clip(lo, hi)
    return (x - x.min()) / (x.max() - x.min() + 1e-9)

def main():
    assert IN_HVI.exists(), f"Missing {IN_HVI}"
    g = gpd.read_file(IN_HVI)

    # Safe backup of the original file 
    backup = IN_HVI.with_name(IN_HVI.stem + "_backup.geojson")
    shutil.copy(IN_HVI, backup)
    print(f"Backed up original HVI → {backup}")

    gi = g.set_index("GEOID", drop=False)

    # Try to grab per-tract NDVI/LST if present
    ndvi = None
    lst  = None
    if FEATS.exists():
        f = pd.read_parquet(FEATS)
        f = f.set_index("GEOID")
        for c in f.columns:
            if c.lower().startswith("ndvi"):
                ndvi = f[c]
                break
        for c in f.columns:
            if c.lower().startswith("lst"):
                lst = f[c]
                break

    # Reasonable fallbacks if features are missing
    if ndvi is None:
        ndvi = pd.Series(0.35, index=gi.index, name="NDVI_fallback")
    else:
        ndvi = ndvi.reindex(gi.index)
    if lst is None:
        # Use current HVI shape as a weak proxy for relative heat
        lst = gi["HVI"]
    else:
        lst = lst.reindex(gi.index)

    ndvi01     = minmax01(ndvi)
    inv_canopy = 1.0 - ndvi01
    built_heat = z(lst) - z(ndvi01)     # hotter & barer → larger score
    built01    = minmax01(built_heat)

    # Blend with your existing HVI (keep existing HVI dominant)
    hvi_base01 = minmax01(gi["HVI"])
    hvi2       = 0.60 * hvi_base01 + 0.20 * inv_canopy + 0.20 * built01
    hvi2_01    = minmax01(hvi2)

    # Write back to the original (non-indexed) GeoDataFrame and save
    g["HVI"] = hvi2_01.reindex(g["GEOID"]).values

    # Ensure don't write an index column that collides with GEOID
    g = g.reset_index(drop=True)
    g.to_file(OUT_HVI, driver="GeoJSON")
    print(f"Upgraded HVI written → {OUT_HVI}")

if __name__ == "__main__":
    main()
