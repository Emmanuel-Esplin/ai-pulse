"""Enrich silver with Claude: `python -m enrich.run {hn,arxiv} [--limit N] [--yes] [--wait]`.

Without --yes this is a dry run: it prints how many items are new and what they would cost,
and sends nothing. With --yes it submits batches and records them as pending in bronze.
`python -m enrich.run collect [--wait]` writes finished batches to bronze; every run does
that first, so a batch submitted yesterday is picked up today.
"""

from __future__ import annotations

import argparse
import logging
import os

from enrich import llm, tasks

ITEM_BUILDERS = {
    "hn": ("hn_technologies", lambda a: tasks.hn_items(a.min_points)),
    "arxiv": ("arxiv_digest", lambda a: tasks.arxiv_items()),
}


def main(argv: list[str] | None = None, client: llm.LLMClient | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=[*ITEM_BUILDERS, "collect"])
    parser.add_argument("--limit", type=int, default=500, help="most items to send this run")
    parser.add_argument("--min-points", type=int, default=20, help="HN stories at or above")
    parser.add_argument("--model", default=os.environ.get("AIPULSE_LLM_MODEL", llm.DEFAULT_MODEL))
    parser.add_argument("--yes", action="store_true", help="submit (this is billed)")
    parser.add_argument("--wait", action="store_true", help="poll until batches finish")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    all_tasks = tasks.tasks()
    if args.target == "collect":
        client = client or llm.AnthropicBatchClient(args.model)
        (llm.wait if args.wait else llm.collect)(client, all_tasks)
        return

    task_name, build = ITEM_BUILDERS[args.target]
    task = all_tasks[task_name]
    candidates = build(args)
    new = llm.to_send(task, candidates)
    batch = new[: args.limit]
    estimate = llm.estimate_cost(task, batch, args.model)
    print(
        f"{task.name} {task.version} on {args.model}: {len(candidates)} items, "
        f"{len(new)} not yet answered, sending {len(batch)}.\n"
        f"Estimated: {estimate['input_tokens']:,} input + {estimate['cached_tokens']:,} cached "
        f"+ {estimate['output_tokens']:,} output tokens = about ${estimate['usd']:.2f} "
        f"(batch prices)."
    )
    if not args.yes:
        print("Dry run: nothing sent. Add --yes to submit.")
        return
    if not batch:
        return
    client = client or llm.AnthropicBatchClient(args.model)
    llm.collect(client, all_tasks)
    llm.submit(client, task, batch)
    if args.wait:
        llm.wait(client, all_tasks)


if __name__ == "__main__":
    main()
