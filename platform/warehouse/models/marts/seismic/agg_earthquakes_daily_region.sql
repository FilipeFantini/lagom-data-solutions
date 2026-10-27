-- Gold: earthquakes per UTC day and region.
-- The day is cut in UTC explicitly: casting a timestamptz to date would use the
-- session time zone and move events near midnight to another day.
-- Built from fct_earthquakes, so it shares its definition of an earthquake; the
-- reconciliation test reconcile_agg_vs_fct proves the counts add up.
-- A day that is still open is a partial window: re-running dbt recomputes it
-- from silver, so late revisions correct it.

select
    (event_time at time zone 'UTC')::date as event_date,
    region,
    count(*) as event_count,
    max(magnitude) as max_magnitude,
    round(avg(magnitude)::numeric, 2)::numeric(4, 2) as avg_magnitude,
    count(*) filter (where magnitude >= 4) as count_magnitude_4_plus,
    max(event_time) as last_event_time
from {{ ref('fct_earthquakes') }}
group by 1, 2
