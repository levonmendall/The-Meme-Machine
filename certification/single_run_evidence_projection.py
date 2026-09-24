"""Copy selected files from one completed, digest-pinned GitHub artifact.

This module only reads GitHub Actions evidence. It imports no market runtime,
accepts no configurable source or command, and performs no workflow dispatch.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile

REPO = "levonmendall/The-Meme-Machine"
RUN = 35962402406
ARTIFACT = 10795922766
SHA = "029e7a851f122825e19343a9e8a79652a86f6bb4"
DIGEST = "cd48383d331ded838128469f4a17138cc217fa7697b424e0e99b958b266400c2"
ROOT_FILES = {
    "assurance/market-assurance.json",
    "assurance/meteora-conformance.json",
    "assurance/pons-conformance.json",
    "assurance/pump-conformance.json",
    "assurance/ramses-conformance.json",
    "prospective-observation.json",
    "single-campaign-phase.json",
    "evidence-snapshot.json",
    "certification-hourly/result.json",
    "certification-hourly/manifest.json",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    base = "https://api.github.com/repos/" + REPO
    headers = {
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
    }

    def read_json(path):
        with urllib.request.urlopen(
            urllib.request.Request(base + path, headers=headers), timeout=60
        ) as response:
            return json.load(response)

    run = read_json(f"/actions/runs/{RUN}")
    if (run["status"] != "completed" or run["head_sha"] != SHA
            or run["run_attempt"] != 1):
        raise ValueError("source_run_not_terminal_exact_attempt")
    metadata = read_json(f"/actions/artifacts/{ARTIFACT}")
    archive_url = base + f"/actions/artifacts/{ARTIFACT}/zip"
    if (metadata["workflow_run"]["id"] != RUN
            or metadata["workflow_run"]["head_sha"] != SHA
            or metadata.get("digest") != "sha256:" + DIGEST
            or metadata.get("expired") is not False
            or metadata["archive_download_url"] != archive_url):
        raise ValueError("artifact_identity_mismatch")
    out = Path("single-run-evidence-projection")
    out.mkdir()
    receipt = {
        "source_run": RUN, "source_sha": SHA, "artifact_id": ARTIFACT,
        "source_sha256": DIGEST, "source_workflow_conclusion": run["conclusion"],
        "market_provider_requests": 0, "workflow_dispatches": 0,
        "copy_semantics": "selected original files, byte-for-byte",
        "files": [], "inventory": [],
    }
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        request = urllib.request.Request(archive_url, headers=headers)
        try:
            response = urllib.request.build_opener(NoRedirect()).open(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers["Location"]
            if not location.startswith("https://"):
                raise ValueError("non_https_artifact_redirect")
            # The GitHub token is deliberately absent from the signed-blob request.
            response = urllib.request.urlopen(location, timeout=120)
        with response, archive.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != DIGEST:
                raise ValueError("artifact_digest_mismatch")
        copied_bytes = 0
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("archive_path")
                receipt["inventory"].append({"path": member.filename, "bytes": member.file_size})
                native = member.filename.startswith("certification-native/hourly/")
                selected = (member.filename in ROOT_FILES or
                            (native and path.suffix in {".json", ".sqlite", ".jsonl", ".gz"}))
                if member.is_dir() or not selected or member.file_size > 32 * 1024 * 1024:
                    continue
                copied_bytes += member.file_size
                if copied_bytes > 128 * 1024 * 1024:
                    raise ValueError("projection_size_boundary")
                target = out / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                with target.open("rb") as source:
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                receipt["files"].append({"path": member.filename,
                                         "sha256": checksum, "bytes": member.file_size})
        if ROOT_FILES - {row["path"] for row in receipt["files"]}:
            raise ValueError("required_source_files_missing")
    (out / "projection-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"source_run": RUN, "source_sha256": DIGEST,
                      "copied_files": len(receipt["files"]),
                      "market_provider_requests": 0, "workflow_dispatches": 0}))


if __name__ == "__main__":
    main()
