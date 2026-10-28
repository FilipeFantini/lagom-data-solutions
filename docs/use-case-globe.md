# Use case — the globe

> **Status (2026-10-28):** not on the roadmap. The platform became a portfolio
> of data architectures ([ADR-0022](adr/0022-platform-as-a-portfolio-of-architectures.md)), and the globe left the
> milestones. The sources below remain candidates for the streaming showcase
> (M6). The rest is kept as the original idea.

The first solution built on the platform, not the project itself. The platform
is the deliverable; the globe is what proves it works.

## The concept

An interactive globe in the style of a control-room display, where each data
layer is a different source — weather, public transport, seismic activity,
flights — all geolocated in the same view.

The intent is the impression of a living world based on real data: navigate the
globe and see, for the same region, the weather, the state of public transport,
and seismic activity.

## Why it serves the platform

Each source has its own ingestion pipeline — some batch, some streaming — but
all converge on the same geographic model and the same dbt project underneath. A
new source is another pipeline reusing the backbone: orchestration,
transformation, GitOps delivery.

Streaming becomes **one of the pieces**, not the whole project. The globe
demonstrates growth by composition concretely.

## Candidate sources

The nature of the source determines the ingestion tool: batch goes through dlt,
continuous events through Redpanda Connect. See
[ADR-0003](adr/0003-ingestion-split-dlt-benthos.md).

### Chosen for M2

**USGS** — earthquakes, public GeoJSON, no authentication, stable schema, small
volume. The right first source because there is no auth to debug and the focus
stays on the conveyor rather than the source.

### Strong for later layers

| Source | Nature | Note |
|---|---|---|
| Weather (open APIs) | batch / near-real-time | minute-scale; works well as enrichment |
| SPTrans Olho Vivo (São Paulo buses) | **real streaming** | live vehicle position, rich data |
| Carris / GTFS Realtime Lisbon | **real streaming** | vehicle position second by second |
| OpenSky Network (flights) | **real streaming** | highly visual |
| INPE (wildfires) | batch | environmental angle, rarely done |
| Air quality | batch | completes the smart-city angle |

### Considered and rejected

**Formula 1.** Has a live telemetry API and the FastF1 library with rich history
— lap times, positions, pit stops, car telemetry. Would yield both batch and
streaming with rewarding visuals. **Rejected on saturation:** portfolio projects
built on F1 data are common, so it does not differentiate.

**Strava.** Official API, but designed around one's own data. Good for batch and
personal analysis, but **not genuine streaming** — nobody generates activity
second by second. It would be a batch analytics project, not a platform.

**Live sport (football, scores).** Genuine streaming and good visuals, but less
personal and less connected to the other interests.

**Brazilian Chamber of Deputies open data.** Votes, expenses, bills. Excellent
quality and a real story to tell, but batch. A good candidate for a second
solution on the same platform, not for the globe.

**Crypto / B3 market data.** Live tick-by-tick, pure streaming, but a
heavily explored subject.

**Wikipedia edit stream.** A classic for practising streaming, but not
geolocated.

## Starting plan

Two or three sources, not all at once: one batch (USGS) and one streaming. That
validates the architecture end to end without drowning the project in sources
before the conveyor runs.

## Implementation

Streamlit with **pydeck** — deck.gl bindings, so the globe is written in Python
rather than JavaScript. That also serves the operator's goal of gaining Python
proficiency.

Alternative considered: a static web app with deck.gl or globe.gl reading GeoJSON
from object storage. Lighter — zero resident RAM — but requires JavaScript and
loses interactive filtering against the database.
