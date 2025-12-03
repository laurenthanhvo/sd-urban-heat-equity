#!/usr/bin/env python3
# Generate a tiny synthetic dataset for quick sanity checks.
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Polygon, Point
from pathlib import Path

OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

origin_x, origin_y = -13000000, 4000000  # EPSG:3857 coords
size = 2000  # 2 km squares
tracts = []
geoid = 100000
for i in range(3):
    for j in range(3):
        x0 = origin_x + j*size
        y0 = origin_y + i*size
        poly = Polygon([(x0,y0),(x0+size,y0),(x0+size,y0+size),(x0,y0+size)])
        tracts.append({"GEOID": str(geoid), "geometry": poly})
        geoid += 1

g = gpd.GeoDataFrame(tracts, crs=3857)

np.random.seed(42)
g["LST_mean"] = np.random.uniform(300, 315, len(g))
g["LST_p95"] = g["LST_mean"] + np.random.uniform(2, 5, len(g))
g["NDVI_med"] = np.random.uniform(0.1, 0.6, len(g))
g["TreeCanopy_pct"] = np.random.uniform(5, 40, len(g))
g["Impervious_pct"] = np.random.uniform(20, 95, len(g))
g["pct_age65p"] = np.random.uniform(8, 25, len(g))
g["no_vehicle"] = np.random.uniform(3, 20, len(g))
g["limited_english"] = np.random.uniform(5, 30, len(g))
g["renters_pct"] = np.random.uniform(30, 80, len(g))
g["crowding_pct"] = np.random.uniform(2, 15, len(g))
g["income_median_neg"] = np.random.uniform(0, 1, len(g))

exp_cols = ["LST_mean","LST_p95","NDVI_med","TreeCanopy_pct","Impervious_pct"]
sen_cols = ["pct_age65p","no_vehicle","limited_english"]
cap_cols = ["renters_pct","crowding_pct","income_median_neg"]

def zscore(s):
    return (s - s.mean()) / (s.std() + 1e-9)

Xexp = g[exp_cols].apply(zscore)
Xsen = g[sen_cols].apply(zscore)
Xcap = g[cap_cols].apply(zscore)
HVI = 0.4*Xexp.mean(1) + 0.4*Xsen.mean(1) + 0.2*Xcap.mean(1)
g["HVI"] = (HVI - HVI.min())/(HVI.max()-HVI.min() + 1e-9)

g.to_file(OUT_DIR / "tracts_hvi.geojson", driver="GeoJSON")

cx = origin_x + size
cy = origin_y + size
sites = gpd.GeoDataFrame({
    "name": ["Site A","Site B","Site C"],
    "geometry": [Point(cx, cy), Point(cx+1500, cy+500), Point(cx-1000, cy+1000)]
}, crs=3857)

sites.to_file(OUT_DIR / "cooling_sites.geojson", driver="GeoJSON")
print("Wrote data/processed/tracts_hvi.geojson and cooling_sites.geojson")
