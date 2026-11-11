"""Score rule-based and LLM technology extraction against hand labels: `python -m enrich.evaluate`.

Labels are in eval/hn_labels.csv: the technology_ids a careful reader would list from the
same input the model sees (title, link domain, text). Only stories that both methods have
covered are scored, so the two are compared on identical ground.
Micro-averaged: every (story, technology) pair counts once.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb

from ingestion import landing

LABELS = Path(__file__).resolve().parents[1] / "eval" / "hn_labels.csv"


def load_labels(path: Path = LABELS) -> dict[str, set[str]]:
    with open(path) as f:
        return {
            row["story_id"]: {t for t in row["expected"].split(";") if t}
            for row in csv.DictReader(f)
        }


def score(predicted: dict[str, set[str]], expected: dict[str, set[str]]) -> dict[str, float]:
    tp = sum(len(predicted.get(s, set()) & e) for s, e in expected.items())
    fp = sum(len(predicted.get(s, set()) - e) for s, e in expected.items())
    fn = sum(len(e - predicted.get(s, set())) for s, e in expected.items())
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _predictions(con: duckdb.DuckDBPyConnection, model: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for doc, tech in con.execute(f"select document_id, technology_id from main.{model}").fetchall():
        found.setdefault(str(doc), set()).add(tech)
    return found


def main() -> None:
    labels = load_labels()
    warehouse = Path(landing.store().path("gold", "warehouse.duckdb"))
    with duckdb.connect(str(warehouse), read_only=True) as con:
        answered = {
            d
            for (d,) in con.execute(
                "select distinct doc_id from main.stg_llm_responses "
                "where task = 'hn_technologies' and status = 'succeeded'"
            ).fetchall()
        }
        rules = _predictions(con, "int_hn_story_technologies")
        llm = _predictions(con, "int_hn_story_technologies_llm")
    covered = {s: e for s, e in labels.items() if s in answered}
    if not covered:
        sys.exit(f"None of the {len(labels)} labelled stories has an LLM answer yet.")
    print(f"{len(covered)} of {len(labels)} labelled stories have an LLM answer.\n")
    print(f"{'method':8} {'precision':>9} {'recall':>7} {'f1':>6}   tp  fp  fn")
    for name, predicted in (("rules", rules), ("llm", llm)):
        s = score(predicted, covered)
        print(
            f"{name:8} {s['precision']:9.2f} {s['recall']:7.2f} {s['f1']:6.2f}"
            f"  {s['tp']:3} {s['fp']:3} {s['fn']:3}"
        )
    print("\nDisagreements with the labels:")
    for story, expected in sorted(covered.items()):
        for name, predicted in (("rules", rules), ("llm", llm)):
            got = predicted.get(story, set())
            if got != expected:
                extra, missing = sorted(got - expected), sorted(expected - got)
                print(f"  {story} {name:5} extra={extra} missing={missing}")


if __name__ == "__main__":
    main()
