"""Enrich silver with an LLM: `python -m enrich.run {hn,arxiv} [--provider P] [--limit N] [--yes]`.

Without --yes this is a dry run: it prints how many items are new and what they would cost,
and sends nothing. With --yes it submits batches and records them as pending in bronze.
`python -m enrich.run collect [--wait]` writes finished batches to bronze; every run does
that first, so a batch submitted yesterday is picked up today.

Providers: `anthropic` (Claude API, Message Batches, half price; the default) and `bedrock`
(Amazon Bedrock on demand; answers arrive as the run goes, so --wait is not needed).
"""

from __future__ import annotations

import argparse
import logging
import os

from enrich import llm, tasks

DEFAULT_MODELS = {"anthropic": llm.DEFAULT_MODEL, "bedrock": "qwen.qwen3-32b-v1:0"}


def make_client(provider: str, model: str) -> llm.LLMClient:
    if provider == "bedrock":
        from enrich.bedrock import BedrockConverseClient

        return BedrockConverseClient(model, region=os.environ.get("AWS_REGION", "eu-west-1"))
    return llm.AnthropicBatchClient(model)


def _hn(args: argparse.Namespace) -> list[llm.Item]:
    if args.eval_set:
        # The labelled stories, whatever their points, so `make eval` can score the model.
        from enrich.evaluate import load_labels

        return tasks.hn_items(min_points=0, story_ids=set(load_labels()))
    return tasks.hn_items(args.min_points)


ITEM_BUILDERS = {
    "hn": ("hn_technologies", _hn),
    "arxiv": ("arxiv_digest", lambda a: tasks.arxiv_items()),
}


def main(argv: list[str] | None = None, client: llm.LLMClient | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=[*ITEM_BUILDERS, "collect"])
    parser.add_argument("--limit", type=int, default=500, help="most items to send this run")
    parser.add_argument("--min-points", type=int, default=20, help="HN stories at or above")
    parser.add_argument("--eval-set", action="store_true", help="HN: only the labelled stories")
    parser.add_argument(
        "--provider",
        choices=sorted(DEFAULT_MODELS),
        default=os.environ.get("AIPULSE_LLM_PROVIDER", "anthropic"),
    )
    parser.add_argument("--model", default=os.environ.get("AIPULSE_LLM_MODEL"))
    parser.add_argument("--yes", action="store_true", help="submit (this is billed)")
    parser.add_argument("--wait", action="store_true", help="poll until batches finish")
    args = parser.parse_args(argv)
    args.model = client.model if client else (args.model or DEFAULT_MODELS[args.provider])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    all_tasks = tasks.tasks()
    if args.target == "collect":
        client = client or make_client(args.provider, args.model)
        (llm.wait if args.wait else llm.collect)(client, all_tasks)
        return

    task_name, build = ITEM_BUILDERS[args.target]
    task = all_tasks[task_name]
    candidates = build(args)
    new = llm.to_send(task, candidates, args.model)
    batch = new[: args.limit]
    estimate = llm.estimate_cost(task, batch, args.model)
    print(
        f"{task.name} {task.version} on {args.model}: {len(candidates)} items, "
        f"{len(new)} not yet answered, sending {len(batch)}.\n"
        f"Estimated: {estimate['input_tokens']:,} input + {estimate['cached_tokens']:,} cached "
        f"+ {estimate['output_tokens']:,} output tokens = about ${estimate['usd']:.2f} "
        f"({args.provider} prices)."
    )
    if not args.yes:
        print("Dry run: nothing sent. Add --yes to submit.")
        return
    if not batch:
        return
    client = client or make_client(args.provider, args.model)
    llm.collect(client, all_tasks)
    llm.submit(client, task, batch)
    if args.wait:
        llm.wait(client, all_tasks)


if __name__ == "__main__":
    main()
