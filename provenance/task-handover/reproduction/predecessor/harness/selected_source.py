# SPDX-License-Identifier: Apache-2.0
"""Check the recorded picker source without rewriting its signed/raw payload."""
from pathlib import Path


def selected_source_matches(source,expected):
    keys={'task_spec_path','task_spec_sha256','task_inputs'}
    if (type(source) is not dict or type(expected) is not dict
            or set(source)!=keys or set(expected)!=keys
            or any(type(row[key]) is not str for row in (source,expected) for key in keys)
            or source['task_spec_path']!=expected['task_spec_path']
            or source['task_spec_sha256']!=expected['task_spec_sha256']):
        return False
    actual,wanted=Path(source['task_inputs']),Path(expected['task_inputs'])
    try:
        return (actual.is_absolute() and wanted.is_absolute()
            and '..' not in actual.parts and '..' not in wanted.parts
            and actual==wanted and actual.is_dir() and wanted.is_dir()
            and actual.resolve(strict=True)==wanted.resolve(strict=True)
            and actual.samefile(wanted))
    except (OSError,ValueError):
        return False
