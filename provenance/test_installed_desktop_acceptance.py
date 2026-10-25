"""Expose the installed evidence selection tests to existing CI discovery."""
import importlib.util
from pathlib import Path


def load_tests(loader, tests, pattern):
    path = Path(__file__).with_name('installed-desktop')/'test_export_acceptance.py'
    spec = importlib.util.spec_from_file_location('installed_acceptance_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
