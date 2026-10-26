"""Fetch the Ethereum block builder data for the Builder Market room.

Source: BigQuery public data set `bigquery-public-data.crypto_ethereum.blocks`.
The script uses the `bq` command line tool. The tool must be installed and
authenticated. Each query first runs as a dry run. The script prints the bytes
that the query scans and stops if the scan is above the cap.

Outputs (all in data/raw/builder-market/):
  daily_builders.csv   one row per day and builder label with the block count
  daily_stats.csv      one row per day with block count and median base fee
  weekly_stats.csv     one row per week with block count and median base fee
  ticker.csv           one row per block for the latest 7 days
  tags.csv             the 300 most common raw extra_data tags with the label

Run from the repository root:
  .venv/bin/python3 -I pipelines/builder-market/fetch.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "builder-market"
RAW.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 100_000_000_000  # 100 GB cap for each query
MERGE_TS = "2022-09-15 06:42:42"  # the Merge, UTC

# The builder label rule. The text is the decoded extra_data field in lower
# case. The first matching line wins. Tags that look like a client default
# (geth, Nethermind, besu, erigon, reth, or an empty tag) become "vanilla".
# All other tags keep a sanitized copy of the raw text, so that the HHI can
# count them as separate entities.
LABEL_SQL = """
CASE
  WHEN REGEXP_CONTAINS(lt, r'titan') THEN 'Titan'
  WHEN REGEXP_CONTAINS(lt, r'beaverbuild') THEN 'beaverbuild'
  WHEN REGEXP_CONTAINS(lt, r'rsync') THEN 'rsync'
  WHEN REGEXP_CONTAINS(lt, r'illuminate dmocr') THEN 'Flashbots'
  WHEN REGEXP_CONTAINS(lt, r'buildernet') THEN 'BuilderNet'
  WHEN REGEXP_CONTAINS(lt, r'quasar') THEN 'Quasar'
  WHEN REGEXP_CONTAINS(lt, r'bloxroute') THEN 'bloXroute'
  WHEN REGEXP_CONTAINS(lt, r'builder0x69') THEN 'builder0x69'
  WHEN REGEXP_CONTAINS(lt, r'eureka') THEN 'Eureka'
  WHEN REGEXP_CONTAINS(lt, r'blocknative') THEN 'Blocknative'
  WHEN REGEXP_CONTAINS(lt, r'btcs') THEN 'Builder+ (BTCS)'
  WHEN REGEXP_CONTAINS(lt, r'eth-builder') THEN 'eth-builder'
  WHEN REGEXP_CONTAINS(lt, r'f1b') THEN 'f1b.io'
  WHEN REGEXP_CONTAINS(lt, r'jetbldr') THEN 'jetbldr'
  WHEN REGEXP_CONTAINS(lt, r'bobthebuilder') THEN 'bobTheBuilder'
  WHEN REGEXP_CONTAINS(lt, r'buildai') THEN 'BuildAI'
  WHEN REGEXP_CONTAINS(lt, r'bombora') THEN 'bombora'
  WHEN REGEXP_CONTAINS(lt, r'gmbit|gambit') THEN 'Gambit'
  WHEN REGEXP_CONTAINS(lt, r'manta-builder') THEN 'manta'
  WHEN REGEXP_CONTAINS(lt, r'penguinbuild') THEN 'penguinbuild'
  WHEN REGEXP_CONTAINS(lt, r'tbuilder') THEN 'tbuilder'
  WHEN REGEXP_CONTAINS(lt, r'payload\\.de') THEN 'payload.de'
  WHEN REGEXP_CONTAINS(lt, r'lokibuilder') THEN 'lokibuilder'
  WHEN REGEXP_CONTAINS(lt, r'lightspeed') THEN 'lightspeed'
  WHEN REGEXP_CONTAINS(lt, r'ultrasound') THEN 'ultrasound'
  WHEN REGEXP_CONTAINS(lt, r'edennetwork') THEN 'Eden'
  WHEN REGEXP_CONTAINS(lt, r'boba-builder') THEN 'boba'
  WHEN REGEXP_CONTAINS(lt, r'shimmerblocks') THEN 'shimmer'
  WHEN REGEXP_CONTAINS(lt, r'blockbeelder') THEN 'blockbeelder'
  WHEN REGEXP_CONTAINS(lt, r'bitget') THEN 'Bitget'
  WHEN lt = '' OR REGEXP_CONTAINS(lt, r'geth|nethermind|besu|erigon|reth') THEN 'vanilla'
  ELSE REGEXP_REPLACE(tag, r'[^\\x20-\\x7e]', '?')
