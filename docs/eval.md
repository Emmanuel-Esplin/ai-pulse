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

| method | prompt | precision | recall | F1 | sample |
|---|---|---|---|---|---|
| rules | | 0.97 | 0.91 | 0.94 | all 50 labelled stories |
| Qwen3 32B (Bedrock) | v1 | 0.84 | 0.84 | 0.84 | 50 |
| gpt-oss-120b (Bedrock) | v1 | n/a | | | 24 of 50 answers missed the schema |
| Qwen3 32B (Bedrock) | v2 | 0.94 | 0.94 | 0.94 | 50 |
| gpt-oss-120b (Bedrock) | v2 | 1.00 | 1.00 | 1.00 | 49 (after two retries) |
| Claude | v2 | pending | | | needs an API key |

Pilot run 2026-11-12 on AWS credits (Claude is not offered to FREE-plan AWS accounts).
Total pilot spend: $0.10 for 200 responses, per `mart_llm_usage`.

Prompt v1 let models infer: OpenAI news got `gpt`, Anthropic news got `claude`. v2 adds
explicit rules (a lab does not imply its models, a product does not imply its family, a model
name does), which fixed most of it. gpt-oss-120b ignores the forced tool call on about one
answer in four; those are rejected by the schema check and asked again on the next run.

On 10 arXiv papers, gpt-oss-120b's digests were accurate; Qwen3 32B tagged technologies the
papers are not about (DSPy and diffusion models on a medical segmentation paper). For a full
run, gpt-oss-120b is the pick for both tasks.

The rules' misses on this sample are the expected ones: "Sponsored Agents" and "OpenAI
agents" are not caught by the `agents` aliases, "Opus" is not recognised as Claude, and
"Claude Code" also counts as `claude`.

50 stories is a small sample: one story changes F1 by about 0.03. Treat differences under
0.05 as noise.

## What Claude adds beyond the rules

Recall on known names is only part of it. Rules cannot tell sentiment, cannot say whether a
technology is the post's subject or a passing mention, and cannot notice names nobody has
added to the taxonomy. Those are what the LLM layer is for.
