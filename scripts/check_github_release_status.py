"""Read deployment/CI status using the existing Git credential helper, without logging tokens."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx


def main() -> int:
    revision = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], text=True
    ).strip()
    remote = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
    parsed = urlsplit(remote)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise RuntimeError("This verifier requires the configured HTTPS GitHub remote.")
    repository = parsed.path.strip("/").removesuffix(".git")
    helper = subprocess.run(
        ["git", "credential", "fill"],
        input=f"protocol=https\nhost=github.com\npath={repository}.git\n\n",
        env={**os.environ, "GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    credential = dict(line.split("=", 1) for line in helper.stdout.splitlines() if "=" in line)
    token = credential.get("password")
    if helper.returncode or not token:
        print(json.dumps({"state": "AUTH_UNAVAILABLE", "interactive_login_attempted": False}))
        return 1

    def safe_url(value: str | None) -> str | None:
        if not value:
            return value
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    result: dict[str, object] = {"revision": revision}
    with httpx.Client(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
        follow_redirects=False,
    ) as client:
        for endpoint in ("status", "check-runs"):
            response = client.get(
                f"https://api.github.com/repos/{repository}/commits/{revision}/{endpoint}"
            )
            if response.status_code != 200:
                result[endpoint] = {"http_status": response.status_code}
                continue
            payload = response.json()
            if endpoint == "status":
                result[endpoint] = {
                    "state": payload["state"],
                    "statuses": [
                        {
                            "context": row["context"],
                            "state": row["state"],
                            "updated_at": row["updated_at"],
                            "url": safe_url(row.get("target_url")),
                        }
                        for row in payload.get("statuses", [])
                    ],
                }
            else:
                result[endpoint] = [
                    {
                        "name": row["name"],
                        "status": row["status"],
                        "conclusion": row["conclusion"],
                        "url": safe_url(row.get("html_url")),
                    }
                    for row in payload.get("check_runs", [])
                ]
                failures = []
                for row in payload.get("check_runs", []):
                    if row.get("conclusion") != "failure":
                        continue
                    annotations = client.get(
                        f"https://api.github.com/repos/{repository}/check-runs/{row['id']}/annotations"
                    )
                    if annotations.status_code == 200:
                        failures.append(
                            {
                                "name": row["name"],
                                "annotations": [
                                    {
                                        "path": item.get("path"),
                                        "line": item.get("start_line"),
                                        "message": item.get("message", "")[:4000],
                                    }
                                    for item in annotations.json()
                                ],
                            }
                        )
                    if "--logs" in sys.argv:
                        job_id = urlsplit(row.get("html_url", "")).path.rsplit("/", 1)[-1]
                        if job_id.isdecimal():
                            job = client.get(
                                f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}"
                            )
                            if job.status_code == 200:
                                failures.append(
                                    {
                                        "name": row["name"],
                                        "failed_steps": [
                                            item.get("name")
                                            for item in job.json().get("steps", [])
                                            if item.get("conclusion") == "failure"
                                        ],
                                    }
                                )
                            logs = client.get(
                                f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}/logs"
                            )
                            if logs.status_code == 302:
                                # Follow signed artifacts without forwarding GitHub credentials.
                                location = logs.headers["location"]
                                if urlsplit(location).scheme != "https":
                                    raise RuntimeError("GitHub log artifact must use HTTPS.")
                                logs = httpx.get(location, timeout=30)
                            if logs.status_code == 200:
                                failures.append(
                                    {"name": row["name"], "log_tail": logs.text[-12000:]}
                                )
                result["failures"] = failures
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
