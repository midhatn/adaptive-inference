"""Exact predecessor inputs for the older arithmetic/shutdown source checks.

Reuse this repository's explicit historical-source projection convention. Every
unmapped helper still reads the current file; two changed helpers require both
the declared current identity and the preserved historical identity. Assertions
in the historical consumers keep their original expected hashes and bytes.
"""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE.parents[2] / 'provenance/windows-handoff/termination-race-predecessor'
PINS = {
    'native/owner_source/ownership.py': (
        '9c5d702048c9dede30fb1c8124ecd7be1dfc0b161c3872f488035f487a44063d',
        'f419391c84d5d123328b8c3b454253f060e4d5d59db89fedd43fbd2313960b14'),
    'native/owner_source/source-pins.json': (
        '4dcb622f9d2c7fa0d01ee051ba404c40e195ea13d0d93d39a3ad02a61c5aa3c8',
        '19f871c8b6ca05becec6f9a76758eac94d9aa38f29951af1e20753bdd7ee7aca'),
}


def historical_native_source(relative):
    current = HERE / relative
    if relative not in PINS:
        return current
    current_pin, previous_pin = PINS[relative]
    previous = ARCHIVE / Path(relative).name
    for path, expected in ((current, current_pin), (previous, previous_pin)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Native historical projection identity changed: ' + relative)
    return previous
