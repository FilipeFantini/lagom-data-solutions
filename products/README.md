# products/

One directory per thing a consumer sees. Products change often and affect one
audience each.

Planned:

| Product | Form | Born in |
|---|---|---|
| curated reports | Evidence site, built in CI | M4 |
| the globe | Streamlit with pydeck | M6 |

A product reads from the gold layer in Postgres, and from the lakehouse once it
exists ([ADR-0008](../docs/adr/0008-postgres-for-all-layers.md)). It never
reaches into a service's internals.

This directory is deliberately agnostic about form: a report, an app, a notebook,
or a BI project are all products. Whatever lands here must be reviewable as
text — see [ADR-0006](../docs/adr/0006-monorepo-layout.md) and
[`../.gitattributes`](../.gitattributes).
