"""Ad-hoc LanceDB inspector — dumps schema, counts, and sample rows.

Usage:
    python scripts/inspect_db.py                 # overview + 5 sample rows
    python scripts/inspect_db.py --app NAME      # filter by app
    python scripts/inspect_db.py --path SUBSTR   # filter by path substring
    python scripts/inspect_db.py --limit 20      # more rows
    python scripts/inspect_db.py --distinct path # unique values of a column
"""
from __future__ import annotations

import argparse
import json
import time

from wrag import store as st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=None, help="filter app_name")
    ap.add_argument("--path", default=None, help="substring match on path")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--distinct", default=None, help="show distinct values of a column")
    args = ap.parse_args()

    db = st.connect()
    print(f"DB path : {st.VECTORS_DIR}")
    print(f"Tables  : {db.table_names()}")

    if st.TABLE_NAME not in db.table_names():
        print("No `chunks` table yet — run `wrag index` first.")
        return

    tbl = db.open_table(st.TABLE_NAME)
    print(f"Rows    : {tbl.count_rows()}")
    print(f"Schema  :\n{tbl.schema}\n")

    rows = tbl.to_arrow().to_pydict()
    n = len(rows["id"])

    if args.distinct:
        col = args.distinct
        if col not in rows:
            print(f"Column '{col}' not in schema.")
            return
        uniq = sorted({rows[col][i] for i in range(n)})
        print(f"Distinct {col} ({len(uniq)}):")
        for v in uniq:
            print(f"  {v}")
        return

    # Filter + display
    shown = 0
    for i in range(n):
        if args.app and rows["app_name"][i] != args.app:
            continue
        if args.path and args.path not in rows["path"][i]:
            continue
        record = {
            "id": rows["id"][i],
            "app_name": rows["app_name"][i],
            "source_type": rows["source_type"][i],
            "path": rows["path"][i],
            "language": rows["language"][i],
            "symbol_type": rows["symbol_type"][i],
            "symbol_name": rows["symbol_name"][i],
            "lines": f"{rows['start_line'][i]}-{rows['end_line'][i]}",
            "indexed_at": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(rows["indexed_at"][i])
            ),
            "vector_dim": len(rows["vector"][i]),
            "text_preview": rows["text"][i][:120].replace("\n", " ⏎ "),
        }
        print(json.dumps(record, indent=2))
        shown += 1
        if shown >= args.limit:
            break

    if shown == 0:
        print("No matching rows.")


if __name__ == "__main__":
    main()
