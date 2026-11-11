-- Daily Hacker News activity: the volume baseline every technology trend is compared with.
select
    created_date,
    count(*) as stories,
    sum(points) as points,
    sum(num_comments) as comments,
    sum(case when points >= 100 then 1 else 0 end) as stories_100_plus,
    sum(case when story_kind = 'show' then 1 else 0 end) as show_hn,
    sum(case when story_kind = 'ask' then 1 else 0 end) as ask_hn
from {{ ref('stg_hn_stories') }}
group by created_date
