"""SIC matching eval: ICP -> ranked SIC codes, scored against evals/labels/sic_cases.toml.

Runs the same path as the non-interactive `smearch` CLI: roles detected from the
ICP, keyless expansion (lexicon + Datamuse), no LLM, max_sics=5, min_score=1.0.
Datamuse responses are replayed from evals/cassettes/sic/ (vcrpy); `--record`
re-records them against the live API.

    python -m evals.sic_eval [--record] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import tomllib
import urllib.request
from pathlib import Path

import vcr
from vcr.errors import CannotOverwriteExistingCassetteException

from opencold import config, icp_expansion, sic_match, sic_semantic, smearch

ROOT = Path(__file__).resolve().parent
LABELS = ROOT / "labels" / "sic_cases.toml"
CASSETTES = ROOT / "cassettes" / "sic"
TOP_K = 5


class StaleCassette(RuntimeError):
    pass


def load_cases(path: Path = LABELS) -> list[dict]:
    with open(path, "rb") as f:
        return tomllib.load(f)["case"]


def _slug(icp: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", icp.lower()).strip("_")


def ranked_sics(icp: str, *, record: bool = False) -> tuple[list[sic_match.SicMatch], str, str]:
    """(top-K matches with scores, status) for one ICP, network via cassette."""
    misses: list[str] = []
    real_urlopen = urllib.request.urlopen

    def tracking_urlopen(req, *a, **k):
        try:
            return real_urlopen(req, *a, **k)
        except CannotOverwriteExistingCassetteException:
            misses.append(getattr(req, "full_url", str(req)))
            raise

    cassette = CASSETTES / f"{_slug(icp)}.yaml"
    recorder = vcr.VCR(
        record_mode="all" if record else "none",
        match_on=["method", "uri"],
        decode_compressed_response=True,
    )
    with tempfile.TemporaryDirectory() as tmp:
        # Isolate from the user's ~/.opencold (expansion disk cache, user synonyms).
        old_dir, old_cache = config.CONFIG_DIR, icp_expansion._DISK_CACHE
        config.CONFIG_DIR, icp_expansion._DISK_CACHE = Path(tmp), None
        urllib.request.urlopen = tracking_urlopen
        try:
            if not record and not cassette.exists():
                raise StaleCassette(f"missing cassette {cassette.name}; run with --record")
            with recorder.use_cassette(str(cassette)):
                result = smearch.plan_matches(
                    icp,
                    roles=sic_match.detect_icp_roles(icp),
                    use_expansion=True,
                    use_llm=False,
                    max_sics=TOP_K,
                    min_score=1.0,
                )
        finally:
            urllib.request.urlopen = real_urlopen
            config.CONFIG_DIR, icp_expansion._DISK_CACHE = old_dir, old_cache
    if misses:
        raise StaleCassette(f"{cassette.name} has no recording for {misses[0]}; run --record")
    return result.matches[:TOP_K], result.status, result.mode


def score_case(case: dict, matches: list[sic_match.SicMatch], status: str, mode: str) -> dict:
    expected = set(case.get("expected", []))
    acceptable = set(case.get("acceptable", []))
    must_not = set(case.get("must_not_top1", []))
    codes = [m.code for m in matches]
    top1 = codes[0] if codes else None
    return {
        "icp": case["icp"],
        "status": status,
        "mode": mode,
        # How many of the top-5 share the top-1 score (>1 = top-1 decided by tie-break).
        "top1_tied_with": sum(abs(m.score - matches[0].score) < 1e-9 for m in matches)
        if matches
        else 0,
        "top5": [
            {"code": m.code, "score": m.score, "role": m.role, "description": m.description}
            for m in matches
        ],
        "abstain": top1 is None,
        "top1_correct": top1 in expected,
        "top1_lenient": top1 in expected | acceptable,
        "recall_at_5": len(expected & set(codes)) / len(expected) if expected else None,
        "sibling_confusion": top1 in must_not,
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    answered = [r for r in rows if not r["abstain"]]
    recalls = [r["recall_at_5"] for r in rows if r["recall_at_5"] is not None]
    return {
        "cases": n,
        "abstain": sum(r["abstain"] for r in rows),
        "top1_accuracy": sum(r["top1_correct"] for r in rows) / n,
        "top1_lenient": sum(r["top1_lenient"] for r in rows) / n,
        "recall_at_5": sum(recalls) / len(recalls) if recalls else None,
        "sibling_confusion": sum(r["sibling_confusion"] for r in answered),
    }


def _prepare_semantic(model: str | None) -> str:
    """Opt into hybrid matching and load the model ONCE, before cassettes and the
    CONFIG_DIR redirect. Unlike the product (which silently falls back to BM25), the
    eval fails loudly: a 'hybrid' score measured in lexical mode would be a lie."""
    os.environ[sic_semantic.MATCHING_ENV] = "hybrid"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # use the downloaded model, no network
    sic_semantic.MODEL = model or sic_semantic.MODEL
    if sic_semantic.load() is None:
        raise RuntimeError(
            f"semantic eval: cannot load {sic_semantic.MODEL}. Install the extra "
            "(pip install -e '.[semantic]') and download the model once with HF_HUB_OFFLINE=0."
        )
    return sic_semantic.MODEL


def run(record: bool = False, semantic: bool = False, model: str | None = None) -> dict:
    used_model = _prepare_semantic(model) if semantic else None
    rows = []
    for case in load_cases():
        matches, status, mode = ranked_sics(case["icp"], record=record)
        if semantic and mode != "hybrid":
            raise RuntimeError(f"semantic eval fell back to {mode} for {case['icp']!r}")
        rows.append(score_case(case, matches, status, mode))
    return {
        "mode": "hybrid" if semantic else "lexical",
        "model": used_model,
        "metrics": summarize(rows),
        "cases": rows,
    }


def print_report(result: dict) -> None:
    for r in result["cases"]:
        flag = "ABSTAIN" if r["abstain"] else ("OK" if r["top1_correct"] else "MISS")
        if r["sibling_confusion"]:
            flag += " sibling-confusion"
        tie = f" TIE x{r['top1_tied_with']}" if r.get("top1_tied_with", 0) > 1 else ""
        print(f"\n{r['icp']!r}  [{flag}{tie}] status={r['status']} mode={r.get('mode')}")
        for i, m in enumerate(r["top5"], 1):
            print(f"  {i}. {m['code']}  {m['score']:4.2f}  {m['description'][:70]}")
    m = result["metrics"]
    print(
        f"\nSIC: top1 {m['top1_accuracy']:.2f} | lenient {m['top1_lenient']:.2f} | "
        f"recall@5 {m['recall_at_5']:.2f} | sibling confusion {m['sibling_confusion']} | "
        f"abstain {m['abstain']}/{m['cases']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="re-record Datamuse cassettes")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a report")
    ap.add_argument("--semantic", action="store_true", help="hybrid BM25+embedding mode")
    ap.add_argument("--model", help="embedding model for --semantic (default: sic_semantic.MODEL)")
    args = ap.parse_args()
    result = run(record=args.record, semantic=args.semantic, model=args.model)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
