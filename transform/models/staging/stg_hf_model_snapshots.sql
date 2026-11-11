-- One row per Hugging Face model per daily snapshot. downloads_30d is the Hub's rolling
-- 30-day count, so day-on-day growth is computed by comparing snapshots, not by summing.
select
    snapshot_date,
    model_id,
    author,
    model_name,
    downloads_30d,
    likes,
    trending_score,
    pipeline_tag,
    library_name,
    license,
    base_model,
    base_relation,
    arxiv_ids,
    rankings,
    created_at
from {{ silver('huggingface', 'model_snapshots') }}
