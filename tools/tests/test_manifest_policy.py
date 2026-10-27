from pathlib import Path
from typing import Any

import pytest

from manifest_policy import (
    OWN_REGISTRY_PREFIX,
    check,
    image_references,
    image_violation,
    manifest_violations,
    prune_violations,
    source_violations,
)
from resource_budget import REPO_URL, load_applications

DIGEST = "sha256:" + "a" * 64
OWN_IMAGE = f"{OWN_REGISTRY_PREFIX}lagom-usgs:abc123@{DIGEST}"


def application(
    sources: list[dict[str, Any]] | None = None,
    sync_policy: dict[str, Any] | None = None,
    name: str = "demo",
) -> dict[str, Any]:
    git = {"repoURL": REPO_URL, "targetRevision": "main", "path": "platform/infra/demo"}
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": name},
        "spec": {
            "sources": sources if sources is not None else [git],
            "destination": {"namespace": "demo"},
            "syncPolicy": (
                sync_policy
                if sync_policy is not None
                else {"automated": {"prune": False, "selfHeal": True}}
            ),
        },
    }


def chart(revision: object) -> dict[str, Any]:
    return {"repoURL": "https://charts.example.com", "chart": "demo", "targetRevision": revision}


# Rule 1: explicit prune policy


@pytest.mark.parametrize("prune", [True, False])
def test_prune_set_explicitly_passes(prune: bool) -> None:
    assert prune_violations(application(sync_policy={"automated": {"prune": prune}})) == []


def test_prune_missing_from_automated_fails() -> None:
    app = application(sync_policy={"automated": {"selfHeal": True}})
    assert prune_violations(app) == [
        "demo: spec.syncPolicy.automated.prune is not set (true or false)"
    ]


def test_application_without_automated_block_fails() -> None:
    app = application(sync_policy={"syncOptions": ["CreateNamespace=true"]})
    assert len(prune_violations(app)) == 1


def test_application_without_sync_policy_fails() -> None:
    app = application()
    del app["spec"]["syncPolicy"]
    assert len(prune_violations(app)) == 1


def test_empty_automated_block_fails() -> None:
    # `automated:` with no keys parses as null: automated sync on, prune by default.
    assert len(prune_violations(application(sync_policy={"automated": None}))) == 1


def test_prune_string_is_not_a_boolean() -> None:
    app = application(sync_policy={"automated": {"prune": "false"}})
    assert prune_violations(app) == [
        "demo: spec.syncPolicy.automated.prune is 'false', not a boolean"
    ]


# Rule 2: pinned chart versions


@pytest.mark.parametrize(
    "revision", ["10.10.3", "0.29.1", "2.20.0", "1", "1.2.3-rc.1", "1.2.3+build.5", "1.2.3-rc.1+b5"]
)
def test_exact_chart_version_passes(revision: str) -> None:
    assert source_violations(application([chart(revision)])) == []


@pytest.mark.parametrize(
    "revision",
    ["*", "1.x", "1.2.*", "^1.2.3", "~1.2.3", ">=1.2.3", ">1 <2", "1.2.3 - 2.0.0", "latest",
     "v1.2.3", "main", "1.2.", "", None, 1.2],
)  # fmt: skip
def test_unpinned_chart_version_fails(revision: object) -> None:
    found = source_violations(application([chart(revision)]))
    assert found == [f"demo: chart demo targetRevision {revision!r} is not an exact version"]


def test_chart_without_target_revision_fails() -> None:
    source = chart("1.2.3")
    del source["targetRevision"]
    assert len(source_violations(application([source]))) == 1


# Rule 3: Git sources point at this repository


def test_git_source_in_this_repository_passes_on_main() -> None:
    assert source_violations(application()) == []


def test_values_ref_source_in_this_repository_passes() -> None:
    values = {"repoURL": REPO_URL, "targetRevision": "main", "ref": "values"}
    assert source_violations(application([chart("1.2.3"), values])) == []


def test_external_git_source_fails() -> None:
    other = {"repoURL": "https://github.com/someone/else.git", "targetRevision": "v1", "path": "x"}
    assert source_violations(application([other])) == [
        "demo: Git source 'https://github.com/someone/else.git' "
        f"is not this repository ({REPO_URL})"
    ]


