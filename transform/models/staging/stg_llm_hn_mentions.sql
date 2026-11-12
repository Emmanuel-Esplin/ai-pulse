-- Technologies Claude found in each Hacker News story, with the sentiment towards each.
-- technology_id 'other' marks AI technologies outside the seed taxonomy.
select
    story_id,
    technology_id,
    name,
    sentiment,
    is_main_subject,
    model,
    task_version,
    observed_at as answered_at
from {{ silver('llm', 'hn_mentions') }}
