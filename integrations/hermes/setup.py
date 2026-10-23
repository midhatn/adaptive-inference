"""Reconstruct the fixed Hermes host-intent integration into a new directory."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'provenance'))
from reconstruct import reconstruct

if __name__ == '__main__':
    reconstruct(HERE, 'https://github.com/NousResearch/hermes-agent.git',
                '2587d8231fc7e0f3e846acafa46eb5b67cdc70c8')
