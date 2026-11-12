-- AI names Claude found that the seed taxonomy does not cover yet: 'other' mentions on
-- Hacker News and new terms in arXiv papers. Frequent ones are candidates for the seed.
with hn as (
    select lower(trim(m.name)) as term, m.name, s.created_date as seen_date, 'hackernews' as source
    from {{ ref('stg_llm_hn_mentions') }} as m
    join {{ ref('stg_hn_stories') }} as s using (story_id)
    where m.technology_id = 'other'
),

arxiv as (
    select lower(trim(t.term)) as term, t.term as name, p.submitted_date as seen_date,
           'arxiv' as source
    from (
        select arxiv_id, unnest(new_terms) as term from {{ ref('stg_llm_arxiv_digest') }}
    ) as t
    join {{ ref('stg_arxiv_papers') }} as p using (arxiv_id)
),

seen as (
    select * from hn
    union all
    select * from arxiv
)

select
    term,
    min(name) as example_name,
    count(*) as mentions,
    count(*) filter (where source = 'hackernews') as hn_mentions,
    count(*) filter (where source = 'arxiv') as arxiv_mentions,
    min(seen_date) as first_seen,
    max(seen_date) as last_seen
from seen
group by term
