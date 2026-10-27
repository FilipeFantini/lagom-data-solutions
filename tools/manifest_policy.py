"""Manifest policy check for everything Argo CD applies to the cluster.

Reads every Application in platform/infra/apps/ and renders it the way Argo CD
does (the rendering is resource_budget.py's), then enforces four rules (roadmap
Track G). Each turns something a reviewer must remember into a CI gate:

1. Explicit prune policy. Every Application sets spec.syncPolicy.automated.prune
   to true or false. A missing key is a violation: the default is a decision
   nobody wrote down, and for prune it decides whether a deleted file deletes a
   live object (a database, if the file was a Cluster).
2. Pinned chart versions. Every Helm source (one with `chart:`) has a
   targetRevision that is an exact version: digits and dots, optionally with a
   prerelease or build suffix (1.2.3, 1.2.3-rc.1, 1.2.3+build.5). Ranges,
   wildcards, `latest`, and an empty value move under the cluster's feet.
3. Git sources point at this repository. A source without `chart:` must use
   this repository's URL. targetRevision `main` is correct there by design:
   Argo CD watching main is the GitOps loop. Another repository is a violation
   until a rule for pinning it exists.
4. Pinned images. Every container and init container image in the rendered
   manifests, and a CloudNativePG Cluster's spec.imageName (required), has a tag or a
   digest, and the tag is not `latest`. Images under ghcr.io/filipefantini/
   must carry a digest (name[:tag]@sha256:<64 hex>), as ADR-0015 requires: a
   tag can be moved to other bytes after it was tested.

An Application with a violation in rule 2 or 3 is reported but not rendered:
Argo CD itself could not render it unambiguously, and its images are then
unchecked, which the report says.

What it does not check:
- That a pinned chart version or image digest exists, or is the one that was
  tested. promotion_check.py covers the order staging, then prod, for digests.
- Third-party images pinned by a tag only (nginx:1.30.5-alpine): a tag can be
  moved. Only this repository's own images are held to a digest.
- Images the operator or a chart creates at runtime, outside the rendered
  manifests (a CloudNativePG Cluster's other Pod images), images in custom
  resource fields other than a Cluster's imageName, and images named only in
  args or environment variables.
- Any other Application field: selfHeal, project, syncOptions, destination.
  Prune is checked for being explicit, not for being the right value.
- Kinds other than Application in platform/infra/apps/ (an ApplicationSet is
  ignored), and Applications created outside that directory.
- Chart contents beyond the rendered manifests, and anything helm template
  cannot see without a cluster (lookup, the cluster's API versions).
- Components k3s installs outside Git: they are not in any Application.

Exits 1 on any violation. Run from anywhere:

    uv run --project tools python tools/manifest_policy.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from resource_budget import (
    EPHEMERAL_KINDS,
    REPO_URL,
    RESIDENT_KINDS,
    is_cnpg_cluster,
    load_applications,
    pod_spec,
    render_application,
)

# Exact version: digits and dots, then an optional prerelease and build suffix.
VERSION_PATTERN = re.compile(r"\d+(\.\d+)*(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
OWN_REGISTRY_PREFIX = "ghcr.io/filipefantini/"


def sources_of(app: dict[str, Any]) -> list[dict[str, Any]]:
    spec = app["spec"]
    sources: list[dict[str, Any]] = spec.get("sources") or (
        [spec["source"]] if "source" in spec else []
    )
    return sources


def prune_violations(app: dict[str, Any]) -> list[str]:
    """Rule 1: spec.syncPolicy.automated.prune is set to a boolean."""
    name = app["metadata"]["name"]
    automated = ((app["spec"].get("syncPolicy") or {}).get("automated")) or {}
    if "prune" not in automated:
        return [f"{name}: spec.syncPolicy.automated.prune is not set (true or false)"]
    if not isinstance(automated["prune"], bool):
        return [f"{name}: spec.syncPolicy.automated.prune is {automated['prune']!r}, not a boolean"]
    return []


def source_violations(app: dict[str, Any]) -> list[str]:
    """Rules 2 and 3: chart versions are exact, Git sources are this repository."""
    name = app["metadata"]["name"]
    sources = sources_of(app)
    if not sources:
        return [f"{name}: no source or sources"]
    found = []
    for source in sources:
        if "chart" in source:
            revision = source.get("targetRevision")
            if not isinstance(revision, str) or not VERSION_PATTERN.fullmatch(revision):
                found.append(
                    f"{name}: chart {source['chart']} targetRevision {revision!r} "
                    "is not an exact version"
                )
        elif source.get("repoURL") != REPO_URL:
            found.append(
                f"{name}: Git source {source.get('repoURL')!r} is not this repository ({REPO_URL})"
            )
    return found


def image_violation(image: object) -> str | None:
    """Rule 4 for one image reference: the reason it is not pinned, or None."""
    if not isinstance(image, str) or not image:
        return f"image {image!r} is empty or not a string"
    reference, _, digest = image.partition("@")
    # A tag follows the last "/", so a registry port (host:5000/name) is not a tag.
    name, tag = reference, None
    if ":" in reference.rpartition("/")[2]:
        name, _, tag = reference.rpartition(":")
    if digest and not DIGEST_PATTERN.fullmatch(digest):
        return f"image {image} has a malformed digest (expected sha256:<64 hex>)"
    if tag == "latest":
        return f"image {image} uses the tag latest"
    if name.lower().startswith(OWN_REGISTRY_PREFIX) and not digest:
        return f"image {image} is this repository's own and has no digest (ADR-0015)"
    if not digest and tag is None:
        return f"image {image} has neither a tag nor a digest"
    if not digest and tag == "":
        return f"image {image} has an empty tag"
    return None


def image_references(doc: dict[str, Any]) -> list[tuple[str, object]]:
    """Every image a rendered manifest names: (where, image)."""
    if is_cnpg_cluster(doc):
        # A missing imageName is a violation, not an absence: the operator
        # would then run its own default image, which nothing here pins.
        return [("spec.imageName", doc["spec"].get("imageName"))]
    if doc.get("kind") not in RESIDENT_KINDS | EPHEMERAL_KINDS:
        return []
    spec = pod_spec(doc)
    return [
        (f"{key[:-1]} {container['name']}", container.get("image"))
        for key in ("initContainers", "containers")
        for container in spec.get(key) or []
    ]


def manifest_violations(label: str, doc: dict[str, Any]) -> tuple[list[str], int]:
    """Rule 4 for one rendered manifest: the violations, and how many images were checked."""
    references = image_references(doc)
    found = []
    for where, image in references:
        reason = image_violation(image)
        if reason is not None:
            found.append(f"{label} {where}: {reason}")
    return found, len(references)


def check(repo: Path) -> tuple[list[str], list[str], int, int]:
    """Run every rule: (violations, unrendered Applications, Applications, images checked)."""
    apps = load_applications(repo)
    problems: list[str] = []
    unrendered: list[str] = []
    images = 0
    if not apps:
        problems.append(f"no Application found in {repo / 'platform/infra/apps'}")
    for app in apps:
        name = app["metadata"]["name"]
        problems += prune_violations(app)
        broken = source_violations(app)
        problems += broken
        if broken:
            unrendered.append(name)
            continue
        docs = render_application(repo, app)
        if not docs:
            # An emptied directory or a mistyped path would otherwise pass
            # with nothing checked.
            problems.append(f"{name}: renders no manifests")
        for doc in docs:
            found, count = manifest_violations(f"{name}/{doc.get('kind')}/{_name(doc)}", doc)
            problems += found
            images += count
    return problems, unrendered, len(apps), images


def _name(doc: dict[str, Any]) -> str:
    return str((doc.get("metadata") or {}).get("name"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    problems, unrendered, apps, images = check(args.repo)
    if problems:
        report = "## Manifest policy\n\n**Failed:**\n\n" + "\n".join(f"- {p}" for p in problems)
        if unrendered:
            report += (
                "\n\nNot rendered, so their images were not checked: " + ", ".join(unrendered) + "."
            )
    else:
        report = (
            f"## Manifest policy\n\nAll {apps} Applications set prune explicitly and pin "
            f"their chart versions and Git sources; all {images} rendered image references "
            "are pinned."
        )
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(report + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
