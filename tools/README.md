# tools/

Development and operational scripts: the resource-budget check, local
environment helpers, one-off maintenance commands.

A script here is held to the same standard as the rest of the repository — it is
read and run by someone who did not write it. That means arguments over edited
constants, a clear failure when a precondition is missing, and no destructive
action without an explicit flag.

| Script | What it does | Run |
|---|---|---|
| [`resource_budget.py`](resource_budget.py) | Renders every Argo CD Application and fails on missing resources or a total over the ceiling — [architecture.md §11](../docs/architecture.md#11-resource-budget) | `uv run --project tools python tools/resource_budget.py` |
| [`promotion_check.py`](promotion_check.py) | Fails if prod pins an image without a digest, or a digest staging had not pinned on `main` first — [ADR-0015](../docs/adr/0015-images-on-ghcr.md) | `uv run --project tools python tools/promotion_check.py --base origin/main` |

`tools/` is a small `uv` project: `pyproject.toml` declares dependencies and the
ruff, mypy, and pytest settings, and `uv.lock` pins them. CI runs
`ruff format --check`, `ruff check`, `mypy --strict`, and `pytest` on it.
