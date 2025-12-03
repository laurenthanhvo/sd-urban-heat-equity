# Urban Heat Vulnerability & Cooling Equity — San Diego, CA

This repository contains the code for an **urban heat vulnerability and cooling-equity analysis for San Diego County**. The project:

* Builds a tract-level **Extreme Heat Vulnerability Index (HVI)** using demographics, land surface temperature (LST), and greenness (NDVI).
* Uses a **Poisson generalized linear model (GLM)** to relate tract-level heat-health events to environmental and social risk factors, and converts predicted rates into 0–1 risk scores.
* Computes **walk-time coverage** to existing and candidate cooling sites using the pedestrian street network.
* Solves a **k-facility placement problem** to prioritize locations for new cooling centers.
* Serves an **interactive Streamlit app** to explore vulnerability, coverage, and optimized sites.

Tech stack: **Python** (`pandas`, `GeoPandas`, `statsmodels`, `OSMnx`, `NetworkX`), **Streamlit**, **Folium**, **Google Earth Engine** (for LST/NDVI preprocessing).

---

## 1. Environment Setup (macOS + VS Code)

These steps assume macOS and VS Code, but any recent Python 3.10+ setup should work.

### 1.1 Homebrew (optional but recommended)

If you don’t have Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1.2 Miniforge / Conda

Install **Miniforge** (Conda-based):

