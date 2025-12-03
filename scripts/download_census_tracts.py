#!/usr/bin/env python3
import argparse, io, zipfile, sys
import geopandas as gpd
import requests
from pathlib import Path

# Download Census tracts for a given state/year, then filter a target county.
# Defaults: California (06), San Diego County (073), 2023.
# Outputs: data/processed/tracts_sd.gpkg

URL_FMT = "https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/tl_{year}_{state}_tract.zip"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="06", help="State FIPS (e.g., 06 = CA)")
    ap.add_argument("--county", default="073", help="County FIPS (e.g., 073 = San Diego)")
    ap.add_argument("--year", default="2023", help="TIGER year (e.g., 2023)")
    ap.add_argument("--out", default="data/processed/tracts_sd.gpkg")
    args = ap.parse_args()

    url = URL_FMT.format(year=args.year, state=args.state)
    print(f"Downloading: {url}")
    r = requests.get(url, timeout=300)
    r.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(r.content))
    tmpdir = Path("data/raw/tiger_tracts")
    tmpdir.mkdir(parents=True, exist_ok=True)
    z.extractall(tmpdir)

    shp = None
    for f in tmpdir.iterdir():
        if f.suffix.lower() == ".shp":
            shp = f
            break
    if shp is None:
        print("Could not find shapefile in the zip.", file=sys.stderr)
        sys.exit(1)

    g = gpd.read_file(shp)
    g = g[g["COUNTYFP"] == str(args.county)]
    g = g.to_crs(3857)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(out, driver="GPKG")
    print(f"Wrote {out} with {len(g)} tracts.")

if __name__ == "__main__":
    main()
