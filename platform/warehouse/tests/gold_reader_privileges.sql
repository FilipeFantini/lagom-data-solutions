-- gold_reader may read gold and nothing else, and may write nowhere
-- (architecture.md section 10). Returns a row, and so fails, for each relation
-- in a layer schema where that is not so, and for a gold schema it cannot use.
-- The privileges are granted by dbt_project.yml; this checks the outcome in the
-- database, not the config.
--
-- The refs make dbt build both gold models before this test runs: with no
-- parent a singular test could run first, before any grant exists.
-- depends_on: {{ ref('fct_earthquakes') }}
-- depends_on: {{ ref('agg_earthquakes_daily_region') }}

with relations as (
    select
        table_schema,
        table_name,
        has_table_privilege(
            'gold_reader', format('%I.%I', table_schema, table_name), 'SELECT'
        ) as can_read,
        has_table_privilege(
            'gold_reader',
            format('%I.%I', table_schema, table_name),
            'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
        ) as can_write
    from information_schema.tables
    where table_schema in ('bronze', 'silver', 'gold')
)

select
    table_schema,
    table_name,
    can_read,
    can_write
from relations
where can_write or can_read <> (table_schema = 'gold')

union all

select
    'gold' as table_schema,
    null as table_name,
    false as can_read,
    false as can_write
where not has_schema_privilege('gold_reader', 'gold', 'USAGE')