1. Download the macOS installer (`.pkg`) from
   [https://github.com/conda-forge/miniforge/releases](https://github.com/conda-forge/miniforge/releases)
2. Run the installer, then in a new terminal:

```bash
conda init zsh
exec zsh
```

### 1.3 Create the project environment

From the repo root:

```bash
mamba env create -f environment.yml    # or: conda env create -f environment.yml
conda activate heat
python -m ipykernel install --user --name heat --display-name "Python (heat)"
```

If `mamba` is not installed:

```bash
conda install -c conda-forge mamba
```

---

## 2. Project Layout

Key pieces of the repo:

* `app/streamlit_app.py` – main Streamlit application (HVI map, coverage, and optimization views).
* `data/`

  * `raw/` – raw inputs (LST/NDVI rasters, CDC event data, cooling-site CSVs, etc.).
  * `processed/` – tract geometries, joined feature tables, HVI outputs, network coverage, and optimized sites.
* `notebooks/` – exploratory data analysis, model fitting (Poisson GLM), and intermediate checks.
* `src/` (if present) – reusable helpers for loading data, computing features, coverage, and optimization.
* `.gitignore` – configured not to track large rasters or private data.

Exact notebook/module names may differ, but the workflow below matches the logic used in the project.

---

## 3. Data Requirements

Because of file size and privacy, **raw data is not stored in this GitHub repo**. To fully reproduce the pipeline you will need to obtain:

### 3.1 LST & NDVI (summer)

* Source: **Landsat 8/9** via **Google Earth Engine**.
* Export tract-scale or raster LST and NDVI for summer months.
* Save rasters to:

  * `data/raw/SD_LST_Summer.tif`
  * `data/raw/SD_NDVI_Summer.tif`

### 3.2 Demographics (ACS 5-year)

* Source: **American Community Survey 5-year estimates (2023)**.
* Geography: census tracts for **California, San Diego County** (`state=06`, `county=073`).
* Recommended storage: `data/raw/acs_tracts_sd.csv` or a similar file read by the notebooks.

### 3.3 Heat-health events (CDC Heat & Health Tracker)

* Source: **CDC Heat & Health Tracker** (emergency department visits for heat-related illness).
* Original data is often at **ZIP code** level. In this project it is **re-keyed from ZIP to census tracts** using spatial joins and area weighting.
* Store as e.g. `data/raw/cdc_heat_events_sd.csv`.

### 3.4 Cooling sites and candidate locations

* CSV with known or proposed cooling locations (libraries, rec centers, etc.), e.g.
  `data/raw/cooling_sites.csv`
  with at least `name,address,city,state,zip`.
* These are geocoded to points (lat/long) using a geocoding service (e.g., Nominatim or another provider).

### 3.5 Street network (walkability)

* Obtained on the fly via **OSMnx**, which downloads OpenStreetMap walking networks for the study area.
* No upfront files required; expect first-run downloads to take longer.

---

## 4. Analysis Workflow

The analysis is structured around four main steps.

### 4.1 Build tract-level features

**Geometries & joins**

* Load **census tract geometries** for San Diego County.
* Standardize all layers to a common **CRS** and clean geometries.

**Environmental features**

* Overlay **LST** and **NDVI** rasters on tract polygons.
* Aggregate to tract-level summaries (e.g., mean summer LST, mean NDVI).

**Social vulnerability**

Join ACS variables such as:

* % older adults
* % children
* % low-income households
* % people of color
* housing and AC-related variables (where available).

**Health outcomes**

Re-key CDC heat-related ED visits from ZIP to tract:

* Spatially intersect ZIP polygons and tracts.
* Allocate counts proportionally (e.g., by population or area).
* Compute a tract-level outcome (events per population, per season).

Intermediate outputs are saved under `data/processed/` (e.g., `tract_features.parquet`).

### 4.2 Poisson GLM & Heat Vulnerability Index

Using `statsmodels`, the project fits a **Poisson generalized linear model** of the form:

> Heat events ~ exp(β₀ + β₁ · LST + β₂ · NDVI + …)

* The model uses tract-level counts as the outcome and may include an **offset** for population.
* Coefficients provide interpretable effect sizes for each vulnerability factor.
* Predicted event rates are **rescaled to a 0–1 index**, forming the **Heat Vulnerability Index (HVI)** used in the map and optimization.

The resulting tract-level GeoDataFrame is written as, e.g., `data/processed/tracts_hvi.geojson`.

### 4.3 Walk-time coverage (walkability)

To measure access to cooling resources:

* Use **OSMnx** to download a **pedestrian network** for San Diego.
* Convert to a **NetworkX** graph and project to a metric CRS.
* For each tract centroid and each cooling site:

  * Compute **shortest-path travel time** on the walking network.
  * Derive indicators such as “within 15-minute walk of any cooling site”.
* Aggregate to tract-level coverage metrics (e.g., fraction of vulnerable population with access).

Outputs (e.g., `coverage.gpkg`) feed directly into the dashboard.

### 4.4 k-facility placement optimization

To identify the best places for new cooling centers:

* Formulate a **k-facility / location-allocation** problem:

  * **Candidate facilities** = potential cooling sites.
  * **Demand points** = tracts weighted by HVI and/or population.
  * **Objective** = maximize covered vulnerable population within a given walk time.
* Solve using a small optimization routine (e.g., integer programming or greedy heuristic) over candidate sites.
* Save selected facility locations to, e.g., `data/processed/optimized_sites.geojson`.

---

## 5. Running the Streamlit App

Once the environment is set up and the processed data files exist in `data/processed/`, you can run:

```bash
conda activate heat
streamlit run app/streamlit_app.py
```

By default, Streamlit prints a local URL such as `http://localhost:8501`. Open that in a browser.

The app exposes:

* **HVI map** – tract-level risk scores shaded by vulnerability.
* **Coverage view** – shows access to existing cooling sites (e.g., 15-minute walk).
* **Optimization view** – visualizes the selected `k` new cooling sites and how they improve coverage.

---

## 6. Notes & Caveats

* **Large rasters are not tracked in Git**
  The raw LST/NDVI GeoTIFFs are large (>100 MB each) and should live in `data/raw/` but are **not committed to GitHub**. If you clone this repo, you must supply your own rasters at:

  * `data/raw/SD_LST_Summer.tif`
  * `data/raw/SD_NDVI_Summer.tif`

* **CDC Heat & Health Tracker data** may have usage or privacy restrictions. This repository does **not** redistribute original line-level records.

* **Network downloads**: OSMnx calls OpenStreetMap/Nominatim APIs; first-time runs can be slow and are subject to rate limits. For larger jobs, consider caching graphs to disk.

* This codebase is intended primarily as a **research / decision-support prototype**, not a production planning tool. Model choices, weights, and thresholds should be interpreted in consultation with local stakeholders and domain experts.

---

## 7. Contact

For questions about this project or collaboration on extreme heat and cooling-equity work in San Diego, please reach out to:

**Lauren Vo** — `ddjapri@ucsd.edu` (replace with your preferred contact)
