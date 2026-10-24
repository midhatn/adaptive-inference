"""Owned temporary SQLite files only; no source mutation or retained database."""
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile

rows = []
with tempfile.TemporaryDirectory(prefix="wal-readonly-probe-", dir=Path(__file__).parent) as directory:
    root = Path(directory)
    for name, statements in (
        ("normal", ["BEGIN", "PRAGMA application_id"]),
        ("journal-query-first", ["PRAGMA journal_mode"]),
        ("exclusive-first", ["PRAGMA locking_mode=EXCLUSIVE", "BEGIN", "PRAGMA application_id"]),
        ("exclusive-journal", ["PRAGMA locking_mode=EXCLUSIVE", "PRAGMA journal_mode"]),
    ):
        path = root / (name + ".sqlite")
        db = sqlite3.connect(path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.commit()
        db.close()
        initial = sorted(item.name for item in root.glob(name + ".sqlite*"))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        trace = []
        try:
            for sql in statements:
                try:
                    result = db.execute(sql).fetchall()
                    trace.append({"sql": sql, "result": result,
                                  "files": sorted(item.name for item in root.glob(name + ".sqlite*"))})
                except sqlite3.Error as exc:
                    trace.append({"sql": sql, "error": str(exc),
                                  "code": getattr(exc, "sqlite_errorcode", None),
                                  "name": getattr(exc, "sqlite_errorname", None),
                                  "files": sorted(item.name for item in root.glob(name + ".sqlite*"))})
                    break
        finally:
            db.close()
        rows.append({"case": name, "initial": initial, "trace": trace,
                     "final": sorted(item.name for item in root.glob(name + ".sqlite*")),
                     "main_bytes_unchanged": hashlib.sha256(path.read_bytes()).hexdigest() == before})
result = {"sqlite": sqlite3.sqlite_version, "rows": rows}
destination = Path(__file__).with_suffix(".json")
with destination.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
