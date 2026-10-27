"""Resource budget check for everything Argo CD applies to the cluster.

Renders every Application in platform/infra/apps/ the way Argo CD does, then
enforces engineering-protocol.md §16.5:

1. Every container, init containers included, declares a memory request, a
   memory limit, and a CPU request.
2. Resident memory requests, plus the components k3s installs itself, plus
   every ephemeral job at once, fit within the ceiling stated in
   docs/architecture.md.

CloudNativePG Cluster objects (postgresql.cnpg.io/v1) are counted too. Their
Pods are created by the operator at runtime, so no Pod spec exists in Git to
inspect; the Cluster's spec.resources is what the operator copies into every
instance, and spec.instances is the replica count. Rule 1 applies to
spec.resources as if it were a single container.

Exits 1 on any violation. Run from anywhere:

    uv run --project tools python tools/resource_budget.py
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_URL = "https://github.com/FilipeFantini/lagom-data-solutions.git"
CEILING_PATTERN = re.compile(r"Ceiling enforced in CI: ([0-9.]+) GB of declared requests")

# Requests counted per Pod replica. A DaemonSet counts once: one node today.
RESIDENT_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Pod"}
EPHEMERAL_KINDS = {"Job", "CronJob"}
CNPG_API_VERSION = "postgresql.cnpg.io/v1"

_BINARY = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}
_DECIMAL = {"k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}
MI = 2**20


def parse_bytes(quantity: str | int) -> int:
    """Convert a Kubernetes memory quantity ("64Mi", "1G", "1048576") to bytes."""
    text = str(quantity).strip()
    for suffix, factor in {**_BINARY, **_DECIMAL}.items():
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * factor)
    try:
        return int(float(text))
    except ValueError:
        raise ValueError(f"unrecognised memory quantity: {quantity!r}") from None


def pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the Pod spec inside any workload kind."""
    kind = doc["kind"]
    if kind == "Pod":
        spec: dict[str, Any] = doc["spec"]
    elif kind == "CronJob":
        spec = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    else:
        spec = doc["spec"]["template"]["spec"]
    return spec


def _containers(spec: dict[str, Any], key: str) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = spec.get(key) or []
    return containers


def _memory_request(container: dict[str, Any]) -> int:
    value = ((container.get("resources") or {}).get("requests") or {}).get("memory")
    return parse_bytes(value) if value is not None else 0


def pod_request_bytes(spec: dict[str, Any]) -> int:
    """Memory the scheduler reserves for one Pod.

    Init containers run one at a time before the others, so the Pod needs the
    larger of the biggest init container and the sum of the regular ones.
    """
    regular = sum(_memory_request(c) for c in _containers(spec, "containers"))
    init = max((_memory_request(c) for c in _containers(spec, "initContainers")), default=0)
    return max(regular, init)


def _missing_resources(resources: dict[str, Any] | None) -> list[str]:
    """Name each of the three required resources that `resources` does not declare."""
    requests = (resources or {}).get("requests") or {}
    limits = (resources or {}).get("limits") or {}
    return [
        name
        for name, present in (
            ("memory request", "memory" in requests),
            ("memory limit", "memory" in limits),
            ("CPU request", "cpu" in requests),
        )
        if not present
    ]


def violations(label: str, spec: dict[str, Any]) -> list[str]:
    """List every container in the Pod spec that misses a required resource."""
    found = []
    for key in ("initContainers", "containers"):
        for container in _containers(spec, key):
            missing = _missing_resources(container.get("resources"))
            if missing:
                found.append(f"{label} container {container['name']}: no {', '.join(missing)}")
    return found


def is_cnpg_cluster(doc: dict[str, Any]) -> bool:
    return doc.get("apiVersion") == CNPG_API_VERSION and doc.get("kind") == "Cluster"


def cnpg_violations(label: str, doc: dict[str, Any]) -> list[str]:
    """List the required resources a CloudNativePG Cluster does not declare."""
    missing = _missing_resources(doc["spec"].get("resources"))
    return [f"{label} spec.resources: no {', '.join(missing)}"] if missing else []


def cnpg_workload(app: str, doc: dict[str, Any]) -> Workload:
    """A Cluster as a resident workload: `instances` Pods, each requesting spec.resources."""
    spec = doc["spec"]
    return Workload(
        app,
        "Cluster",
        doc["metadata"]["name"],
        1 if spec.get("instances") is None else spec["instances"],
        _memory_request({"resources": spec.get("resources")}),
    )


def replicas(doc: dict[str, Any]) -> int:
    if doc["kind"] in {"Deployment", "StatefulSet", "ReplicaSet"}:
        count: int = doc["spec"].get("replicas", 1)
        return count
    return 1


def read_ceiling_bytes(architecture: Path) -> int:
    """The ceiling is stated once, in architecture.md; GB there means GiB."""
    match = CEILING_PATTERN.search(architecture.read_text())
    if match is None:
        raise SystemExit(f"ceiling sentence not found in {architecture}")
    return int(float(match.group(1)) * 2**30)


def _load_yaml(text: str) -> list[dict[str, Any]]:
    return [doc for doc in yaml.safe_load_all(text) if doc]


