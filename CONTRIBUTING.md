# Contributing

The workflow is in place from the first commit, even with one developer, so that
adding the second changes nothing.

Start with [`CLAUDE.md`](CLAUDE.md). For anything larger than a single-file
change, read [`docs/engineering-protocol.md`](docs/engineering-protocol.md)
first.

## Language

Conversation happens in Brazilian Portuguese. **Everything written into the
repository is in English** — code, comments, commits, docs, PR descriptions, log
messages.

## Workflow

1. Branch from `main`. Only `main` is reconciled by Argo CD, so nothing reaches
   the cluster from a branch.
2. Commit in small, coherent steps. One concern per commit.
3. Open a pull request and let CI run.
4. Get a review. Working alone, the review is the `reviewer` agent
   ([`.claude/agents/reviewer.md`](.claude/agents/reviewer.md)): an
   independent pass that runs the adversarial review of
   [`docs/engineering-protocol.md`](docs/engineering-protocol.md) §12 Phase E.
   Blocker and major findings are fixed before merge. GitHub does not let an
   author approve their own pull request, so the architect posts the verdict
   with `gh pr review --comment`.
5. Merge to `main`. Argo CD converges the cluster.

**Agents.** The main Claude session acts as architect. It can hand a scoped
task to the `implementer` agent
([`.claude/agents/implementer.md`](.claude/agents/implementer.md)) with a brief —
files, acceptance criteria, constraints. The implementer commits on a local
branch, never pushes or changes the cluster, and reports validation evidence;
the architect reads the diff, opens the pull request, and sends it to review.
**Most of these limits are instructions, not enforced permissions.** One part is
enforced: [`.claude/settings.json`](.claude/settings.json) denies, to every
Claude Code session and agent, the git commands that discard uncommitted work
or rewrite shared history — `reset --hard`, `checkout --` and `checkout HEAD`,
`restore`, `clean`, `switch -f`, `stash drop`/`clear`, `branch -D`/`-f`, force
pushes in any flag position or `+` refspec, remote deletes — and pushes to
`main`. Two harmless forms are blocked with them, as accepted friction:
`git restore --staged` (use `git reset <file>`) and `git clean -n`. Claude Code
cannot scope these
rules to one agent, so they bind the main session too. They match the command
as written: `git -C . reset --hard` is not caught, so they stop mistakes, not a
determined bypass. Everything else — no push from the implementer, no
`kubectl apply` — is still instruction only. Changing the file is a guardrail
change ([`engineering-protocol.md`](docs/engineering-protocol.md) §18 rule 3).

Branch naming: `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` followed by a
short description.

## Commits

Conventional Commits:

```
feat(ingestion): add USGS earthquake source
fix(dbt): correct timezone handling in silver layer
docs(adr): record table format decision
```

Explain **why** in the body when the change is not self-evident. The subject
says what changed; the body says what it is protecting against.

## Checks

