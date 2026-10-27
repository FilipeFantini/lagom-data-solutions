# platform/

The shared backbone. Changes here affect every workload, so they change rarely
and are reviewed accordingly.

| Subdirectory | Contents | Born in |
|---|---|---|
| `infra/` | Kubernetes manifests, Argo CD applications, Helm values | M1 |
| `warehouse/` | the single dbt project: silver and gold models, tests, and the profile | M2 |
| `orchestration/` | Dagster deployment and shared resources | M3 |

**Argo CD watches `platform/infra/` only.** Nothing outside that path can change
the cluster, which keeps the deployment boundary explicit and auditable.

`warehouse/` holds one dbt project rather than one per service, because dbt-core
has no cross-project `ref()`. Models are laid out as
`models/staging/<service>/`, mirroring the service directory name, and
`models/marts/<domain>/` for the modelled layer. That naming is the only thing
connecting a service to its models — see
[ADR-0006](../docs/adr/0006-monorepo-layout.md).
