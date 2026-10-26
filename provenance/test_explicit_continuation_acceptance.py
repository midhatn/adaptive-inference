# SPDX-License-Identifier: Apache-2.0
"""Discover the single portable continuation-export suite."""
import importlib.util
from pathlib import Path


def load_tests(loader, tests, pattern):
    path = Path(__file__).resolve().parent/'explicit-continuation/acceptance/test_export.py'
    spec = importlib.util.spec_from_file_location('continuation_acceptance_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
