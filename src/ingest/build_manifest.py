"""Build raw data manifests for PM2.5 ground data and GEE extracts."""
from pathlib import Path
from datetime import datetime
import pandas as pd

GEE_DATASETS = [
    "s5p_no2", "s5p_co", "s5p_so2", "s5p_hcho", "s5p_aer_ai",
    "maiac_aod", "era5_land", "era5_blh", "cams_aod",
]

def build_pm25_manifest() -> pd.DataFrame:
    """Build manifest for PM2.5 hourly files."""
    rows = []
    for f in sorted(Path("data/raw/pm25_hourly").glob("*.csv")):
        df = pd.read_csv(f, parse_dates=["timestamp_ist"])
        rows.append({
            "file": f.name,
            "source": "xkdr_cpcb",
            "station_id": f.stem,
            "row_count": len(df),
            "date_start": str(df["timestamp_ist"].min())[:10],
            "date_end": str(df["timestamp_ist"].max())[:10],
            "retrieval_date": datetime.now().strftime("%Y-%m-%d"),
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv("data/raw/pm25_manifest.csv", index=False)
    return manifest

def build_gee_manifest() -> pd.DataFrame:
    """Build manifest for GEE extraction files."""
    rows = []
    for dataset in GEE_DATASETS:
        p = Path(f"data/raw/gee_extracts/{dataset}")
        files = sorted(p.glob("*.csv")) if p.exists() else []
        n_rows = sum(len(pd.read_csv(f)) for f in files)
        rows.append({
            "dataset": dataset,
            "months_done": len(files),
            "months_total": 48,
            "total_rows": n_rows,
            "complete": len(files) == 48,
            "retrieval_date": datetime.now().strftime("%Y-%m-%d"),
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv("data/raw/gee_manifest.csv", index=False)
    return manifest

if __name__ == "__main__":
    pm25 = build_pm25_manifest()
    total_rows = pm25["row_count"].sum()
    print(f"PM2.5: {len(pm25)} stations, {total_rows:,} rows")

    gee = build_gee_manifest()
    print("\nGEE extractions:")
    print(gee[["dataset", "months_done", "months_total", "total_rows"]].to_string(index=False))
