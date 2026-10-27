{#
  Fails for every row whose value lies outside [min_value, max_value].
  A null value is not returned: pair this with not_null where null matters.
#}
{% test value_between(model, column_name, min_value, max_value) %}

select {{ column_name }} as out_of_range_value
from {{ model }}
where {{ column_name }} < {{ min_value }}
    or {{ column_name }} > {{ max_value }}

{% endtest %}
