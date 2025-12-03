#!/usr/bin/env python3
import argparse, os, sys, json
import pandas as pd
import requests
from pathlib import Path
import certifi

# Robust ACS 5-year pull for tract-level indicators (San Diego default)
# Handles missing columns & converts numerics only if present.

AGE65_VARS = [
    "B01001_020E","B01001_021E","B01001_022E","B01001_023E","B01001_024E","B01001_025E",
    "B01001_044E","B01001_045E","B01001_046E","B01001_047E","B01001_048E","B01001_049E",
]
LEP_VARS = ["C16002_004E","C16002_007E","C16002_010E","C16002_013E"]
CROWD_VARS = ["B25014_005E","B25014_006E","B25014_007E","B25014_011E","B25014_012E","B25014_013E"]
RENT_VARS = ["B25003_002E","B25003_003E"]  # owner, renter
CORE_VARS = ["B01003_001E","B08201_002E","B19013_001E"]  # pop, no_vehicle HHs, median income

ALL_VARS = CORE_VARS + AGE65_VARS + LEP_VARS + CROWD_VARS + RENT_VARS

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2023", help="ACS 5-year vintage (e.g., 2023 = 2019–2023)")
    ap.add_argument("--state", default="06", help="State FIPS (06=CA)")
    ap.add_argument("--county", default="073", help="County FIPS (073=San Diego)")
    ap.add_argument("--out", default="data/processed/acs_tracts_sd.parquet")
    ap.add_argument("--api_key", default=os.environ.get("CENSUS_API_KEY", ""))
    args = ap.parse_args()

    base = f"https://api.census.gov/data/{args.year}/acs/acs5"
    get_fields = ",".join(["NAME"] + ALL_VARS)
    params = {"get": get_fields, "for": "tract:*", "in": f"state:{args.state} county:{args.county}"}
    if args.api_key: params["key"] = args.api_key

    print("Querying ACS…")
    try:
        r = requests.get(base, params=params, timeout=120, verify=certifi.where())
    except Exception as e:
        print(f"TLS problem ({e}); retrying without verify just for this call…", file=sys.stderr)
        r = requests.get(base, params=params, timeout=120, verify=False)
    if r.status_code != 200:
        print(f"ACS request failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
        sys.exit(1)

    data = r.json()
    if not isinstance(data, list) or not data:
        print("Unexpected ACS response format.", file=sys.stderr); sys.exit(1)
    cols, rows = data[0], data[1:]
    df = pd.DataFrame(rows, columns=cols)

    # Ensure every requested var exists; if not, create as NA
    for v in ALL_VARS:
        if v not in df.columns:
            df[v] = pd.NA

    # Convert numerics safely (skip NAME/state/county/tract)
    for c in [c for c in df.columns if c not in ("NAME","state","county","tract")]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # GEOID (11-digit)
    df["GEOID"] = df["state"] + df["county"] + df["tract"]

    # Aggregates
    df["population"] = df["B01003_001E"]
    df["age_65p_sum"] = df[AGE65_VARS].sum(axis=1, min_count=1)
    df["lep_sum"] = df[LEP_VARS].sum(axis=1, min_count=1)
    df["crowding_sum"] = df[CROWD_VARS].sum(axis=1, min_count=1)

    # Percents (guard against divide-by-zero)
    pop = df["population"].replace({0: pd.NA})
    df["pct_age65p"] = 100.0 * df["age_65p_sum"] / pop
    df["no_vehicle"] = 100.0 * df["B08201_002E"] / pop
    df["limited_english"] = 100.0 * df["lep_sum"] / pop
    denom_hh = (df["B25003_002E"] + df["B25003_003E"]).replace({0: pd.NA})
    df["renters_pct"] = 100.0 * df["B25003_003E"] / denom_hh
    df["crowding_pct"] = 100.0 * df["crowding_sum"] / pop

    # Income inverse (lower income → higher vulnerability proxy)
    df["income_median_neg"] = 1.0 / (df["B19013_001E"] + 1e-6)

    keep = ["GEOID","population","pct_age65p","no_vehicle","limited_english",
            "renters_pct","crowding_pct","income_median_neg"]
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    df[keep].to_parquet(out, index=False)
    print(f"Wrote {out} ({len(df)} tracts).")

if __name__ == "__main__":
    main()
