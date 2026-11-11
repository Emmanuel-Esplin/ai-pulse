-- How often each technology appears in each source over all loaded data: a first
-- cross-source view, and a quick check that the alias rules are neither too loose nor too tight.
with hn as (
    select technology_id, count(*) as hn_stories
    from {{ ref('int_hn_story_technologies') }}
    group by technology_id
),

arxiv as (
    select technology_id, count(*) as arxiv_papers
    from {{ ref('int_arxiv_paper_technologies') }}
    group by technology_id
),

hf as (
    select m.technology_id, count(*) as hf_models, sum(s.downloads_30d) as hf_downloads_30d
    from {{ ref('int_hf_model_technologies') }} as m
    join {{ ref('stg_hf_model_snapshots') }} as s on s.model_id = m.document_id
    where s.snapshot_date = (select max(snapshot_date) from {{ ref('stg_hf_model_snapshots') }})
    group by m.technology_id
)

select
    d.technology_id,
    d.name,
    d.category,
    coalesce(hn.hn_stories, 0) as hn_stories,
    coalesce(arxiv.arxiv_papers, 0) as arxiv_papers,
    coalesce(hf.hf_models, 0) as hf_models,
    coalesce(hf.hf_downloads_30d, 0) as hf_downloads_30d
from {{ ref('dim_technology') }} as d
left join hn using (technology_id)
left join arxiv using (technology_id)
left join hf using (technology_id)
