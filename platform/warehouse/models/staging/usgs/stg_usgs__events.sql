-- Silver: one row per USGS event, the latest revision of it, typed and renamed.
-- All event types are kept; gold decides which ones it serves.
--
-- Bronze keeps every revision (merge key id + updated), so the current state
-- of an event is the revision with the largest `updated`. (id, updated) is
-- unique in bronze, so the ranking has no ties.
--
-- The columns are listed instead of `select *`: if bronze loses or retypes one
-- of them, this model fails to build and names it (protocol 16.3).
--
-- Epoch milliseconds become timestamptz through to_timestamp, which reads its
-- argument as seconds since 1970-01-01 UTC, so no timestamp is ever naive.

with revisions as (

    select
        id,
        properties__type,
        properties__mag,
        properties__mag_type,
        properties__place,
        properties__time,
        properties__updated,
        geometry__coordinates,
        properties__status,
        properties__tsunami,
        properties__sig,
        properties__felt,
        properties__alert,
        properties__net,
        properties__url,
        properties__title,
        row_number() over (
            partition by id
            order by properties__updated desc
        ) as revision_rank
    from {{ source('usgs', 'events') }}

),

latest as (

    select * from revisions
    where revision_rank = 1

)

select
    id::text as event_id,
    properties__type::text as event_type,
    properties__mag::double precision as magnitude,
    properties__mag_type::text as magnitude_type,
    properties__place::text as place,
    -- Text after the last comma, trimmed: "12 km SSW of Town, Alaska" is
    -- "Alaska". With no comma the pattern matches nothing and the whole place
    -- remains ("Fiji region").
    nullif(btrim(regexp_replace(properties__place, '^.*,', '')), '')::text as region,
    to_timestamp(properties__time / 1000.0) as event_time,
    to_timestamp(properties__updated / 1000.0) as updated_at,
    -- GeoJSON order is [longitude, latitude, depth in km].
    (geometry__coordinates ->> 0)::double precision as longitude,
    (geometry__coordinates ->> 1)::double precision as latitude,
    (geometry__coordinates ->> 2)::double precision as depth_km,
    properties__status::text as status,
    properties__status = 'reviewed' as is_reviewed,
    properties__tsunami = 1 as has_tsunami_flag,
    properties__sig as significance,
    properties__felt as felt_reports,
    properties__alert::text as alert_level,
    properties__net::text as network,
    properties__url::text as url,
    properties__title::text as title
from latest
