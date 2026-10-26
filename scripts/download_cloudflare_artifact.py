"""Download a successful main CI bundle without building on the owner's laptop."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx


def download(revision: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=root, text=True
    ).strip()
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=root, text=True
    ).strip()
    parsed = urlsplit(remote)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("Expected the configured HTTPS GitHub origin.")
    repository = parsed.path.strip("/").removesuffix(".git")
    helper = subprocess.run(
        ["git", "credential", "fill"],
        cwd=root,
        input=f"protocol=https\nhost=github.com\npath={repository}.git\n\n",
        env={**os.environ, "GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    values = dict(line.split("=", 1) for line in helper.stdout.splitlines() if "=" in line)
    token = values.get("password")
    if helper.returncode or not token:
        raise RuntimeError("Existing GitHub credentials unavailable; no login was attempted.")
    output = root / ".open-next" / f"ci-{revision[:12]}"
    if output.exists():
        raise RuntimeError("This revision already has a downloaded artifact; refusing overwrite.")
    api = f"https://api.github.com/repos/{repository}"
    with httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
        follow_redirects=False,
    ) as client:
        response = client.get(
            f"{api}/actions/workflows/ci.yml/runs",
            params={"head_sha": revision, "branch": "main", "event": "push", "per_page": 20},
        )
        response.raise_for_status()
        runs = [
            run
            for run in response.json()["workflow_runs"]
            if run["head_sha"] == revision
            and run["head_branch"] == "main"
            and run["status"] == "completed"
            and run["conclusion"] == "success"
        ]
        if not runs:
            raise RuntimeError("The complete main CI workflow has not passed for this commit.")
        run = max(runs, key=lambda item: item["id"])
        response = client.get(f"{api}/actions/runs/{run['id']}/artifacts")
        response.raise_for_status()
        artifacts = [
            item
            for item in response.json()["artifacts"]
            if item["name"] == f"cloudflare-{revision}" and not item["expired"]
        ]
        if len(artifacts) != 1:
            raise RuntimeError("Expected exactly one unexpired Cloudflare artifact for the run.")
        artifact = artifacts[0]
        expected_digest = str(artifact.get("digest", ""))
        if not expected_digest.startswith("sha256:"):
            raise RuntimeError("GitHub did not provide an artifact SHA-256 digest.")
        response = client.get(f"{api}/actions/artifacts/{artifact['id']}/zip")
        if response.status_code != 302:
            raise RuntimeError("Artifact download did not return the expected redirect.")
        location = response.headers["location"]
        if urlsplit(location).scheme != "https":
            raise RuntimeError("Artifact download must use HTTPS.")
        # Signed storage URL gets a fresh client, without any GitHub authorization header.
        with tempfile.TemporaryDirectory(prefix="nutrilens-cloudflare-") as scratch:
            archive = Path(scratch) / "artifact.zip"
            digest = hashlib.sha256()
            size = 0
            with httpx.stream("GET", location, timeout=120, follow_redirects=False) as stream:
                stream.raise_for_status()
                with archive.open("wb") as handle:
                    for chunk in stream.iter_bytes():
                        size += len(chunk)
                        if size > 512 * 1024 * 1024:
                            raise RuntimeError("Artifact exceeds the 512-MiB download bound.")
                        digest.update(chunk)
                        handle.write(chunk)
            if f"sha256:{digest.hexdigest()}" != expected_digest:
                raise RuntimeError("Artifact digest does not match GitHub metadata.")
            tar_name = f"cloudflare-{revision}.tar.gz"
            with zipfile.ZipFile(archive) as zipped:
                if zipped.namelist() != [tar_name]:
                    raise RuntimeError("Artifact contains unexpected files.")
                if zipped.getinfo(tar_name).file_size > 512 * 1024 * 1024:
                    raise RuntimeError("Artifact archive exceeds its extraction bound.")
                zipped.extract(tar_name, scratch)
            with tarfile.open(Path(scratch) / tar_name, "r:gz") as bundle:
                members = bundle.getmembers()
                if sum(item.size for item in members) > 2 * 1024 * 1024 * 1024:
                    raise RuntimeError("Uncompressed bundle exceeds its 2-GiB bound.")
                for member in members:
                    name = PurePosixPath(member.name)
                    if (
                        name.is_absolute()
                        or ".." in name.parts
                        or not name.parts
                        or name.parts[0] != ".open-next"
                        or "\\" in member.name
                    ):
                        raise RuntimeError("Bundle contains an unexpected extraction path.")
                output.mkdir(parents=True)
                bundle.extractall(output, members=members, filter="data")
    if not (output / ".open-next" / "worker.js").is_file():
        raise RuntimeError("Downloaded bundle has no Cloudflare worker entrypoint.")
    return {
        "status": "VERIFIED_DOWNLOAD",
        "revision": revision,
        "run_id": run["id"],
        "artifact_id": artifact["id"],
        "sha256": digest.hexdigest(),
        "bundle": str(output / ".open-next"),
        "deployed": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(download(sys.argv[1] if len(sys.argv) > 1 else "HEAD"), indent=2))
    except Exception as error:
        # HTTP errors can include signed download URLs; never put those in task output.
        print(json.dumps({"status": "DOWNLOAD_FAILED", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
