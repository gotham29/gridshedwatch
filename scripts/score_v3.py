#!/usr/bin/env python3
"""Score the reference methods under docs/protocol_v3.md (see gridshedwatch/protocol.py for the options)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gridshedwatch.protocol import main  # noqa: E402

if __name__ == "__main__":
    main()
