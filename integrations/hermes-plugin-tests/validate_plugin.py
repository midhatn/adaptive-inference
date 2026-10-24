import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--plugin', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
from hermes_cli.plugin_validate import validate_plugin_dir
report = validate_plugin_dir(args.plugin.resolve())
args.out.write_text(json.dumps(report.to_dict(), indent=2), encoding='utf-8')
print(json.dumps(report.to_dict(), indent=2))
raise SystemExit(report.exit_code)
