"""Expose the paused-expiry selector checks to existing provenance discovery."""
import importlib.util
from pathlib import Path


def load_tests(loader, tests, pattern):
    path = Path(__file__).with_name('paused-budget-expiry')/'acceptance/test_export.py'
    spec = importlib.util.spec_from_file_location('paused_expiry_acceptance_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
