"""Download and clean aggregate adult body-shape data from Hong Kong C&SD (HEA001).

Usage:
    python scripts\download_and_clean.py

This script will:
 - download the HEA001 table (attempts CSV download)
 - save raw file to data/raw/HEA001_raw.csv or .html
 - produce a cleaned CSV at data/cleaned/HEA001_cleaned.csv

Assumptions:
 - The web table at C&SD is identified by id=HEA001 and supports a CSV format query param.
 - We focus on adults aged 18-80 and sexes Male/Female.
 - Input files may be aggregates (age-group × sex). The cleaner will try to detect BMI/height/weight columns.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path
import requests
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "cleaned"
RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_URL = (
    "https://www.censtatd.gov.hk/en/web_table.html?id=HEA001&format=csv"
)


def download_url(url: str, dest: Path) -> Path:
    print(f"Downloading: {url}")
    resp = requests.get(url, timeout=30, headers={"User-Agent": "data-scraper/1.0"})
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    # If it looks like CSV, save as CSV
    if "text/csv" in content_type or url.lower().endswith(".csv"):
        dest.write_bytes(resp.content)
        return dest
    # Sometimes the endpoint returns CSV text even with text/html header
    text = resp.text
    # Heuristic: if it contains many commas and newline, assume CSV
    lines = text.splitlines()
    if len(lines) > 5 and any(
        (line.count(",") >= 1 for line in lines[:10])
    ):
        dest.write_text(text, encoding="utf-8")
        return dest

    # Otherwise save HTML and try to find a direct CSV link
    html_dest = dest.with_suffix(".html")
    html_dest.write_text(text, encoding="utf-8")
    print(f"Saved HTML to {html_dest}. Attempting to find CSV links inside HTML...")
    m = re.search(r'href=["\'](?P<h>[^"\']+\.csv)["\']', text, re.IGNORECASE)
    if m:
        csv_link = m.group("h")
        # make absolute if needed
        if csv_link.startswith("/"):
            csv_link = f"https://www.censtatd.gov.hk{csv_link}"
        print(f"Found CSV link: {csv_link}")
        resp2 = requests.get(csv_link, timeout=30, headers={"User-Agent": "data-scraper/1.0"})
        resp2.raise_for_status()
        dest.write_bytes(resp2.content)
        return dest

    raise RuntimeError("Could not locate CSV content from the provided URL; saved HTML for inspection.")


def parse_age_group_minmax(s: str) -> tuple[int | None, int | None]:
    s = str(s).strip()
    # examples: '18-24', '25-34', '80 and over', '80+'
    m = re.search(r"(\d{1,3})\s*[-–]\s*(\d{1,3})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{1,3})\s*\+", s)
    if m:
        v = int(m.group(1))
        return v, None
    m = re.search(r"(\d{1,3}).*(over|and over)", s.lower())
    if m:
        v = int(m.group(1))
        return v, None
    # single age
    m = re.search(r"^(\d{1,3})$", s)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


def filter_age_range(df: pd.DataFrame, age_col: str, min_age=18, max_age=80) -> pd.DataFrame:
    # Keep rows where the age group overlaps [min_age, max_age]
    def keep(s: str) -> bool:
        a, b = parse_age_group_minmax(s)
        if a is None:
            return False
        if b is None:
            b = 200
        return not (b < min_age or a > max_age)

    mask = df[age_col].astype(str).apply(keep)
    return df.loc[mask].reset_index(drop=True)


def detect_cols(df: pd.DataFrame) -> dict:
    cols = {"age": None, "sex": None, "bmi": None, "height": None, "weight": None}
    for c in df.columns:
        cl = c.lower()
        if cols["age"] is None and ("age" in cl or "age group" in cl):
            cols["age"] = c
        if cols["sex"] is None and any(k in cl for k in ("sex", "gender")):
            cols["sex"] = c
        if cols["bmi"] is None and "bmi" in cl:
            cols["bmi"] = c
        if cols["height"] is None and "height" in cl:
            cols["height"] = c
        if cols["weight"] is None and "weight" in cl:
            cols["weight"] = c
    return cols


def derive_bmi_from_height_weight(df: pd.DataFrame, hcol: str, wcol: str, newcol: str = "BMI") -> pd.DataFrame:
    # height expected in cm or m; weight in kg
    s = df.copy()
    # convert to numeric
    s[hcol] = pd.to_numeric(s[hcol], errors="coerce")
    s[wcol] = pd.to_numeric(s[wcol], errors="coerce")
    # assume height in cm if values > 3
    s["height_m"] = s[hcol].apply(lambda x: (x / 100) if x and x > 3 else x)
    s[newcol] = s[wcol] / (s["height_m"] ** 2)
    return s


def add_bmi_category(df: pd.DataFrame, bmi_col: str = "BMI") -> pd.DataFrame:
    s = df.copy()
    def cat(v):
        try:
            v = float(v)
        except Exception:
            return None
        if v < 18.5:
            return "Underweight"
        if v < 25:
            return "Normal"
        if v < 30:
            return "Overweight"
        return "Obese"

    s["BMI_category"] = s[bmi_col].apply(cat)
    return s


def clean_file(src: Path, dest: Path) -> Path:
    print(f"Loading raw file: {src}")
    # try read with pandas
    try:
        df = pd.read_csv(src)
    except Exception:
        df = pd.read_csv(src, encoding="utf-8", engine="python", error_bad_lines=False)

    cols = detect_cols(df)
    print(f"Detected columns: {cols}")
    # require age and sex
    if not cols["age"] or not cols["sex"]:
        raise RuntimeError("Could not find age or sex columns in the raw data. Please inspect the raw file.")

    # filter age groups
    df_filtered = filter_age_range(df, cols["age"], 18, 80)
    # keep only male/female rows (common labels)
    sex_vals = df_filtered[cols["sex"]].astype(str).str.lower()
    mask = sex_vals.str.contains("male") | sex_vals.str.contains("female") | sex_vals.str.contains("m") | sex_vals.str.contains("f")
    df_filtered = df_filtered.loc[mask].reset_index(drop=True)

    # if BMI present use it, else derive if height and weight present
    if cols["bmi"]:
        df_filtered["BMI"] = pd.to_numeric(df_filtered[cols["bmi"]], errors="coerce")
    elif cols["height"] and cols["weight"]:
        df_filtered = derive_bmi_from_height_weight(df_filtered, cols["height"], cols["weight"], newcol="BMI")
    else:
        print("No BMI or height+weight columns found; cleaned file will contain filtered aggregates only.")

    if "BMI" in df_filtered.columns:
        df_filtered = add_bmi_category(df_filtered, bmi_col="BMI")

    # Normalize columns: AgeGroup, Sex, BMI, BMI_category, plus any numeric fields
    out_cols = [cols["age"], cols["sex"]]
    if "BMI" in df_filtered.columns:
        out_cols.append("BMI")
        out_cols.append("BMI_category")
    # keep any height/weight columns too
    for k in ("height", "weight"):
        if cols[k]:
            out_cols.append(cols[k])

    out_cols = [c for c in out_cols if c in df_filtered.columns]
    df_out = df_filtered.loc[:, out_cols]
    df_out.columns = ["AgeGroup" if c == cols["age"] else ("Sex" if c == cols["sex"] else c) for c in df_out.columns]
    df_out.to_csv(dest, index=False)
    print(f"Saved cleaned CSV to {dest}")
    return dest


def main():
    raw_path = RAW_DIR / "HEA001_raw.csv"
    cleaned_path = CLEAN_DIR / "HEA001_cleaned.csv"
    try:
        download_url(DEFAULT_URL, raw_path)
    except Exception as e:
        print(f"Warning: download attempt failed: {e}")
        print("Please open the saved HTML in data/raw/ and update the script with the correct CSV URL if needed.")
        # continue if raw exists
        if not raw_path.exists():
            sys.exit(1)

    # attempt cleaning
    try:
        clean_file(raw_path, cleaned_path)
    except Exception as e:
        print(f"Cleaning failed: {e}")
        print("Inspect the raw file at", raw_path)
        sys.exit(1)


if __name__ == "__main__":
    main()
