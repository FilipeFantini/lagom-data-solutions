# ADR-0001 — Record architecture decisions in ADRs

- **Status:** Accepted
- **Date:** 2026-10-12

## Context and problem

This platform is built incrementally, partly as a learning vehicle, and will be
worked on by more than one developer. Most of its design choices are trade-offs
rather than obvious answers: a cheaper tool against a better-known one, a
deferred piece against an immediate one.

Without a record, those trade-offs are lost. The cost is concrete: a second
developer cannot tell whether a choice was deliberate or accidental, and will
either reopen settled discussions or undo a decision without knowing what it was
protecting.

## Requirements and constraints

- A decision must be findable from the code it affects.
- The record must survive the conversation that produced it.
- Writing one must be cheap enough that it actually happens.
- The repository is the source of truth; a personal notes vault is not.

## Alternatives considered

**Document decisions in commit messages.** Cheap, but not discoverable: nobody
reads history looking for rationale, and a decision spanning several commits has
no single home.

**Keep decisions in the personal Obsidian vault.** Already in use and
comfortable, but the second developer has no access to it, and it drifts from
the code it describes.

**One long architecture document.** Readable as an overview, but it records the
current state rather than the reasoning, and editing it erases the history of
why it changed.

## Decision

Record each significant decision as a numbered ADR in this directory, with a
fixed set of headings, and index it in [`README.md`](README.md).

Reverse a decision with a new ADR that supersedes the old one. Never edit a past
ADR to match present reality; mark it superseded and link forward.

The repository is the source of truth. The operator's Obsidian vault remains as
learning notes and an index, with no authority over these records.

## Consequences

**Positive.** Rationale lives next to the code and is versioned with it. A
reader can see not just what was chosen but what was rejected. Onboarding
becomes reading a short list of decisions rather than reconstructing them.

**Negative.** Adds a step to meaningful changes, and the index needs
maintenance. ADRs that are written and never maintained are worse than none, so
updating them is a blocking checklist item in [`../../CLAUDE.md`](../../CLAUDE.md)
§5, not a courtesy.

## Risks, cost, and reversal

Low risk; the cost is minutes per decision. Reversible at any time by stopping —
existing ADRs stay valuable as a historical record even if the practice is
abandoned.
