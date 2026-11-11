# Extraction eval

How well do the rule-based aliases and Claude find the AI technologies in a Hacker News post?

## The labels

`eval/hn_labels.csv` holds 50 real stories with at least 20 points, drawn at random: 25 the
rules matched and 25 they did not, so both missed and spurious matches are tested.
Each row lists the technology_ids a careful reader would name from the same input the model
sees (title, link domain, text), with notes on judgement calls:

- A product does not imply its model family: "Claude Code" is `claude_code`, not `claude`.
- A model name implies its family: "Opus" is `claude`.
- Generic "AI" is not a technology; names outside the taxonomy (JEPA, Stable Audio) are not
  scored here and show up in `mart_emerging_terms` instead.
- A title that does not say what the post is about gets no label, even if the linked article
  might.

The labels were drafted by Claude Code while building phase 3 and should be reviewed by a
person; edit the CSV and rerun `make eval`.

## Results

`make eval` scores only stories both methods covered. Micro-averaged over (story, technology)
pairs.

| method | precision | recall | F1 | sample |
|---|---|---|---|---|
| rules | 0.97 | 0.91 | 0.94 | all 50 labelled stories |
| Claude | pending | pending | pending | after the first enrichment run |

The rules' misses on this sample are the expected ones: "Sponsored Agents" and "OpenAI
agents" are not caught by the `agents` aliases, "Opus" is not recognised as Claude, and
"Claude Code" also counts as `claude`.

50 stories is a small sample: one story changes F1 by about 0.03. Treat differences under
0.05 as noise.

## What Claude adds beyond the rules

Recall on known names is only part of it. Rules cannot tell sentiment, cannot say whether a
technology is the post's subject or a passing mention, and cannot notice names nobody has
added to the taxonomy. Those are what the LLM layer is for.
