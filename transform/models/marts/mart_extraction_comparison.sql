-- Rules against Claude, per technology, on the stories Claude has answered: how often both
-- found the technology, only the rules did, or only Claude did. A technology with many
-- rules-only hits has a loose alias; many Claude-only hits means a missing alias.
with answered as (
    select distinct doc_id as document_id
    from {{ ref('stg_llm_responses') }}
    where task = 'hn_technologies' and status = 'succeeded'
),

rules as (
    select r.document_id, r.technology_id
    from {{ ref('int_hn_story_technologies') }} as r
    join answered as a on cast(r.document_id as varchar) = a.document_id
),

llm as (
    select document_id, technology_id
    from {{ ref('int_hn_story_technologies_llm') }}
),

compared as (
    select
        coalesce(cast(rules.document_id as varchar), llm.document_id) as document_id,
        coalesce(rules.technology_id, llm.technology_id) as technology_id,
        rules.document_id is not null as by_rules,
        llm.document_id is not null as by_llm
    from rules
    full outer join llm
      on cast(rules.document_id as varchar) = llm.document_id
     and rules.technology_id = llm.technology_id
)

select
    c.technology_id,
    d.name,
    count(*) filter (where by_rules and by_llm) as found_by_both,
    count(*) filter (where by_rules and not by_llm) as rules_only,
    count(*) filter (where by_llm and not by_rules) as llm_only,
    round(
        count(*) filter (where by_rules and by_llm) / count(*), 3
    ) as agreement
from compared as c
join {{ ref('dim_technology') }} as d using (technology_id)
group by all
