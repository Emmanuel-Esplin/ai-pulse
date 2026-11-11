-- The arXiv papers each model cites in its Hub tags: a direct link between two sources.
select distinct
    model_id,
    unnest(arxiv_ids) as arxiv_id
from {{ ref('stg_hf_model_snapshots') }}
