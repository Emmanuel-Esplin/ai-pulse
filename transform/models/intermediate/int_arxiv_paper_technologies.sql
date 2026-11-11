-- Technologies named in each arXiv paper's title or abstract (rule-based baseline).
{{ technology_mentions(ref('stg_arxiv_papers'), 'arxiv_id', "title || ' ' || abstract") }}
