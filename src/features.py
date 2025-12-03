#!/usr/bin/env python3
import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import rioxarray as rxr
from rasterstats import zonal_stats
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracts", required=True, help="GPKG/GeoJSON of tracts (must have GEOID)")
    ap.add_argument("--lst", required=True, help="GeoTIFF of summer LST (Kelvin)")
    ap.add_argument("--ndvi", default="", help="GeoTIFF of NDVI (optional)")
    ap.add_argument("--out", required=True, help="Parquet of features")
    args = ap.parse_args()

    tracts = gpd.read_file(args.tracts)
    lst = rxr.open_rasterio(args.lst).squeeze()
    if tracts.crs != lst.rio.crs:
        tracts = tracts.to_crs(lst.rio.crs)

    stats = zonal_stats(tracts, lst.values, affine=lst.rio.transform(),
                        stats=['mean','percentile_95'], nodata=None)
    df = pd.DataFrame(stats).rename(columns={"mean":"LST_mean","percentile_95":"LST_p95"})

    if args.ndvi:
        ndvi = rxr.open_rasterio(args.ndvi).squeeze()
        if tracts.crs != ndvi.rio.crs:
            tracts_ndvi = tracts.to_crs(ndvi.rio.crs)
        else:
            tracts_ndvi = tracts
        ndvi_stats = zonal_stats(tracts_ndvi, ndvi.values, affine=ndvi.rio.transform(),
                                 stats=['median'], nodata=None)
        df["NDVI_med"] = pd.DataFrame(ndvi_stats)["median"]
    else:
        df["NDVI_med"] = np.nan

    out = pd.concat([tracts[["GEOID"]].reset_index(drop=True), df], axis=1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
