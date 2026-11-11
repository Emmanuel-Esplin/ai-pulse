-- Technologies named in each Hacker News story's title or text (rule-based baseline).
{{ technology_mentions(ref('stg_hn_stories'), 'story_id',
     "title || ' ' || coalesce(story_text, '')") }}
