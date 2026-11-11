{# A silver table: one Parquet file per table, e.g. silver/hackernews/stories.parquet. #}
{% macro silver(source_name, table) %}
  read_parquet('{{ var("silver_dir") }}/{{ source_name }}/{{ table }}.parquet')
{% endmacro %}