def test_external_ref_source_fails() -> None:
    other = {"repoURL": "https://github.com/someone/else.git", "ref": "values"}
    assert len(source_violations(application([other]))) == 1


def test_source_without_repo_url_fails() -> None:
    assert len(source_violations(application([{"path": "x"}]))) == 1


def test_single_source_key_is_read() -> None:
    app = application()
    app["spec"]["source"] = app["spec"].pop("sources")[0]
    assert source_violations(app) == []
    app["spec"]["source"] = chart("latest")
    assert len(source_violations(app)) == 1


def test_application_with_no_source_fails() -> None:
    assert source_violations(application([])) == ["demo: no source or sources"]


def test_both_source_rules_report_together() -> None:
    other = {"repoURL": "https://example.com/x.git", "path": "x"}
    assert len(source_violations(application([chart("^1.0"), other]))) == 2


# Rule 4: pinned images


@pytest.mark.parametrize(
    "image",
    [
        "nginxinc/nginx-unprivileged:1.30.5-alpine",
        f"ghcr.io/cloudnative-pg/postgresql:18.6-minimal-trixie@{DIGEST}",
        f"registry.example.com/team/app@{DIGEST}",
        "localhost:5000/app:1.0",
        OWN_IMAGE,
        f"{OWN_REGISTRY_PREFIX}lagom-usgs@{DIGEST}",
    ],
)
def test_pinned_image_passes(image: str) -> None:
    assert image_violation(image) is None


@pytest.mark.parametrize(
    ("image", "reason"),
    [
        ("nginx", "neither a tag nor a digest"),
        ("localhost:5000/app", "neither a tag nor a digest"),
        ("nginx:latest", "uses the tag latest"),
        (f"nginx:latest@{DIGEST}", "uses the tag latest"),
        ("nginx:", "empty tag"),
        ("nginx:1.0@sha256:abc", "malformed digest"),
        ("nginx:1.0@md5:" + "a" * 32, "malformed digest"),
        ("nginx:1.0@sha256:" + "A" * 64, "malformed digest"),
        (f"{OWN_REGISTRY_PREFIX}lagom-usgs:abc123", "no digest (ADR-0015)"),
        (f"{OWN_REGISTRY_PREFIX}lagom-usgs", "no digest (ADR-0015)"),
        ("GHCR.IO/FilipeFantini/lagom-usgs:abc123", "no digest (ADR-0015)"),
        ("", "empty or not a string"),
        (None, "empty or not a string"),
    ],
)
def test_unpinned_image_fails(image: object, reason: str) -> None:
    found = image_violation(image)
    assert found is not None
    assert reason in found


def workload(
    kind: str, containers: list[dict[str, Any]], init: list[dict[str, Any]]
) -> dict[str, Any]:
    pod: dict[str, Any] = {"containers": containers, "initContainers": init}
    if kind == "CronJob":
        spec: dict[str, Any] = {"jobTemplate": {"spec": {"template": {"spec": pod}}}}
    else:
        spec = {"template": {"spec": pod}}
    return {"kind": kind, "metadata": {"name": "w"}, "spec": spec}


def test_references_include_containers_and_init_containers_of_a_cronjob() -> None:
    doc = workload("CronJob", [{"name": "main", "image": "a:1"}], [{"name": "dlt", "image": "b:2"}])
    assert image_references(doc) == [("initContainer dlt", "b:2"), ("container main", "a:1")]


def test_init_container_image_is_checked() -> None:
    doc = workload("Deployment", [{"name": "main", "image": "a:1"}], [{"name": "i", "image": "b"}])
    found, count = manifest_violations("app/Deployment/w", doc)
    assert count == 2
    assert found == ["app/Deployment/w initContainer i: image b has neither a tag nor a digest"]


def test_workload_without_image_fails() -> None:
    doc = workload("Deployment", [{"name": "main"}], [])
    found, _ = manifest_violations("x", doc)
    assert found == ["x container main: image None is empty or not a string"]


