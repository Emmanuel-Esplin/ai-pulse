-- Top-level comments from front-page snapshots; position 1 is the highest-ranked.
select
    comment_id,
    story_id,
    position,
    author,
    text,
    created_at,
    observed_at
from {{ silver('hackernews', 'comments') }}