def _render_chart(
    repo: Path, source: dict[str, Any], namespace: str, refs: set[str]
) -> list[dict[str, Any]]:
    helm = source.get("helm") or {}
    unsupported = {"values", "valuesObject", "parameters"} & helm.keys()
    if unsupported:
        raise SystemExit(f"chart {source['chart']}: inline {sorted(unsupported)} not supported")
    command = [
        "helm", "template", helm.get("releaseName", source["chart"]), source["chart"],
        "--repo", source["repoURL"], "--version", source["targetRevision"],
        "--namespace", namespace,
    ]  # fmt: skip
    for value_file in helm.get("valueFiles", []):
        ref, _, relative = value_file.removeprefix("$").partition("/")
        if not value_file.startswith("$") or ref not in refs:
            raise SystemExit(f"chart {source['chart']}: value file {value_file} not from this repo")
        command += ["--values", str(repo / relative)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"helm template failed for {source['chart']}:\n{result.stderr}")
    return _load_yaml(result.stdout)


def render_application(repo: Path, app: dict[str, Any]) -> list[dict[str, Any]]:
    """Render an Application's sources into the manifests Argo CD would apply."""
    spec = app["spec"]
    sources: list[dict[str, Any]] = spec.get("sources") or [spec["source"]]
    namespace = spec["destination"].get("namespace", "default")
    refs = {s["ref"] for s in sources if "ref" in s and s["repoURL"] == REPO_URL}
    docs: list[dict[str, Any]] = []
    for source in sources:
        if "chart" in source:
            docs += _render_chart(repo, source, namespace, refs)
        elif "path" in source:
            if source["repoURL"] != REPO_URL:
                raise SystemExit(f"{app['metadata']['name']}: path source outside this repo")
            for path in sorted((repo / source["path"]).glob("*.y*ml")):
                docs += _load_yaml(path.read_text())
        elif "ref" not in source:
            raise SystemExit(f"{app['metadata']['name']}: source with neither chart nor path")
    return docs


@dataclass(frozen=True)
class Workload:
    app: str
    kind: str
    name: str
    replicas: int
    request: int

    @property
    def total(self) -> int:
        return self.request * self.replicas


def jobs_peak_bytes(ephemeral: list[Workload]) -> int:
    """Memory every ephemeral job requests if all of them run at the same time.

    Counting only the largest job assumes no two ever overlap, and nothing
    enforces that: staging's and prod's pipelines share a schedule, and a run
    started by hand can land on top of a scheduled one. The sum is the peak
    the scheduler may really have to place. It overstates jobs whose
    schedules never meet, which is the safe error for a memory gate.
    """
    return sum(w.total for w in ephemeral)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--k3s-builtins-mi",
        type=int,
        default=170,
        help="requests of components k3s installs outside Git (architecture.md §11)",
    )
    args = parser.parse_args()
    repo: Path = args.repo

    ceiling = read_ceiling_bytes(repo / "docs/architecture.md")
    resident: list[Workload] = []
    ephemeral: list[Workload] = []
    problems: list[str] = []

    for app_file in sorted((repo / "platform/infra/apps").glob("*.y*ml")):
        for app in _load_yaml(app_file.read_text()):
            if app.get("kind") != "Application":
                continue
            app_name = app["metadata"]["name"]
            for doc in render_application(repo, app):
                if is_cnpg_cluster(doc):
                    label = f"{app_name}/Cluster/{doc['metadata']['name']}"
                    problems += cnpg_violations(label, doc)
                    resident.append(cnpg_workload(app_name, doc))
                    continue
                kind = doc.get("kind")
                if kind not in RESIDENT_KINDS | EPHEMERAL_KINDS:
                    continue
                spec = pod_spec(doc)
                label = f"{app_name}/{kind}/{doc['metadata']['name']}"
                problems += violations(label, spec)
                workload = Workload(
                    app_name, kind, doc["metadata"]["name"], replicas(doc), pod_request_bytes(spec)
                )
                (resident if kind in RESIDENT_KINDS else ephemeral).append(workload)

    builtins = args.k3s_builtins_mi * MI
    jobs = jobs_peak_bytes(ephemeral)
    total = sum(w.total for w in resident) + builtins + jobs

    lines = ["| Application | Kind | Name | Replicas | Request (MiB) |", "|---|---|---|---|---|"]
    for w in sorted(resident, key=lambda w: w.total, reverse=True):
        lines.append(f"| {w.app} | {w.kind} | {w.name} | {w.replicas} | {w.total / MI:.0f} |")
    lines += [
        f"| k3s built-ins | — | outside Git | — | {builtins / MI:.0f} |",
        f"| ephemeral jobs, all at once | — | {len(ephemeral)} | — | {jobs / MI:.0f} |",
        f"| **Total** | | | | **{total / MI:.0f}** of {ceiling / MI:.0f} ceiling |",
    ]
    status = "within" if total <= ceiling else "OVER"
    report = "\n".join(
        ["## Resource budget", "", *lines, "", f"**{status} budget**: {total / MI:.0f} MiB"]
    )
    if problems:
        report += "\n\n### Missing resources\n\n" + "\n".join(f"- {p}" for p in problems)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(report + "\n")
    return 1 if problems or total > ceiling else 0


if __name__ == "__main__":
    sys.exit(main())
