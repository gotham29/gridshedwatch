#!/usr/bin/env python3
"""Download the reference per-signal scores (LSTM 5 seeds, Chronos, HTM 5 seeds; about 100 MB)
from the GitHub release into reference_scores/, check the checksum and unpack.

Usage: python scripts/fetch_reference.py [--url URL]
"""
import argparse
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/gotham29/gridshedwatch/releases/download/v1.0.0/reference_scores_v1.0.zip"
SHA_FILE = ROOT / "results" / "v1.0" / "reference_scores.sha256"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    a = ap.parse_args()
    print(f"downloading {a.url}")
    blob = urllib.request.urlopen(a.url, timeout=300).read()
    want = SHA_FILE.read_text().split()[0]
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise SystemExit(f"checksum mismatch: got {got}, expected {want}")
    zipfile.ZipFile(io.BytesIO(blob)).extractall(ROOT)
    print("unpacked into reference_scores/")


if __name__ == "__main__":
    main()