END
"""

BASE = f"""
WITH b AS (
  SELECT number, timestamp, miner, base_fee_per_gas, gas_used, transaction_count,
    COALESCE(SAFE_CONVERT_BYTES_TO_STRING(FROM_HEX(SUBSTR(extra_data, 3))), '') AS tag
  FROM `bigquery-public-data.crypto_ethereum.blocks`
  WHERE timestamp >= TIMESTAMP('{MERGE_TS}')
), l AS (
  SELECT *, LOWER(tag) AS lt FROM b
), lab AS (
  SELECT number, timestamp, miner, base_fee_per_gas, gas_used, transaction_count, tag,
    {LABEL_SQL} AS label
  FROM l
)
"""

QUERIES = {
    "daily_builders.csv": BASE + """
SELECT DATE(timestamp) AS day, label, COUNT(*) AS n
FROM lab GROUP BY day, label ORDER BY day, n DESC
""",
    "daily_stats.csv": BASE + """
SELECT DATE(timestamp) AS day, COUNT(*) AS blocks,
  APPROX_QUANTILES(base_fee_per_gas, 100)[OFFSET(50)] / 1e9 AS median_base_fee_gwei,
  AVG(gas_used) AS avg_gas_used, SUM(transaction_count) AS tx
FROM lab GROUP BY day ORDER BY day
""",
    "weekly_stats.csv": BASE + """
SELECT DATE_TRUNC(DATE(timestamp), WEEK(THURSDAY)) AS week, COUNT(*) AS blocks,
  APPROX_QUANTILES(base_fee_per_gas, 100)[OFFSET(50)] / 1e9 AS median_base_fee_gwei,
  AVG(gas_used) AS avg_gas_used, SUM(transaction_count) AS tx
FROM lab GROUP BY week ORDER BY week
""",
    "ticker.csv": BASE + """
SELECT number, UNIX_SECONDS(timestamp) AS ts, label,
  ROUND(base_fee_per_gas / 1e9, 2) AS base_fee_gwei, transaction_count AS tx
FROM lab
WHERE timestamp >= (SELECT TIMESTAMP_SUB(MAX(timestamp), INTERVAL 7 DAY) FROM lab)
ORDER BY number
""",
    "tags.csv": BASE + """
SELECT REGEXP_REPLACE(tag, r'[^\\x20-\\x7e]', '?') AS tag, label, COUNT(*) AS n,
  COUNT(DISTINCT miner) AS fee_recipients,
  APPROX_TOP_COUNT(miner, 1)[OFFSET(0)].value AS top_fee_recipient,
  MIN(DATE(timestamp)) AS first_day, MAX(DATE(timestamp)) AS last_day
FROM lab GROUP BY tag, label ORDER BY n DESC LIMIT 300
""",
}


def bq(args, sql):
    cmd = ["nice", "-n", "10", "bq", "query", "--use_legacy_sql=false",
           f"--maximum_bytes_billed={MAX_BYTES}", "--quiet"] + args + [sql]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    for name, sql in QUERIES.items():
        out = RAW / name
        dry = bq(["--dry_run", "--format=prettyjson"], sql)
        if dry.returncode != 0:
            print("dry run failed for", name, dry.stderr, dry.stdout)
            sys.exit(1)
        info = json.loads(dry.stdout)
        scanned = int(info["statistics"]["totalBytesProcessed"])
        print(f"{name}: dry run scans {scanned/1e9:.2f} GB")
        if scanned > MAX_BYTES:
            print("scan above the cap, stop")
            sys.exit(1)
        res = bq(["--format=csv", "--max_rows=2000000"], sql)
        if res.returncode != 0:
            print("query failed for", name, res.stderr, res.stdout)
            sys.exit(1)
        out.write_text(res.stdout)
        rows = res.stdout.count("\n") - 1
        print(f"  wrote {out} ({rows} rows, {out.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
