-- Every Claude response, successful or not, with token usage: the basis for cost tracking
-- and for knowing which documents have been enriched.
select
    task,
    task_version,
    doc_id,
    key,
    status,
    model,
    input_tokens,
    output_tokens,
    cache_read_tokens,
    cache_write_tokens,
    error,
    observed_at as answered_at,
    cast(observed_at as date) as answered_date
from {{ silver('llm', 'responses') }}
