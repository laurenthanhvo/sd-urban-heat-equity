# Extreme Heat Vulnerability Index (HVI) & Cooling Center Optimization — San Diego

This is a complete starter kit for building a tract-level **Heat Vulnerability Index (HVI)** and running a **location-allocation optimization** to place new cooling resources. Tailored for **macOS + VS Code**.

## Setup (macOS + VS Code)

1) Install **Homebrew** (if not installed):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

2) Install **Miniforge (Conda)**:
- Download the macOS installer (.pkg) from: https://github.com/conda-forge/miniforge/releases
- Run it, then:
```bash
conda init zsh
exec zsh
```

3) Open this folder in **VS Code** and install extensions:
- Python
- Jupyter
- YAML

4) Create the environment:
```bash
mamba env create -f environment.yml   # or: conda env create -f environment.yml
conda activate heat
python -m ipykernel install --user --name heat --display-name "Python (heat)"
```

## Quick sanity check (no real data)

```bash
python scripts/make_synthetic_demo.py
streamlit run app/streamlit_app.py
```

## Real data pipeline (San Diego)

1) **Tracts (TIGER/Line)**:
```bash
python scripts/download_census_tracts.py --state 06 --county 073 --year 2023
```
Creates: `data/processed/tracts_sd.gpkg`

2) **ACS demographics (2023 5-year)**:
```bash
export CENSUS_API_KEY="YOUR_KEY"   # optional
python scripts/fetch_acs.py --year 2023 --state 06 --county 073
```
Creates: `data/processed/acs_tracts_sd.parquet`

3) **Cooling sites CSV → GeoJSON**:
- Put your CSV at `data/raw/cooling_sites.csv` with columns: `name,address,city,state,zip`
```bash
python scripts/geocode_sites.py --in_csv data/raw/cooling_sites.csv --out data/processed/cooling_sites.geojson
```

4) **Satellite LST/NDVI**:
- Prefer Google Earth Engine to export summer LST (and NDVI) as GeoTIFFs:
  - Put them in `data/raw/SD_LST_Summer.tif` and `data/raw/SD_NDVI_Summer.tif`

5) **Features → HVI**:
```bash
python -m src.features   --tracts data/processed/tracts_sd.gpkg   --lst data/raw/SD_LST_Summer.tif   --ndvi data/raw/SD_NDVI_Summer.tif   --out data/processed/tract_features.parquet

python -m src.hvi   --features data/processed/tract_features.parquet   --acs data/processed/acs_tracts_sd.parquet   --tracts_geom data/processed/tracts_sd.gpkg   --out data/processed/tracts_hvi.geojson
```

6) **Coverage (walk isochrones, 15 min)**:
```bash
python -m src.coverage   --tracts data/processed/tracts_hvi.geojson   --sites data/processed/cooling_sites.geojson   --minutes 15   --out data/processed/coverage.gpkg
```

7) **Optimization (MCLP)**:
- Prepare `data/processed/candidate_sites.geojson` (geocode any candidate addresses similarly)
```bash
python -m src.optimize   --tracts data/processed/tracts_hvi.geojson   --sites data/processed/candidate_sites.geojson   --k 10   --minutes 15   --out data/processed/optimized_sites.geojson
```

8) **App**:
```bash
streamlit run app/streamlit_app.py
```

## Notes
- OSMnx downloads walking networks on demand—first run can be slow.
- Nominatim geocoding is rate-limited; be patient or split files.
- Prefer GEE for raster processing speed and quality.

