#!/usr/bin/env python3
import argparse
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import geopandas as gpd
from shapely.geometry import Point
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_csv", required=True, help="CSV with columns: name,address,city,state,zip")
    ap.add_argument("--out", default="data/processed/cooling_sites.geojson")
    args = ap.parse_args()

    df = pd.read_csv(args.in_csv)
    geolocator = Nominatim(user_agent="sd-heat-hvi")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

    lats, lons = [], []
    for _, row in df.iterrows():
        q = f"{row['address']}, {row.get('city','')}, {row.get('state','')}, {row.get('zip','')}"
        loc = geocode(q)
        if loc is None:
            lats.append(None); lons.append(None)
        else:
            lats.append(loc.latitude); lons.append(loc.longitude)

    df["lat"] = lats; df["lon"] = lons
    gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) if pd.notna(xy[0]) and pd.notna(xy[1]) else None for xy in zip(df["lon"], df["lat"])], crs=4326)
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, driver="GeoJSON")
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
