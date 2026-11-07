# ADR-0034 — Notion is the one documentation space outside the repository

- **Status:** Proposed
- **Date:** 2026-11-07
- **Amends:** in [ADR-0001](0001-use-adrs.md), *Decision*: the Obsidian vault
  no longer has a role in the project's documentation.

## Context and problem

Work is now led by a team of agents in Tucano rather than by sessions the
operator orchestrates by hand. They need a shared place for what the repository
does not hold: work in progress, briefs, decisions waiting on the operator, and
drafts of the site planned for M4.

Today that role is split. The operator's Obsidian vault holds an index of the
project that has drifted (it still reads "M0"), and only the operator can edit
it. Two places outside the repository would drift from each other as well as
from the code.

## Requirements and constraints

- The repository stays the source of truth. Nothing outside it may settle a
  question the repository answers.
- One space, reachable by every agent and by the operator.
- It must render Mermaid, since the repository's diagrams are Mermaid.
- Its content will be reused for the public site, so it must serve as a draft
  for presentation as well as a working record.
- The repository is public: it must not reveal anything that identifies the
  operator or the infrastructure.

## Alternatives considered

**Keep the Obsidian vault.** Comfortable and already in use, but it lives on
the operator's machine. An agent can reach it only through the desktop app's
interface, one at a time, and it has no way to share a page with anyone else.

**Tucano's built-in wiki.** Visible to every agent, but agents only read it and
an automatic curator writes it; nobody shapes its pages. It is not a draft that
can turn into a site.

**The repository alone.** It already holds every fact, but briefs and status
change several times a day; putting them through pull requests would bury the
review of real changes, and site drafts are edited for an audience, not for the
code.

## Decision

1. **Notion is the one documentation space outside the repository.** It holds
   only what the repository does not: current status, briefs, decisions
   pending with the operator, and site drafts.
2. **It links to facts; it does not restate them.** A Notion page that needs an
   architecture fact links to the file in the repository. Where a Notion page
   and the repository disagree, the repository wins and the page is fixed.
3. **Diagrams of record stay in the repository.** Notion renders Mermaid in a
   code block set to preview, which is used for site drafts. Each draft links
   to its source document and is checked against it before it is published.
4. **Links go from Notion to the repository, never back.** A Notion URL can
   carry a workspace name; the public repository does not cite one.
5. **The Obsidian vault is the operator's personal notebook**, outside the
   project's documentation. Agents neither read it for project facts nor
   update it.

## Consequences

**Positive.** One place to look for work in progress, open to the whole team.
Site content starts as a draft next to the work it describes, instead of being
written from scratch for M4.

**Negative.** A second tool to keep honest: a Notion page that restates a fact
will drift. Rule 2 is the guard, and it depends on review rather than on a
check.

## Risks, cost, and reversal

It uses the operator's existing Notion workspace; no new service is added. The risk is drift, kept
low by holding only transient content there. Reversible by moving the pages
back to the repository or elsewhere; nothing in the repository depends on
Notion.
