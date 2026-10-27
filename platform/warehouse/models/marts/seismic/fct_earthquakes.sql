-- Gold: one row per earthquake, for the globe and for aggregation.
-- Other event types (quarry blasts, explosions, ...) stay in silver: they are
-- not earthquakes, and counting them would inflate every figure downstream.
-- The one filter is event_type = 'earthquake'; the reconciliation test
-- reconcile_fct_vs_silver proves it drops nothing else.
--
-- Class bands are the usual USGS/Richter ones. Lower bounds are inclusive, so
-- a magnitude of exactly 2.0 is minor. There is no `else`: a null magnitude
-- gets a null class, which the not_null tests turn into a failure, instead of
-- being filed under "great".

select
    event_id,
    event_time,
    updated_at,
    magnitude,
    magnitude_type,
    case
        when magnitude < 2 then 'micro'
        when magnitude < 4 then 'minor'
        when magnitude < 5 then 'light'
        when magnitude < 6 then 'moderate'
        when magnitude < 7 then 'strong'
        when magnitude < 8 then 'major'
        when magnitude >= 8 then 'great'
    end as magnitude_class,
    place,
    region,
    latitude,
    longitude,
    depth_km,
    -- Kilometres. 300 is intermediate, as in the USGS bands (70-300).
    case
        when depth_km < 70 then 'shallow'
        when depth_km <= 300 then 'intermediate'
        when depth_km > 300 then 'deep'
    end as depth_class,
    status,
    is_reviewed,
    has_tsunami_flag,
    significance,
    felt_reports,
    alert_level,
    network,
    url,
    title
from {{ ref('stg_usgs__events') }}
where event_type = 'earthquake'
