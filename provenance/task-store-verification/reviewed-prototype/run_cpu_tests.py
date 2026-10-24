"""CPU-only private successor fixtures; explicit source path, no installed override."""
from pathlib import Path
import json
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
started = time.perf_counter()
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
receipt = {"tests": result.testsRun, "passed": result.wasSuccessful(),
           "failures": len(result.failures), "errors": len(result.errors),
           "seconds": time.perf_counter() - started,
           "scope": "CPU SQLite/OS-lock fixtures only; no original failure-cause or live qualification claim"}
if len(sys.argv) == 2:
    destination = Path(sys.argv[1])
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
print(json.dumps(receipt))
raise SystemExit(0 if result.wasSuccessful() else 1)
