# SPDX-License-Identifier: Apache-2.0
"""Run the unchanged PR20 checks/exporter against its exact historical source."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ACCEPTANCE = HERE.parent / 'acceptance'
TEST_SHA256 = '16fa74d6c28b28f5ba47de36888f427ad2d1615fc5ecdcc9d68e791dd697fcf9'


def builder():
    spec = importlib.util.spec_from_file_location('paused_expiry_historical_view', HERE / 'historical_view.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repository, *, temp_parent=None, selection=None, output=None):
    """Keep the verified view alive through the child exit and result readback."""
    if (selection is None) != (output is None):
        raise ValueError('Selection and fresh output are required together')
    repository = Path(repository).resolve(strict=True)
    temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True) if temp_parent is None else Path(temp_parent)
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    with builder().historical_view(repository, temporary_parent) as view:
        if selection is None:
            test = ACCEPTANCE / 'test_export.py'
            if hashlib.sha256(test.read_bytes()).hexdigest() != TEST_SHA256:
                raise ValueError('Historical exporter tests changed')
            environment['ADAPTIVE_EVIDENCE_REPOSITORY'] = str(view)
            command = [sys.executable, '-B', str(test), '-v']
        else:
            command = [sys.executable, '-B', str(ACCEPTANCE / 'export.py'),
                       '--repository', str(view), '--selection', str(Path(selection).resolve(strict=True)),
                       '--output', str(Path(output).absolute())]
        result = subprocess.run(command, env=environment, cwd=repository,
                                capture_output=True, text=True, timeout=300)
        if selection is not None and result.returncode == 0:
            for name in ('result.json', 'manifest.json'):
                if (Path(output) / name).read_bytes() != (ACCEPTANCE / name).read_bytes():
                    raise ValueError('Reproduced historical evidence differs')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--temporary-parent', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if (args.selection is None) != (args.output is None):
        parser.error('--selection and --output must be provided together')
    result = run(args.repository, temp_parent=args.temporary_parent,
                 selection=args.selection, output=args.output)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
