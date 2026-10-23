"""Reconstruct the fixed Strata integration into a new directory."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'provenance'))
from reconstruct import reconstruct

if __name__ == '__main__':
    reconstruct(HERE, 'https://github.com/Niko1221/Strata.git',
                '7ddc17a38fe7f31637e895ecfba58c2cd43d65ec')
