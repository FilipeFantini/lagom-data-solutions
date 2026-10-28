from pathlib import Path
from typing import Any

import pytest

from resource_budget import (
    cnpg_violations,
    cnpg_workload,
    is_cnpg_cluster,
    parse_bytes,
    pod_request_bytes,
    pod_spec,
    read_ceiling_bytes,
    replicas,
    violations,
)

MI = 2**20


def container(name: str, memory: str | None = "64Mi", limit: str | None = "128Mi",
              cpu: str | None = "10m") -> dict[str, Any]:  # fmt: skip
    requests = {k: v for k, v in (("memory", memory), ("cpu", cpu)) if v is not None}
    limits = {"memory": limit} if limit is not None else {}
    return {"name": name, "resources": {"requests": requests, "limits": limits}}


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [("64Mi", 64 * MI), ("1Gi", 2**30), ("500M", 500 * 10**6), ("1048576", MI), (2048, 2048)],
)
def test_parse_bytes(quantity: str | int, expected: int) -> None:
    assert parse_bytes(quantity) == expected


def test_parse_bytes_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="unrecognised"):
        parse_bytes("12Xi")


def test_pod_request_sums_regular_containers() -> None:
    spec = {"containers": [container("a", "64Mi"), container("b", "32Mi")]}
    assert pod_request_bytes(spec) == 96 * MI


def test_pod_request_takes_larger_init_container() -> None:
    spec = {
        "initContainers": [container("init", "128Mi")],
        "containers": [container("a", "64Mi"), container("b", "32Mi")],
    }
    assert pod_request_bytes(spec) == 128 * MI


def test_pod_request_counts_missing_request_as_zero() -> None:
    assert pod_request_bytes({"containers": [container("a", memory=None)]}) == 0


def test_violations_name_every_missing_resource() -> None:
    spec = {
        "initContainers": [container("init", cpu=None)],
        "containers": [container("ok"), container("bare", memory=None, limit=None, cpu=None)],
    }
    assert violations("app/Deployment/x", spec) == [
        "app/Deployment/x container init: no CPU request",
        "app/Deployment/x container bare: no memory request, memory limit, CPU request",
    ]


def test_violations_accepts_complete_container() -> None:
    assert violations("x", {"containers": [container("ok")]}) == []


def test_pod_spec_reaches_into_cronjob() -> None:
    inner = {"containers": [container("c")]}
    cronjob = {"kind": "CronJob", "spec": {"jobTemplate": {"spec": {"template": {"spec": inner}}}}}
    assert pod_spec(cronjob) is inner


def test_replicas_default_and_explicit() -> None:
    assert replicas({"kind": "Deployment", "spec": {}}) == 1
    assert replicas({"kind": "Deployment", "spec": {"replicas": 0}}) == 0
    assert replicas({"kind": "DaemonSet", "spec": {}}) == 1


def test_read_ceiling_from_architecture(tmp_path: Path) -> None:
    doc = tmp_path / "architecture.md"
    doc.write_text("**Ceiling enforced in CI: 2.6 GB of declared requests.** More text.")
    assert read_ceiling_bytes(doc) == int(2.6 * 2**30)


def test_read_ceiling_fails_loudly_when_missing(tmp_path: Path) -> None:
    doc = tmp_path / "architecture.md"
    doc.write_text("no ceiling here")
    with pytest.raises(SystemExit):
        read_ceiling_bytes(doc)


def cnpg_cluster(
    instances: int | None = 1, resources: dict[str, Any] | None = None
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "resources": resources
        if resources is not None
        else {
            "requests": {"cpu": "50m", "memory": "300Mi"},
            "limits": {"memory": "512Mi"},
        }
    }
    if instances is not None:
        spec["instances"] = instances
    return {
        "apiVersion": "postgresql.cnpg.io/v1",
        "kind": "Cluster",
        "metadata": {"name": "postgres"},
        "spec": spec,
    }


def test_is_cnpg_cluster_matches_only_the_cnpg_api() -> None:
    assert is_cnpg_cluster(cnpg_cluster())
    assert not is_cnpg_cluster({**cnpg_cluster(), "apiVersion": "example.com/v1"})
    assert not is_cnpg_cluster({**cnpg_cluster(), "kind": "Pooler"})


@pytest.mark.parametrize(("instances", "expected_mi"), [(1, 300), (3, 900)])
def test_cnpg_workload_multiplies_request_by_instances(instances: int, expected_mi: int) -> None:
    workload = cnpg_workload("postgres-prod", cnpg_cluster(instances))
    assert workload.kind == "Cluster"
    assert workload.replicas == instances
    assert workload.total == expected_mi * MI


def test_cnpg_workload_defaults_to_one_instance() -> None:
    workload = cnpg_workload("postgres-prod", cnpg_cluster(instances=None))
    assert workload.replicas == 1
    assert workload.total == 300 * MI


def test_cnpg_violations_accept_complete_resources() -> None:
    assert cnpg_violations("x", cnpg_cluster()) == []