CI runs on every pull request and on `main`
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): lint, types, and tests
for `tools/` and for every project under `services/`; lint and parse of the dbt
project; a secret scan of the whole history (see [Secrets](#secrets)); the
promotion check (prod pins only digests staging pinned first,
[ADR-0015](docs/adr/0015-images-on-ghcr.md)); and the resource budget check.
**A red check is not merged.**

### Branch protection

`main` is protected by a repository ruleset named `main`, enabled on
2026-10-27 when the repository became public
([ADR-0017](docs/adr/0017-public-repository-from-a-snapshot.md)). GitHub
enforces, with no bypass — the operator follows the same rules:

- changes reach `main` only through a pull request;
- the six CI checks above must pass, named exactly as their jobs report:
  `tools (lint, types, tests)`, `services (lint, types, tests)`,
  `warehouse (lint, parse)`, `secret scan`, `resource budget`, and
  `promotion (prod pins only staging's digests)` — a renamed job must be
  renamed in the ruleset too, or every pull request waits for a check that
  never reports;
- `main` cannot be force-pushed or deleted.

Inspect what applies with
`gh api repos/FilipeFantini/lagom-data-solutions/rules/branches/main`.

What it does not enforce:

- **Review.** Zero approvals are required: GitHub does not let authors
  approve their own pull requests, and there is one developer. Revisit when a
  second developer joins (M7).
- **A gate approving a change to itself.** A pull request runs the workflow as
  it edits it, so a change under `.github/workflows/` can change what its own
  required checks do. Changes to CI, agent definitions, permissions, RBAC, and
  secrets are therefore merged by the operator, by convention
  ([ADR-0013](docs/adr/0013-agent-driven-development-guardrails.md) rule 2).
  No agent merges on its own until rule 3's criteria are met.

Until 2026-10-27 `main` had no protection: on a private repository it needs a
paid plan, and the operator accepted that as an exception (2026-10-13) and as
debt for ADR-0013 (2026-10-16).

## Pull requests

A pull request states:

- **What changed and why**, in prose a reader can follow without the diff.
- **How it was validated** — the command run and its real result, not an
  assurance. A green build is not a working feature.
- **Which documents were updated**, or an explicit statement that none were
  affected and why.
- **Open items and accepted risks**, if any.
- **For a fix to a defect that reached `main`:** the escape, and the
  deterministic check that now catches it — or why none can
  ([ADR-0013](docs/adr/0013-agent-driven-development-guardrails.md) rule 1).

Guardrail changes are merged by the operator only
([`engineering-protocol.md`](docs/engineering-protocol.md) §18 rule 3).

Do not include unrelated refactoring. A diff that touches files the description
does not mention will be sent back.

## Required checks

A pull request is not ready while any of these is true:

- Build, lint, type check, or a required test fails.
- Acceptance criteria are not validated by evidence.
- A secret appears in the diff.
- Declared resource requests exceed the ceiling in
  [`docs/architecture.md`](docs/architecture.md).
- Documentation required by [`CLAUDE.md`](CLAUDE.md) §5 was not updated.

Never weaken a check to get a green result. If a check is wrong, fix the check
in its own commit, with the reason stated.

## Adding a data source

This is the most common change, and the platform is designed so it is
configuration rather than code:

1. Choose the pattern — batch goes through dlt, continuous events through
   Redpanda Connect ([ADR-0003](docs/adr/0003-ingestion-split-dlt-benthos.md)).
2. Declare the source config. Credentials go to the cluster secret mechanism,
   never into the repository.
3. Add dbt models for bronze, silver, and gold, with the schema contract the
   next layer can rely on.
4. Add reconciliation and freshness tests —
   [`docs/engineering-protocol.md`](docs/engineering-protocol.md) §16.4.
5. Add fixtures for tests. **Tests never call the live API.**
6. Declare resource requests and limits.
7. Update [`docs/architecture.md`](docs/architecture.md) if the data flow or the
   budget changed.

## Secrets

Never commit a credential, token, or connection string — not even a
placeholder that looks real. Secrets are committed only as Sealed Secrets
(`*-sealed.yaml`; how to seal one is in the runbook), and never appear in logs,
including inside error messages and tracebacks.

If a secret is committed by accident, treat it as compromised: rotate it first,
then clean the history.

**CI scans for secrets** with [gitleaks](https://github.com/gitleaks/gitleaks)
over every commit in the history, with its default rules and one exception for
Sealed Secrets ciphertext, explained in [`.gitleaks.toml`](.gitleaks.toml). A
finding fails the build. A false positive is answered by narrowing a rule in
that file, with the reason written next to it — never by a `.gitleaksignore`
entry nobody can explain, and never by removing the job.

What the scan does not check: secrets that match no rule (a password with low
entropy, or an unusual format), anything outside Git (shell history, CI logs,
the cluster), and whether a sealed file is really a `SealedSecret`. The
ciphertext exception matches the shape of a line, not the file it is in, so a
real credential written as `key: Ag` followed by 500 or more base64 characters
would pass the generic rule in any file. It lowers
the chance that a credential reaches the history; it does not prove none did.
