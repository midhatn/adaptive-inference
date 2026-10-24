"""Run explicit real-SDK plugin tests without installing or contacting a model."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing Hermes source checkout")
    parser.add_argument("--plugin", type=Path, required=True, help="Installable plugin directory")
    parser.add_argument("--output", type=Path, required=True, help="New private result directory")
    args = parser.parse_args()
    source, plugin, output = (x.resolve() for x in (args.source, args.plugin, args.output))
    if not (source / "hermes_cli" / "plugins.py").is_file() or not (plugin / "plugin.yaml").is_file():
        parser.error("Source or plugin directory is incomplete")
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(HERMES_TEST_SOURCE=str(source), HERMES_PLUGIN_SOURCE=str(plugin),
               HERMES_HOME=str(output / "home"), PYTHONNOUSERSITE="1")
    with (output / "pytest.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, "-I", "-B", "-m", "pytest",
            str(Path(__file__).resolve().parent / "tests"), "-q", "--disable-warnings",
            "-p", "no:cacheprovider"], env=env, stdout=log, stderr=subprocess.STDOUT,
            timeout=120, check=False)
    print((output / "pytest.log").read_text(encoding="utf-8"))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
