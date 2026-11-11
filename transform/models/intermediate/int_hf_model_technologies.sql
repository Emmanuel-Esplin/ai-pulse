-- The model family of each Hugging Face model, matched on its id and its base model's id,
-- so a community quantization like "someone/Qwen3-4B-GGUF" counts towards Qwen.
-- Only technologies marked match_hf take part: concepts like RAG are not model names.
{{ technology_mentions(
     '(select distinct model_id, base_model from ' ~ ref('stg_hf_model_snapshots') ~ ')',
     'model_id', "model_id || ' ' || coalesce(base_model, '')", hf_only=true) }}
