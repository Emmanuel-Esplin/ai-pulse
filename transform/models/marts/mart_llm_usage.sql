-- What enrichment has cost, per day, task and model, from the token counts the API returned.
-- billed_fraction is 0.5 for Claude through the Message Batches API, 1.0 for Bedrock on demand.
select
    r.answered_date,
    r.task,
    r.model,
    count(*) as responses,
    count(*) filter (where r.status = 'succeeded') as succeeded,
    count(*) filter (where r.status <> 'succeeded') as failed,
    sum(r.input_tokens) as input_tokens,
    sum(r.output_tokens) as output_tokens,
    sum(r.cache_read_tokens) as cache_read_tokens,
    sum(r.cache_write_tokens) as cache_write_tokens,
    round(sum(p.billed_fraction * (
        r.input_tokens * p.input_usd_per_mtok
        + r.output_tokens * p.output_usd_per_mtok
        + r.cache_read_tokens * p.cache_read_usd_per_mtok
        + r.cache_write_tokens * p.cache_write_usd_per_mtok
    )) / 1e6, 4) as cost_usd
from {{ ref('stg_llm_responses') }} as r
left join {{ ref('llm_prices') }} as p using (model)
group by all
