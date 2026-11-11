{#
  Rule-based technology mentions: one row per (id, technology_id) whose text contains any
  alias of the technology as a whole word. The baseline the LLM extraction is measured against.

  A match must start at a word boundary but may be followed by digits, so "Qwen3" and
  "GPT5" count while "llamas" does not. Aliases flagged case_sensitive (RAG, MoE, LoRA) must
  match exactly, because lowercase they are ordinary words or other things.

  Two steps, because a regex per (document, alias) pair took over ten minutes on 130k
  documents: a plain substring join finds candidates, and the regex runs only on those.
#}
{% macro technology_mentions(relation, id_column, text_expression, hf_only=false) %}
with documents as (
    select {{ id_column }} as document_id, {{ text_expression }} as body
    from {{ relation }}
),

documents_cased as (
    select document_id, body, lower(body) as lower_body
    from documents
),

aliases as (
    select
        a.technology_id,
        a.case_sensitive,
        case when a.case_sensitive then a.alias else lower(a.alias) end as needle,
        case
            when a.case_sensitive
                then '(^|[^A-Za-z0-9])' || regexp_escape(a.alias) || '([^A-Za-z]|$)'
            else '(^|[^a-z0-9])' || regexp_escape(lower(a.alias)) || '([^a-z]|$)'
        end as pattern
    from {{ ref('technology_aliases') }} as a
    {% if hf_only %}
    join {{ ref('technologies') }} as t using (technology_id)
    where t.match_hf
    {% endif %}
),

candidates as materialized (
    select
        d.document_id,
        a.technology_id,
        a.pattern,
        case when a.case_sensitive then d.body else d.lower_body end as haystack
    from documents_cased as d
    join aliases as a
      on contains(case when a.case_sensitive then d.body else d.lower_body end, a.needle)
)

select distinct document_id, technology_id
from candidates
where regexp_matches(haystack, pattern)
{% endmacro %}
