#!/usr/bin/env python3
"""
Prune old SHA tags from Vultr Container Registry (qlink01/kisna-backend).

Keeps: `latest` plus the N most recent 40-char git-SHA tags (ordered via
`git log` in this repo). Deletes older SHA tags by digest using Docker
Registry HTTP API v2 (proven against blr.vultrcr.com: DELETE returns 202).

Never deletes a digest still referenced by a kept tag (latest and the
newest SHA usually share a digest; deleting that digest would untag both).

Default is --dry-run. Pass --execute to actually DELETE.

Auth (same as docker login; no values printed):
  VULTR_REGISTRY_USERNAME + VULTR_REGISTRY_PASSWORD
  or Docker credential helper for blr.vultrcr.com

Usage:
  python scripts/prune_registry.py
  python scripts/prune_registry.py --keep 5 --dry-run
  python scripts/prune_registry.py --keep 5 --execute
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

HOST = "blr.vultrcr.com"
REPO = "qlink01/kisna-backend"
SHA_TAG_RE = re.compile(r"^[0-9a-f]{40}$")
ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
ROOT = Path(__file__).resolve().parents[1]


def registry_auth() -> tuple[str, str]:
    user = (os.environ.get("VULTR_REGISTRY_USERNAME") or "").strip()
    password = (os.environ.get("VULTR_REGISTRY_PASSWORD") or "").strip()
    if user and password:
        return user, password
    proc = subprocess.run(
        ["docker-credential-desktop", "get"],
        input=f"{HOST}\n",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "No registry credentials. Set VULTR_REGISTRY_USERNAME and "
            "VULTR_REGISTRY_PASSWORD, or docker login to blr.vultrcr.com."
        )
    data = json.loads(proc.stdout)
    return data["Username"], data["Secret"]


def session(auth: tuple[str, str]) -> requests.Session:
    sess = requests.Session()
    sess.auth = auth
    sess.headers["Accept"] = ACCEPT
    sess.timeout = 30
    return sess


def list_tags(sess: requests.Session) -> list[str]:
    url = f"https://{HOST}/v2/{REPO}/tags/list"
    response = sess.get(url, timeout=30)
    response.raise_for_status()
    return list(response.json().get("tags") or [])


def tag_digest(sess: requests.Session, tag: str) -> str:
    url = f"https://{HOST}/v2/{REPO}/manifests/{tag}"
    response = sess.get(url, timeout=30)
    response.raise_for_status()
    digest = (response.headers.get("Docker-Content-Digest") or "").strip()
    if not digest:
        raise SystemExit(f"No Docker-Content-Digest for tag {tag}")
    return digest


def git_sha_order() -> dict[str, int]:
    """Newer commits get a higher rank. Missing SHAs are omitted."""
    proc = subprocess.run(
        ["git", "log", "--format=%H", "prod"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "log", "--format=%H"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        return {}
    shas = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    # First line is newest.
    return {sha: len(shas) - i for i, sha in enumerate(shas)}


def delete_digest(sess: requests.Session, digest: str) -> tuple[int, str]:
    url = f"https://{HOST}/v2/{REPO}/manifests/{digest}"
    response = sess.delete(url, timeout=30)
    return response.status_code, response.text[:500]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prune old SHA tags from Vultr kisna-backend (default: dry-run)"
    )
    parser.add_argument("--keep", type=int, default=5, help="SHA tags to keep besides latest")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only (default)")
    parser.add_argument("--execute", action="store_true", help="Actually DELETE old SHA manifests")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.execute and args.dry_run:
        raise SystemExit("Use only one of --dry-run or --execute.")
    execute = bool(args.execute)

    auth = registry_auth()
    sess = session(auth)
    tags = list_tags(sess)
    sha_tags = [t for t in tags if SHA_TAG_RE.match(t)]
    other = [t for t in tags if t != "latest" and t not in sha_tags]
    ranks = git_sha_order()
    ranked = [t for t in sha_tags if t in ranks]
    unranked = [t for t in sha_tags if t not in ranks]
    ranked.sort(key=lambda t: ranks[t], reverse=True)
    keep_sha = ranked[: max(args.keep, 0)]
    delete_sha = ranked[max(args.keep, 0) :]
    keep_tags = {"latest", *keep_sha, *unranked, *other}

    print(
        json.dumps(
            {
                "registry": HOST,
                "repository": REPO,
                "mode": "execute" if execute else "dry-run",
                "all_tags": sorted(tags),
                "keep_latest": "latest" in tags,
                "keep_sha": keep_sha,
                "keep_unranked_sha": unranked,
                "keep_other": other,
                "delete_sha": delete_sha,
                "note": (
                    "DELETE is by digest. Digests still referenced by a kept "
                    "tag are skipped so latest is not untagged."
                ),
            },
            indent=2,
        )
    )

    if unranked and not ranks:
        print(
            "Cannot order SHA tags (git log failed). Refusing --execute.",
            file=sys.stderr,
        )
        if execute:
            raise SystemExit(1)

    if not execute:
        print("Dry-run only. Re-run with --execute to delete.", file=sys.stderr)
        return

    keep_digests = set()
    for tag in sorted(keep_tags):
        if tag not in tags:
            continue
        keep_digests.add(tag_digest(sess, tag))

    # Attempt every candidate even if some fail -- one bad digest (or a
    # credential that can list but not delete) must not stop the other 40+
    # from being cleaned up. Collect failures and report/exit at the end.
    failures: list[dict] = []
    for tag in delete_sha:
        digest = tag_digest(sess, tag)
        if digest in keep_digests:
            print(json.dumps({"skip": tag, "reason": "digest still referenced by a kept tag"}))
            continue
        status, body = delete_digest(sess, digest)
        print(json.dumps({"deleted_tag": tag, "digest": digest, "http": status}))
        if status not in {202, 200, 404}:
            failures.append({"tag": tag, "digest": digest, "http": status, "body": body})

    if failures:
        print(json.dumps({"failures": failures}, indent=2), file=sys.stderr)
        if all(f["http"] == 403 for f in failures):
            print(
                "\nEvery delete returned 403 Forbidden -- auth succeeded (list/read worked) "
                "but this credential isn't permitted to delete. Vultr Container Registry is "
                "Harbor-based: if VULTR_REGISTRY_USERNAME/PASSWORD is a robot account, its "
                "scope likely covers push/pull only. Fix in the Vultr console -- Container "
                "Registry -> Robot Accounts -- by granting delete permission on this project "
                "(or recreating the robot account with it included), or delete the old tags "
                "there directly under the repository's Tags tab as an immediate unblock.",
                file=sys.stderr,
            )
        raise SystemExit(
            f"{len(failures)}/{len(delete_sha)} deletes failed -- see failures above"
        )


if __name__ == "__main__":
    main()
