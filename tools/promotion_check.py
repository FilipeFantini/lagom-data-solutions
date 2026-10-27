"""Promotion check: prod pins only image digests that staging pinned first.

ADR-0015 promotes by digest: a new image reaches staging in one pull request
and prod in a later one, by copying the digest staging ran. This check turns
that order from a convention into a CI gate (roadmap Track G).

For every image the prod manifests reference (a container's `image`, a
CloudNativePG Cluster's `imageName`):

1. It is pinned by digest (`name[:tag]@sha256:<64 hex>`). A tag can be moved
   to other bytes after staging ran it, so a tag alone proves nothing.
2. The same digest appears in staging's manifests in some commit reachable
   from --base, the commit the change is compared against: the pull
   request's base, or the previous tip of main on a push. A digest that one
   change pins in staging and prod together therefore fails: staging never
   had it on main before prod did.

Each environment's directories are the Git paths of the Argo CD Applications
in platform/infra/apps/ whose destination is that environment's namespace.

What it does not check:
- That staging's run of the image succeeded. CI never reaches the cluster
  (ADR-0015 decision 4), so "pinned on main" stands in for "ran"; the
  operator still confirms the staging run before the prod pull request.
- Images that come from a Helm chart rather than a manifest in the
  environment's own directory, or from a manifest in a subdirectory of it
  (Argo CD, like this check, reads only the top level of a directory).
- How long the digest ran in staging, or whether staging still pins it.
- Where in a staging file the digest appeared: the search is textual, so a
  digest that staging only mentioned in a comment counts as pinned.

A prod directory that does not exist, or prod manifests with no image at
all, fail the check: a check that found nothing to inspect has not passed.

Exits 1 on any violation, 2 if --base is not a commit. Run from anywhere:

    uv run --project tools python tools/promotion_check.py --base origin/main
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

PROMOTED_NAMESPACE = "prod"
SOURCE_NAMESPACE = "staging"
IMAGE_KEYS = {"image", "imageName"}
DIGEST = re.compile(r"@(sha256:[0-9a-f]{64})$")


def _load_yaml(text: str) -> list[Any]:
    return [doc for doc in yaml.safe_load_all(text) if doc]


def environment_paths(apps_dir: Path) -> dict[str, list[str]]:
    """Map each destination namespace to the repository paths its Applications apply."""
    paths: dict[str, list[str]] = {}
    for app_file in sorted(apps_dir.glob("*.y*ml")):
        for app in _load_yaml(app_file.read_text()):
            if not isinstance(app, dict) or app.get("kind") != "Application":
                continue
            spec = app["spec"]
            namespace = spec["destination"].get("namespace")
            for source in spec.get("sources") or [spec["source"]]:
                if namespace and "path" in source:
                    paths.setdefault(namespace, []).append(source["path"])
    return paths


def _walk_images(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in IMAGE_KEYS and isinstance(value, str):
                yield value
            else:
                yield from _walk_images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_images(item)


def image_refs(repo: Path, paths: list[str]) -> list[tuple[str, str]]:
    """Every (file, image reference) in the manifests directly under `paths`."""
    found: list[tuple[str, str]] = []
    for relative in paths:
        for manifest in sorted((repo / relative).glob("*.y*ml")):
            for doc in _load_yaml(manifest.read_text()):
                for ref in _walk_images(doc):
                    found.append((str(manifest.relative_to(repo)), ref))
    return found


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def is_commit(repo: Path, ref: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def pinned_before(repo: Path, base: str, digest: str, paths: list[str]) -> bool:
    """Whether any commit reachable from `base` added or removed `digest` under `paths`.

    `git log -S` lists the commits that change how many times the string
    occurs, so a digest that was ever pinned there has at least the commit
    that added it.
    """
    result = _git(repo, "log", "--format=%H", f"-S{digest}", base, "--", *paths)
    if result.returncode != 0:
        raise SystemExit(f"git log failed:\n{result.stderr}")
    return bool(result.stdout.strip())


def violations(repo: Path, base: str) -> tuple[list[str], int]:
    """Every problem found in prod's images, and how many images were checked."""
    environments = environment_paths(repo / "platform/infra/apps")
    for namespace in (PROMOTED_NAMESPACE, SOURCE_NAMESPACE):
        if namespace not in environments:
            raise SystemExit(f"no Application with a Git path targets namespace {namespace!r}")
    source_paths = environments[SOURCE_NAMESPACE]

    promoted_paths = environments[PROMOTED_NAMESPACE]
    problems = [
        f"{path}: {PROMOTED_NAMESPACE} Application path does not exist"
        for path in promoted_paths
        if not (repo / path).is_dir()
    ]
    refs = image_refs(repo, promoted_paths)
    if not refs:
        problems.append(f"no image found in {', '.join(promoted_paths)}: nothing was checked")
    for manifest, ref in refs:
        match = DIGEST.search(ref)
        if match is None:
            problems.append(f"{manifest}: {ref} is not pinned by digest")
        elif not pinned_before(repo, base, match.group(1), source_paths):
            problems.append(
                f"{manifest}: {ref} was never pinned in {SOURCE_NAMESPACE} "
                f"({', '.join(source_paths)}) before {base}"
            )
    return problems, len(refs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--base",
        required=True,
        help="commit the change is compared against (a pull request's base, or main before a push)",
    )
    args = parser.parse_args()
    repo: Path = args.repo

    if not is_commit(repo, args.base):
        print(f"--base {args.base!r} is not a commit in {repo}", file=sys.stderr)
        return 2

    problems, checked = violations(repo, args.base)
    if problems:
        report = "## Promotion check\n\n**Failed:**\n\n" + "\n".join(f"- {p}" for p in problems)
    else:
        report = (
            f"## Promotion check\n\nAll {checked} image references in {PROMOTED_NAMESPACE} are "
            f"pinned by a digest that {SOURCE_NAMESPACE} pinned on or before {args.base}."
        )
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(report + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
