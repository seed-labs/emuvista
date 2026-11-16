#!/usr/bin/env python3
"""Observe E15 agents using the shared E99 dashboard."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.E99_virtual_world_with_agents.monitor import main

if __name__ == '__main__':
    if not any(arg == '--output' or arg.startswith('--output=') for arg in sys.argv[1:]):
        sys.argv.extend(['--output', str(HERE / 'output')])
    main()
