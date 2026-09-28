#!/usr/bin/env python3
"""inspect_new_bench.py — peek at the three new public benchmark parquets."""
import pyarrow.parquet as pq
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "backend/data/public_bench/raw"

for fname in ["2wiki-validation.parquet", "musique-validation.parquet",
              "triviaqa-rc-wikipedia-validation.parquet"]:
    p = RAW / fname
    pf = pq.ParquetFile(p)
    print(f"\n===== {fname} =====")
    print("rows:", pf.metadata.num_rows, "| row_groups:", pf.metadata.num_row_groups)
    print("schema:", [f.name for f in pf.schema_arrow])
    t = pf.read_row_group(0)
    d = t.to_pylist()
    r = d[0]
    for k, v in r.items():
        s = str(v)[:180].replace("\n", " ")
        print(f"  {k!r}: {s}")
    # extra trivia-specific stats
    if "triviaqa" in fname:
        n_pages = [len(x.get("entity_pages", {}).get("title", [])) for x in d[:50]]
        sizes = [sum(len(str(t)) for t in x.get("entity_pages", {}).get("document_text", []))
                 for x in d[:50]]
        print(f"  [first 50 rows] entity_pages/question: min {min(n_pages)} max {max(n_pages)}")
        print(f"  [first 50 rows] total entity page chars: min {min(sizes)} max {max(sizes)} avg {sum(sizes)//len(sizes)}")
