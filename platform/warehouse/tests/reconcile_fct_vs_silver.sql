-- The fact table is silver filtered to earthquakes and nothing else, so the
-- counts must match. Returns a row, and so fails, if not.

with silver as (
    select count(*) as earthquake_rows
    from {{ ref('stg_usgs__events') }}
    where event_type = 'earthquake'
),

fct as (
    select count(*) as fct_rows from {{ ref('fct_earthquakes') }}
)

select
    silver.earthquake_rows as silver_earthquake_rows,
    fct.fct_rows
from silver
cross join fct
where silver.earthquake_rows <> fct.fct_rows
