#!/usr/bin/env python3
"""Pack reference_scores/ into reference_scores_v1.0.zip for the GitHub release and record its
checksum in results/v1.0/reference_scores.sha256 (maintainers only)."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "reference_scores_v1.0.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
    for f in sorted((ROOT / "reference_scores").rglob("*.csv.gz")):
        info = zipfile.ZipInfo(str(f.relative_to(ROOT)), date_time=(2026, 10, 23, 0, 0, 0))
        z.writestr(info, f.read_bytes())
digest = hashlib.sha256(out.read_bytes()).hexdigest()
(ROOT / "results" / "v1.0" / "reference_scores.sha256").write_text(f"{digest}  {out.name}\n")
print(out, digest)
