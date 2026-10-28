# platform/infra/

Everything Argo CD applies to the cluster. **Nothing outside this directory can
change the cluster**, and nothing inside it should be applied by hand after
bootstrap — merge to `main` and Argo CD converges.

| Path | What it is |
|---|---|
| `apps/` | One Argo CD Application per component. `root.yaml` watches this directory, so adding a file here adds a component |
| `argocd/values.yaml` | Helm values for Argo CD itself, which it applies to itself |
| `sealed-secrets/values.yaml` | Helm values for the controller that decrypts sealed secrets |
| `local-path/` | The storage provisioner every Postgres volume uses, vendored from upstream with k3s's settings ([ADR-0021](../../docs/adr/0021-k3s-packaged-components-under-git.md)) |
| `metrics-server/values.yaml` | Helm values for metrics-server, which serves `kubectl top` |
| `cloudnative-pg/values.yaml` | Helm values for the operator that runs Postgres from `Cluster` objects |
| `barman-cloud/values.yaml` | Helm values for the Barman Cloud plugin, which backs up each Postgres `Cluster` to R2 ([ADR-0025](../../docs/adr/0025-postgres-backup-barman-cloud-to-r2.md)) |
| `cert-manager/values.yaml` | Helm values for cert-manager, which issues the plugin's TLS certificates |
| `postgres-prod/` | The prod database: one CloudNativePG `Cluster`. The operator generates its credentials in the cluster; nothing is committed. Its `NetworkPolicy` admits only `prod` and the operator, so staging cannot reach it. Backed up to R2 (`ObjectStore`, `ScheduledBackup`, the sealed R2 token) |
| `postgres-staging/` | The staging database: a `Cluster` mirroring prod's, the developer's `lagom_dev` role and database, a ResourceQuota and LimitRange, the sealed credential for that role, its backup to R2 (`ObjectStore`, `ScheduledBackup`, the sealed R2 token), and Dagster's role, database and sealed secrets |
| `dagster-staging/values.yaml` | Helm values for staging's Dagster: webserver, daemon and the platform's code location, with its metadata in staging's Postgres ([ADR-0026](../../docs/adr/0026-dagster-one-instance-per-environment.md)). Its secrets (`dagster-db`, `r2-lake`) are sealed in `postgres-staging/`, which Argo CD applies as a directory |
| `hello/` | A trivial nginx that proves the loop works |

How it fits together, and why: [ADR-0009](../../docs/adr/0009-argocd-bootstrap-and-self-management.md).
Bootstrap and recovery commands: the runbook in
[`docs/architecture.md`](../../docs/architecture.md#13-runbook).
