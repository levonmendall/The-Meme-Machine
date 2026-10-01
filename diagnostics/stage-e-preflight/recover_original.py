"""Recover the exact preserved preflight bytes; never execute the full suite."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ARTIFACT = 11116354967
ZIP_SHA256 = "f64223a28818a0c0ee69e1451df623b8550bb1afd28c6c94b368802d090ae457"
LOG_SHA256 = "afd19c3842af1c00ff5e35f35917d6511e1ceeb67257235469d88e324a4181a0"


def main():
    raw = subprocess.check_output(["gh", "api", f"repos/levonmendall/The-Meme-Machine/actions/artifacts/{ARTIFACT}/zip"])
    assert hashlib.sha256(raw).hexdigest() == ZIP_SHA256, "original_artifact_digest_mismatch"
    out = Path(os.environ["LANE_C_EVIDENCE"])
    (out / "original-preflight.zip").write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        name, = [n for n in names if n.endswith("unittest.log")]
        log = archive.read(name)
    assert hashlib.sha256(log).hexdigest() == LOG_SHA256, "original_log_digest_mismatch"
    (out / "original-unittest.log").write_bytes(log)
    lines = log.decode().splitlines()
    skips = [l for l in lines if re.search(r"\.\.\. skipped ", l)]
    assert len(skips) == 46, ("original_skip_count", len(skips))
    (out / "original-skips.json").write_text(json.dumps(skips, indent=2) + "\n")
    print("LANE_C_ORIGINAL_BINDING " + json.dumps({
        "artifact_id": ARTIFACT,
        "zip_sha256": ZIP_SHA256,
        "unittest_sha256": LOG_SHA256,
        "tests": 1062, "passes": 1013, "failures": 1, "errors": 2, "skips": 46,
    }, sort_keys=True), flush=True)
    for line in skips:
        print("LANE_C_ORIGINAL_SKIP " + line, flush=True)
    error_start = next(i for i, line in enumerate(lines) if line.startswith("ERROR: "))
    print("LANE_C_ORIGINAL_TRACEBACKS\n" + "\n".join(lines[error_start:]), flush=True)


if __name__ == "__main__":
    main()