def test_workload_without_init_containers_is_read() -> None:
    doc = workload("StatefulSet", [{"name": "main", "image": "a:1"}], [])
    del doc["spec"]["template"]["spec"]["initContainers"]
    assert manifest_violations("x", doc) == ([], 1)


def cnpg_cluster(image_name: str | None) -> dict[str, Any]:
    spec: dict[str, Any] = {} if image_name is None else {"imageName": image_name}
    return {
        "apiVersion": "postgresql.cnpg.io/v1",
        "kind": "Cluster",
        "metadata": {"name": "postgres"},
        "spec": spec,
    }


def test_cnpg_image_name_with_digest_passes() -> None:
    assert manifest_violations(
        "x", cnpg_cluster(f"ghcr.io/cloudnative-pg/postgresql:18@{DIGEST}")
    ) == ([], 1)


def test_cnpg_image_name_latest_fails() -> None:
    found, count = manifest_violations(
        "x", cnpg_cluster("ghcr.io/cloudnative-pg/postgresql:latest")
    )
    assert count == 1
    assert "spec.imageName" in found[0]
    assert "uses the tag latest" in found[0]


def test_cnpg_own_image_name_without_digest_fails() -> None:
    found, _ = manifest_violations("x", cnpg_cluster(f"{OWN_REGISTRY_PREFIX}postgres:1"))
    assert len(found) == 1


def test_cnpg_cluster_without_image_name_has_nothing_to_check() -> None:
    assert manifest_violations("x", cnpg_cluster(None)) == ([], 0)


def test_other_kinds_are_ignored() -> None:
    doc = {"kind": "ConfigMap", "metadata": {"name": "c"}, "data": {"image": "latest"}}
    assert manifest_violations("x", doc) == ([], 0)


# The whole check, on a repository laid out like this one


def write_repo(root: Path, app: dict[str, Any], manifest: str) -> None:
    import yaml

    (root / "platform/infra/apps").mkdir(parents=True)
    (root / "platform/infra/demo").mkdir(parents=True)
    (root / "platform/infra/apps/demo.yaml").write_text(yaml.safe_dump(app))
    (root / "platform/infra/demo/deployment.yaml").write_text(manifest)


DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  template:
    spec:
      containers:
        - name: web
          image: {image}
"""


def test_check_passes_a_compliant_repository(tmp_path: Path) -> None:
    write_repo(tmp_path, application(), DEPLOYMENT.format(image="nginx:1.30.5"))
    assert check(tmp_path) == ([], [], 1, 1)


def test_check_reports_every_rule_at_once(tmp_path: Path) -> None:
    app = application(sync_policy={"automated": {"selfHeal": True}})
    write_repo(tmp_path, app, DEPLOYMENT.format(image="nginx:latest"))
    problems, unrendered, apps, images = check(tmp_path)
    assert (unrendered, apps, images) == ([], 1, 1)
    assert len(problems) == 2
    assert "prune is not set" in problems[0]
    assert problems[1].startswith("demo/Deployment/web container web:")


def test_check_does_not_render_an_application_with_an_unpinned_source(tmp_path: Path) -> None:
    external = {"repoURL": "https://github.com/someone/else.git", "path": "x"}
    write_repo(tmp_path, application([external]), DEPLOYMENT.format(image="nginx:1"))
    problems, unrendered, _, images = check(tmp_path)
    assert unrendered == ["demo"]
    assert images == 0
    assert len(problems) == 1


def test_check_fails_when_there_is_nothing_to_inspect(tmp_path: Path) -> None:
    (tmp_path / "platform/infra/apps").mkdir(parents=True)
    problems, _, apps, _ = check(tmp_path)
    assert apps == 0
    assert len(problems) == 1


# The Applications this repository really has. The images they render need
# helm and the network, so CI's `manifest policy` job runs the whole tool;
# the Application rules need neither and run here.


def test_real_applications_pass_the_application_rules() -> None:
    repo = Path(__file__).resolve().parents[2]
    apps = load_applications(repo)
    assert apps, "no Application found"
    for app in apps:
        assert prune_violations(app) == []
        assert source_violations(app) == []
