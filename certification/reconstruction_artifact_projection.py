"""Project digest-pinned, completed evidence without any market access or mutation."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request
import zipfile

REPO = "levonmendall/The-Meme-Machine"
ARTIFACT = 10790448432
RUN = 35949285193
SHA = "1c6da29d08bfbe42e39ea1c8068933aae6b15cdb"
DIGEST = "698dcc65131bdc972f0be3176f8b29d276f8f054c77c86aa780a2bcd237dda6a"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    out = Path("reconstruction-projection")
    out.mkdir()
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
               "Accept": "application/vnd.github+json"}
    base = "https://api.github.com/repos/" + REPO
    with urllib.request.urlopen(urllib.request.Request(
            f"{base}/actions/artifacts/{ARTIFACT}", headers=headers), timeout=60) as response:
        metadata = json.load(response)
    if (metadata["workflow_run"]["id"] != RUN
            or metadata["workflow_run"]["head_sha"] != SHA
            or metadata.get("digest") != "sha256:" + DIGEST):
        raise ValueError("artifact_identity_mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        request = urllib.request.Request(metadata["archive_download_url"], headers=headers)
        try:
            response = urllib.request.build_opener(NoRedirect()).open(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            response = urllib.request.urlopen(error.headers["Location"], timeout=120)
        archive = scratch / "source.zip"
        with response, archive.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != DIGEST:
                raise ValueError("artifact_digest_mismatch")
        receipt = {"source_run": RUN, "source_sha": SHA, "artifact_id": ARTIFACT,
                   "source_sha256": DIGEST, "provider_requests": 0, "files": [],
                   "inventory": [], "sqlite_projections": {}}
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("archive_path")
                receipt["inventory"].append({"path": member.filename, "bytes": member.file_size})
                if member.is_dir():
                    continue
                # Native books, reports, traces, and RPC archives are copied exactly.
                # Large telemetry snapshots and the shared transaction cache stay in
                # the source artifact; only the requested stream/consumer tables are projected.
                shared = path.name == "shared-solana-evidence.sqlite"
                telemetry = path.name == "telemetry.sqlite"
                if shared or telemetry:
                    local = scratch / (str(len(receipt["inventory"])) + ".sqlite")
                    with zipped.open(member) as source, local.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    with sqlite3.connect(f"file:{local}?mode=ro&immutable=1", uri=True) as database:
                        database.row_factory = sqlite3.Row
                        schemas = [dict(r) for r in database.execute(
                            "select name,sql from sqlite_master where type='table'")]
                        receipt["sqlite_projections"][member.filename] = schemas
                        if shared:
                            wanted = {"stream_state", "stream_events", "evidence_consumers",
                                      "hydration_attempt_failures", "acquisition_phases", "pressure"}
                            for row in schemas:
                                table = row["name"]
                                if table not in wanted:
                                    continue
                                target = out / "shared-solana" / (table + ".jsonl.gz")
                                target.parent.mkdir(parents=True, exist_ok=True)
                                with gzip.open(target, "wt") as stream:
                                    for record in database.execute('select * from "' + table + '"'):
                                        stream.write(json.dumps(dict(record), sort_keys=True) + "\n")
                    local.unlink()
                    continue
                if member.file_size > 100 * 1024 * 1024:
                    continue
                target = out / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                with target.open("rb") as source:
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                receipt["files"].append({"path": member.filename, "sha256": checksum,
                                         "bytes": member.file_size})
        (out / "projection-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"run": RUN, "source_sha": SHA, "sha256": DIGEST,
                      "copied_files": len(receipt["files"]), "provider_requests": 0}))


if __name__ == "__main__":
    main()
