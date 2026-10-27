-- Silver keeps exactly one row per event, so its row count must equal the
-- number of distinct ids in bronze. Returns a row, and so fails, if not.
-- Bronze is read live: a load that lands between the silver build and this
-- test shows up as a mismatch; re-run the build.

with silver as (
    select count(*) as row_count from {{ ref('stg_usgs__events') }}
),

bronze as (
    select count(distinct id) as distinct_ids from {{ source('usgs', 'events') }}
)

select
    silver.row_count as silver_rows,
    bronze.distinct_ids as bronze_distinct_ids
from silver
cross join bronze
where silver.row_count <> bronze.distinct_ids
