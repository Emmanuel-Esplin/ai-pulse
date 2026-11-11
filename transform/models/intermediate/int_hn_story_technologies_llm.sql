-- Claude's mentions on the seed taxonomy, in the same shape as the rule-based model, so the
-- two can be compared and later combined. 'other' names go to mart_emerging_terms instead.
select
    cast(story_id as varchar) as document_id,
    technology_id,
    sentiment,
    is_main_subject
from {{ ref('stg_llm_hn_mentions') }}
where technology_id <> 'other'
