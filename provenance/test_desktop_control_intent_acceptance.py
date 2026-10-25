"""Expose only the successor selector tests to existing provenance discovery."""
import importlib.util
from pathlib import Path


def load_tests(loader,tests,pattern):
    path=Path(__file__).with_name('desktop-control-intent')/'acceptance/test_export_acceptance.py'
    spec=importlib.util.spec_from_file_location('control_intent_acceptance_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
