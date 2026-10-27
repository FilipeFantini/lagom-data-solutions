{#
  dbt's default builds "<target schema>_<custom schema>", so `+schema: silver`
  would create `public_silver`. The layers are named in ADR-0008 as exactly
  `silver` and `gold`, so the custom schema is used as is.

  A node with no custom schema would land in the target schema, which is
  nobody's layer. That is a mistake, so it stops the run instead.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ exceptions.raise_compiler_error(
            "Node '" ~ node.name ~ "' sets no schema. Set +schema in dbt_project.yml."
        ) }}
    {%- endif -%}
    {{- custom_schema_name | trim -}}
{%- endmacro %}
