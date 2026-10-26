"""Fetch patent citation flows between CPC fields from BigQuery public data.

Run from the repository root:
    .venv/bin/python3 -I pipelines/patent-drift/fetch.py

The script uses the `bq` command line tool. It runs a dry run first and reads
the byte estimate. It stops when the estimate is above the hard cap. The real
query runs with a maximum_bytes_billed guard. The outputs go to data/raw/patent-drift/:
    citations.csv   level, yr, src, dst, n   (see query.sql for the two levels)
    cpc_titles.csv  symbol, titleFull        (CPC sections and 4-character classes)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "patent-drift"
SQL = Path(__file__).resolve().parent / "query.sql"
HARD_CAP = 250_000_000_000  # bytes, 250 GB
TITLES_SQL = (
    "SELECT symbol, titleFull FROM `patents-public-data.cpc.definition` "
    "WHERE LENGTH(symbol) <= 4 ORDER BY symbol"
)


def read_sql(path):
    """Read the SQL file and remove the comment lines. The bq tool reads a leading '--' as a flag."""
    lines = [l for l in path.read_text().splitlines() if not l.lstrip().startswith("--")]
    return "\n".join(lines)


def dry_run(sql):
    """Return the byte estimate for the query."""
    out = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--dry_run", sql],
        capture_output=True, text=True,
    )
    m = re.search(r"process (\d+) bytes", out.stdout + out.stderr)
    if not m:
        print(out.stdout, out.stderr)
        raise SystemExit("dry run failed")
    return int(m.group(1))


def run(sql, dest, max_rows):
    """Run the query and write the CSV result to dest."""
    cmd = [
        "bq", "query", "--use_legacy_sql=false", "--format=csv", "--quiet",
        f"--max_rows={max_rows}", f"--maximum_bytes_billed={HARD_CAP}", sql,
    ]
    with open(dest, "w") as fh:
        res = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(res.stderr)
        raise SystemExit("query failed")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    sql = read_sql(SQL)
    est = dry_run(sql)
    print(f"dry run estimate: {est / 1e9:.1f} GB")
    if est > HARD_CAP:
        raise SystemExit("estimate is above the hard cap, the query did not run")
    est2 = dry_run(TITLES_SQL)
    print(f"titles dry run estimate: {est2 / 1e6:.1f} MB")
    run(TITLES_SQL, RAW / "cpc_titles.csv", 10000)
    print("wrote", RAW / "cpc_titles.csv")
    run(sql, RAW / "citations.csv", 5_000_000)
    n = sum(1 for _ in open(RAW / "citations.csv")) - 1
    print("wrote", RAW / "citations.csv", "rows:", n)


if __name__ == "__main__":
    sys.exit(main())
