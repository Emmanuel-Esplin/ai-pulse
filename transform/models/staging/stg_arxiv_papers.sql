-- One row per arXiv paper (latest version seen). submitted_date is the v1 submission day,
-- which is how bronze is partitioned and how paper trends are dated.
select
    arxiv_id,
    version,
    title,
    abstract,
    authors,
    len(authors) as author_count,
    primary_category,
    categories,
    primary_category in ('cs.AI', 'cs.LG', 'cs.CL', 'cs.CV', 'stat.ML') as is_ai_primary,
    comment,
    published_at,
    cast(published_at as date) as submitted_date,
    updated_at
from {{ silver('arxiv', 'papers') }}
