Source: Census and Statistics Department (C&SD), Hong Kong — web table HEA001 (Health statistics).

Purpose: This folder will store raw and cleaned datasets used in the assignment.

Assumptions:
- We focus on adults aged 18-80 and sexes Male/Female.
- C&SD publishes aggregate tables on health metrics; HEA001 is an entry point for anthropometric statistics (height/weight/BMI).
- The downloader script attempts to fetch a CSV version of HEA001. If the portal returns HTML, the HTML is saved for manual inspection and the script will try to locate CSV links inside it.

Files produced by scripts:
- data/raw/HEA001_raw.csv (or HEA001_raw.html) — raw download
- data/cleaned/HEA001_cleaned.csv — filtered and normalized CSV with AgeGroup, Sex, BMI, BMI_category (when derivable)

Next steps:
- Run `python scripts\download_and_clean.py` to fetch and clean the data.
- If download fails, open the saved HTML and locate the direct CSV link, then re-run the script after updating DEFAULT_URL in `scripts/download_and_clean.py`.
