-- The shared key of AI Pulse: every source's mentions resolve to one technology_id here.
select
    t.technology_id,
    t.name,
    t.category,
    t.match_hf,
    list(a.alias order by a.alias) as aliases
from {{ ref('technologies') }} as t
join {{ ref('technology_aliases') }} as a using (technology_id)
group by all
