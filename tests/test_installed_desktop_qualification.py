"""Discover the preserved installed-desktop qualification fixtures; no launch."""
import importlib.util
from pathlib import Path
import sys

_ROOT=Path(__file__).resolve().parents[1]/'examples/validation/installed_desktop'
def _load(name,filename):
    spec=importlib.util.spec_from_file_location(name,_ROOT/filename)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

_qualification=_load('installed_desktop_qualification','qualify.py')
_cold=_load('installed_desktop_cold_tests','test_cold.py')
_full=_load('installed_desktop_full_tests','test_full.py')
ColdHarnessTests=_cold.HarnessTests
QualificationSourceTests=_cold.SourceTests
FullUIBoundaries=_full.FullUIBoundaries