@pytest.mark.parametrize(
    ("resources", "missing"),
    [
        ({"requests": {"cpu": "50m"}, "limits": {"memory": "512Mi"}}, "memory request"),
        ({"requests": {"cpu": "50m", "memory": "300Mi"}}, "memory limit"),
        ({"requests": {"memory": "300Mi"}, "limits": {"memory": "512Mi"}}, "CPU request"),
    ],
)
def test_cnpg_violations_name_each_missing_resource(
    resources: dict[str, Any], missing: str
) -> None:
    assert cnpg_violations("app/Cluster/postgres", cnpg_cluster(resources=resources)) == [
        f"app/Cluster/postgres spec.resources: no {missing}"
    ]


def test_cnpg_violations_when_resources_absent() -> None:
    cluster = cnpg_cluster()
    del cluster["spec"]["resources"]
    assert cnpg_violations("x", cluster) == [
        "x spec.resources: no memory request, memory limit, CPU request"
    ]


def test_cnpg_null_fields_report_violations_instead_of_crashing() -> None:
    cluster = cnpg_cluster(resources={"requests": None, "limits": None})
    cluster["spec"]["instances"] = None
    assert cnpg_violations("x", cluster) == [
        "x spec.resources: no memory request, memory limit, CPU request"
    ]
    workload = cnpg_workload("app", cluster)
    assert (workload.replicas, workload.total) == (1, 0)


def test_jobs_peak_counts_every_job_at_once() -> None:
    from resource_budget import Workload, jobs_peak_bytes

    staging = Workload("postgres-staging", "CronJob", "usgs-pipeline", 1, 256 * MI)
    prod = Workload("postgres-prod", "CronJob", "usgs-pipeline", 1, 256 * MI)
    assert jobs_peak_bytes([staging, prod]) == 512 * MI
    assert jobs_peak_bytes([]) == 0


def object_store(resources: dict[str, Any] | None) -> dict[str, Any]:
    spec: dict[str, Any] = {"configuration": {"destinationPath": "s3://bucket/"}}
    if resources is not None:
        spec["instanceSidecarConfiguration"] = {"resources": resources}
    return {
        "apiVersion": "barmancloud.cnpg.io/v1",
        "kind": "ObjectStore",
        "metadata": {"name": "r2-backups"},
        "spec": spec,
    }


def backed_up_cluster(instances: int = 1) -> dict[str, Any]:
    cluster = cnpg_cluster(instances)
    cluster["spec"]["plugins"] = [
        {
            "name": "barman-cloud.cloudnative-pg.io",
            "isWALArchiver": True,
            "parameters": {"barmanObjectName": "r2-backups"},
        }
    ]
    return cluster


SIDECAR = {"requests": {"cpu": "10m", "memory": "64Mi"}, "limits": {"memory": "256Mi"}}


@pytest.mark.parametrize(("instances", "expected_mi"), [(1, 364), (2, 728)])
def test_cnpg_workload_adds_the_barman_sidecar_per_instance(
    instances: int, expected_mi: int
) -> None:
    stores = {"r2-backups": object_store(SIDECAR)}
    workload = cnpg_workload("postgres-staging", backed_up_cluster(instances), stores)
    assert workload.total == expected_mi * MI


def test_cnpg_without_plugin_ignores_object_stores() -> None:
    stores = {"r2-backups": object_store(SIDECAR)}
    assert cnpg_workload("app", cnpg_cluster(), stores).total == 300 * MI
    assert cnpg_violations("x", cnpg_cluster(), stores) == []


def test_cnpg_violations_accept_a_complete_sidecar() -> None:
    assert cnpg_violations("x", backed_up_cluster(), {"r2-backups": object_store(SIDECAR)}) == []


def test_cnpg_violations_name_a_sidecar_without_resources() -> None:
    assert cnpg_violations("x", backed_up_cluster(), {"r2-backups": object_store(None)}) == [
        "x ObjectStore r2-backups instanceSidecarConfiguration.resources: "
        "no memory request, memory limit, CPU request"
    ]


def test_cnpg_violations_name_an_object_store_not_rendered() -> None:
    assert cnpg_violations("x", backed_up_cluster(), {}) == [
        "x names ObjectStore 'r2-backups', not rendered by its Application"
    ]


def test_declared_ephemeral_reads_the_annotation() -> None:
    from resource_budget import declared_ephemeral

    app = {
        "metadata": {
            "name": "dagster-staging",
            "annotations": {"lagom.dev/ephemeral-memory-request": "384Mi"},
        }
    }
    workload = declared_ephemeral(app)
    assert workload is not None
    assert (workload.app, workload.kind, workload.total) == (
        "dagster-staging",
        "declared",
        384 * MI,
    )


def test_declared_ephemeral_absent_without_annotation() -> None:
    from resource_budget import declared_ephemeral

    assert declared_ephemeral({"metadata": {"name": "x"}}) is None
    assert declared_ephemeral({"metadata": {"name": "x", "annotations": None}}) is None
