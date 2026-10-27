# ADR-0013 — Agent-driven development behind enforced guardrails

- **Status:** Accepted
- **Date:** 2026-10-16

## Context and problem

The goal of this platform goes beyond running data pipelines cheaply. Any
developer should be able to extend it **through prompts alone**: describe a
source or a data product, and agents carry development, testing, and deployment,
and refuse changes that head the wrong way. The point is to do more, in scope
and in volume, at the same quality or better. The operator keeps understanding
the stack, the flows, and the decisions, without reading every line of code.

Today the pieces are partly there. A `reviewer` and an `implementer` agent exist
([`.claude/agents/`](../../.claude/agents/)). CI runs lint, types, tests, and the
resource budget. But most of the rules that keep the platform correct are prose
in [`CLAUDE.md`](../../CLAUDE.md) and
[`engineering-protocol.md`](../engineering-protocol.md). Prose works only when
it is read and followed. An agent can misread it or skip it, or be steered away
from it by injected text. The first agent reviews on 2026-10-16 showed the gap:
the agents' "never push, never change the cluster" was instruction only, and
nothing technical enforced it.

The core problem is that **human attention does not scale with volume, and
neither does prose.** Throughput can grow only as far as the guardrails that
hold without anyone watching.

## Requirements and constraints

- Quality must not drop as more changes go through agents. A defect that
  reaches `main` must lead to a guardrail that would have caught it.
- A gate is enforced **outside the agent it gates**
  ([`engineering-protocol.md`](../engineering-protocol.md) §10). An agent
  cannot certify its own work.
- The operator can follow every decision from the ADRs and
  [`architecture.md`](../architecture.md), with no need to read the code.
- No resident cost on the node without a trigger. CI runs on GitHub's machines
  and costs nothing on the node.
- No speculative structure. Each guardrail is built when the risk it covers is
  real, not because it is on a list.

## Alternatives considered

**Prose rules plus agent review, as today.** Cheap and flexible. Rejected as
the end state: it is advisory, and its failure is silent. A review that misses
something reports nothing.

**A human reviews and merges every change, forever.** Safe, but it caps
throughput at one person's attention, which is the limit this decision exists
to remove.

**Full autonomy now: agents merge everything.** Rejected. The gates do not yet
cover what an agent can change, and GitOps amplifies a bad merge, because Argo
CD applies `main` to the cluster within minutes, with no further step.

**A policy engine inside the cluster (Kyverno, OPA Gatekeeper) now.** Such an
engine rejects bad objects at admission, whoever sends them. It is the right
tool when several writers reach the cluster. Here only Argo CD writes, and it
writes only what is in `main`, so a check in CI sees the same changes for zero
resident memory. Deferred with a trigger: a second writer to the cluster.

## Decision

**Guardrails come in five layers.** Each one catches what the layer before it
cannot. **A rule moves to the most deterministic layer that can express it.**

| Layer | Question it answers | Mechanism | Today |
|---|---|---|---|
| 1. Permissions | What may an agent do at all? | Claude Code permission deny rules (whether they can be scoped to one agent is unverified); least-privilege credentials | none — instructions only |
| 2. Deterministic gates | What may a change contain? | CI checks: lint, types, tests, resource budget, secret scan, manifest and architecture policy, `dbt test` and reconciliation | lint, types, tests, budget |
| 3. Agent review | Is the change right where no rule can say? | `reviewer` agent, judged against the ADRs | first used on archive PR #15 |
| 4. Post-deploy verification | Did what reached the cluster behave? | Argo CD sync and health, memory against requests, logs; data freshness and reconciliation | manual |
| 5. Human | Which way should the platform go? | the operator accepts ADRs and merges what is not yet automated | every merge |

*Later state of layer 1 (2026-10-16): Claude Code cannot scope Bash rules to one
agent; destructive git commands are denied for every session — see roadmap
Track G. The table above records the state when this ADR was accepted.*

Four rules govern the layers:

1. **Every escape becomes a gate.** A defect found after merge is recorded in
   the pull request that fixes it. That pull request also adds the
   deterministic check that would have caught it, or says why none can. This
   ratchet is how quality rises with volume.
2. **A gate never approves a change to itself.** Changes to CI, to agent
   definitions, to permissions, to RBAC, or to secrets always need the
   operator's merge, whatever level of autonomy other changes have reached.
3. **Autonomy is earned per class of change.** The classes are documentation,
   `tools/` code, data models, infrastructure manifests, and guardrails. A class
   can be merged by an agent only when (a) its layer-2 gates are deterministic
   and required by branch protection, and (b) it has gone through a run of
   merges with no escape. The size of that run is set when the first class is
   proposed for promotion. Until then, every merge is the operator's.
4. **Wrong direction is caught by rules before agents.** Each decision recorded
   in an ADR should become a check wherever one can express it. An example is
   "every Argo CD Application pins its chart version and declares its prune
   policy". The `reviewer` covers what is left. The ADRs are the reference both
   use.

**Branch protection is a prerequisite for rules 2 and 3.** Without it, both
hold by convention only: a pull request that edits the CI workflow runs its own
edited version, and nothing but the operator's attention stops it merging. An
agent merge is safe only if GitHub, not the agent, enforces that the required
checks passed. Branch protection is not enabled today; why, and when it is
revisited, is in [CONTRIBUTING](../../CONTRIBUTING.md#branch-protection). This
ADR adds one more reason to revisit it: agent merging cannot start before it.

## Consequences

**Positive.**

- Quality is held by gates that run every time, not by attention that runs out.
- The operator reviews decisions (ADRs) and exceptions, not every diff.
- Escapes become checks, so the system improves from its own failures.

**Negative.**

- **Guardrails are code to maintain.** A wrong check blocks good work or passes
  bad work, and it must be reviewed like any other code.
- **Agent review costs tokens on every pull request:** about 70k–130k measured
  on the first two reviews. Moving rules into deterministic checks lowers this
  over time.
- **False positives slow work down.** A gate that flags too much is worked
  around, so a noisy check is fixed or removed, never silenced.
- **Until branch protection exists, nothing merges without the operator.**
  Throughput stays bounded by one person in that time.

## Risks, cost, and reversal

The main risk is **false confidence**: a green pipeline read as proof of
correctness when the gates do not cover what changed. Each gate therefore
states what it does not check, and the `reviewer` reports what it could not
verify.

**Accepted debt: rule 2 is fragile while the repository stays private.** The
operator chose on 2026-10-16 to keep it private, knowing that without branch
protection rule 2 holds by convention only. The debt is recorded with the
branch-protection exception in
[CONTRIBUTING](../../CONTRIBUTING.md#branch-protection).

No monetary cost beyond CI minutes, which are within GitHub's free allowance at
this repository's size.

Reversal: remove agent permissions to merge and return to operator review of
every pull request. The deterministic gates are worth keeping either way.

## Notes after acceptance

The text above is kept as accepted. These notes record what changed since,
without rewriting it.

- **2026-10-27 — branch protection is enabled.** The repository became public
  ([ADR-0017](0017-public-repository-from-a-snapshot.md)), which made it free,
  and a ruleset on `main` now requires a pull request and the six CI checks.
  That ends the accepted debt above for the workflow as a whole. It does not
  make rule 2 enforceable on its own: a pull request runs the workflow as it
  edits it, so a change to the gates can change what its required checks do.
  Such changes stay with the operator by convention, and agent merging still
  waits for rule 3's criteria. Details in
  [CONTRIBUTING](../../CONTRIBUTING.md#branch-protection).
