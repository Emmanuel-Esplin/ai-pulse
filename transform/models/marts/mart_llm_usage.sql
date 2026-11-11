-- What enrichment has cost, per day, task and model, from the token counts the API returned.
-- Batch requests are billed at half the standard price; cache writes at 1.25x input.
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
    round(0.5 * sum(
        r.input_tokens * p.input_usd_per_mtok
        + r.output_tokens * p.output_usd_per_mtok
        + r.cache_read_tokens * p.cache_read_usd_per_mtok
        + r.cache_write_tokens * p.cache_write_usd_per_mtok
    ) / 1e6, 4) as cost_usd
from {{ ref('stg_llm_responses') }} as r
left join {{ ref('llm_prices') }} as p using (model)
group by all
