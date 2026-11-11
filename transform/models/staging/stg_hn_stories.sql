-- One row per Hacker News story with its latest known points and comment count.
-- Ask HN / Show HN / Launch HN are labelled from the title prefix, the site's own convention.
select
    story_id,
    title,
    url,
    domain,
    author,
    coalesce(points, 0) as points,
    coalesce(num_comments, 0) as num_comments,
    story_text,
    created_at,
    cast(created_at as date) as created_date,
    case
        when title like 'Ask HN:%' then 'ask'
        when title like 'Show HN:%' then 'show'
        when title like 'Launch HN:%' then 'launch'
        else 'link'
    end as story_kind,
    observed_at,
    observed_via
from {{ silver('hackernews', 'stories') }}
