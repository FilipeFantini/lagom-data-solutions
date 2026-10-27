-- Grouping moves no event in or out, so the daily counts must add up to the
-- fact table. Returns a row, and so fails, if not. coalesce turns the sum of
-- an empty table (null) into 0, to compare with a count of 0.

with agg as (
    select coalesce(sum(event_count), 0) as counted_events
    from {{ ref('agg_earthquakes_daily_region') }}
),

fct as (
    select count(*) as fct_rows from {{ ref('fct_earthquakes') }}
)

select
    agg.counted_events as agg_events,
    fct.fct_rows
from agg
cross join fct
where agg.counted_events <> fct.fct_rows
