#!/usr/bin/env python3
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

try:
    import statsmodels.api as sm
except Exception:
    sm = None

TRACTS = Path("data/processed/tracts_hvi.geojson")
HEALTH = Path("data/raw/health_outcomes.csv")
OUT    = Path("data/processed/tracts_risk.geojson")

def minmax01(x):
    x = pd.Series(x, dtype="float64")
    lo, hi = np.nanpercentile(x, [1, 99])
    x = x.clip(lo, hi)
    rng = (x.max() - x.min())
    return (x - x.min()) / (rng + 1e-9)

def main():
    # Load tracts & ensure numeric HVI
    g = gpd.read_file(TRACTS).set_index("GEOID", drop=False)
    g["HVI"] = pd.to_numeric(g.get("HVI"), errors="coerce")

    if HEALTH.exists() and sm is not None:
        df = pd.read_csv(HEALTH, dtype={"GEOID": str}).set_index("GEOID")

        # numeric + clean
        df["events"] = pd.to_numeric(df.get("events"), errors="coerce")
        df["pop"]    = pd.to_numeric(df.get("pop"),    errors="coerce")

        # Build design on the same index
        X = pd.DataFrame({
            "intercept": 1.0,
            "hvi": g["HVI"].reindex(df.index) 
        }, index=df.index)

        y      = df["events"]
        offset = np.log(np.clip(df["pop"], 1e-9, np.inf))  # avoid -inf

        # Valid rows only (no NaN/inf in X, y, offset) and pop>0
        Xv      = X.copy()
        valid   = (
            np.isfinite(Xv.to_numpy()).all(axis=1)
            & np.isfinite(y.to_numpy())
            & np.isfinite(offset.to_numpy())
            & (df["pop"].to_numpy() > 0)
        )
        if valid.sum() == 0:
            # Not enough data; fall back to HVI proxy
            g["RISK"] = minmax01((g["HVI"].fillna(0))**1.5)
            g["RISK_src"] = "hvi_proxy"
        else:
            X_fit, y_fit, off_fit = X.loc[valid], y.loc[valid], offset.loc[valid]

            # Fit Poisson GLM
            res = sm.GLM(y_fit, X_fit, family=sm.families.Poisson(), offset=off_fit).fit()

            # Predict expected events for ALL rows (NaN where inputs missing)
            mu   = res.predict(X, offset=offset)  # aligned to df.index
            rate = (mu / df["pop"].replace(0, np.nan)) * 1e4  # events per 10k

            # Scale to 0–1 risk
            risk01 = minmax01(rate)

            # Write onto g by GEOID; fill gaps with an HVI-based proxy
            g["RISK"] = pd.Series(risk01, index=df.index).reindex(g.index)
            proxy = minmax01((g["HVI"].fillna(0))**1.5)
            g["RISK"] = g["RISK"].fillna(proxy)
            g["RISK_src"] = "glm_poisson"
    else:
        # No outcomes or statsmodels: transparent proxy based on HVI
        g["RISK"] = minmax01((g["HVI"].fillna(0))**1.5)
        g["RISK_src"] = "hvi_proxy"

    g = g.copy()
    g.index.name = None   # avoid duplicate 'GEOID' on write

    g.to_file(OUT, driver="GeoJSON")
    print(f"Wrote {OUT} with columns: RISK (0–1), RISK_src")

if __name__ == "__main__":
    main()
