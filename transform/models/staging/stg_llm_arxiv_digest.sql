-- Claude's plain-English summary of each arXiv paper, with its topics and new terms.
select
    arxiv_id,
    summary,
    contribution_type,
    technologies,
    new_terms,
    is_llm_related,
    model,
    task_version,
    observed_at as answered_at
from {{ silver('llm', 'arxiv_digest') }}
