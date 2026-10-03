#!/usr/bin/env python3
"""
Sync utility between standalone lineupnodes repo and bundled xnodify/lineupnodes.py.

Usage:
    python3 tools/sync_lineupnodes.py --check    # Check if files are identical (default)
    python3 tools/sync_lineupnodes.py --pull     # Copy from standalone repo to xnodify
    python3 tools/sync_lineupnodes.py --push     # Copy from xnodify to standalone repo
"""

import sys
import os
import shutil
import filecmp
from pathlib import Path


def main():
    repo_dir = Path(__file__).parent.parent.resolve()
    xnodify_file = repo_dir / "lineupnodes.py"
    standalone_file = repo_dir.parent / "lineupnodes" / "lineupnodes.py"

    if not standalone_file.exists():
        print(f"Standalone lineupnodes repo not found at: {standalone_file}")
        sys.exit(0)

    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if mode == "--check":
        if filecmp.cmp(xnodify_file, standalone_file, shallow=False):
            print("✓ lineupnodes.py is in sync across both repositories.")
            sys.exit(0)
        else:
            print("⚠️  WARNING: lineupnodes.py is OUT OF SYNC between xnodify and standalone repo!")
            print(f"  xnodify copy:    {xnodify_file}")
            print(f"  standalone copy: {standalone_file}")
            print("Run with --pull or --push to synchronize.")
            sys.exit(1)

    elif mode in ("--pull", "--from-standalone"):
        shutil.copy2(standalone_file, xnodify_file)
        print(f"✓ Synchronized: {standalone_file} -> {xnodify_file}")

    elif mode in ("--push", "--to-standalone"):
        shutil.copy2(xnodify_file, standalone_file)
        print(f"✓ Synchronized: {xnodify_file} -> {standalone_file}")

    else:
        print(f"Unknown option: {mode}")
        print("Usage: python3 tools/sync_lineupnodes.py [--check | --pull | --push]")
        sys.exit(1)


if __name__ == "__main__":
    main()
