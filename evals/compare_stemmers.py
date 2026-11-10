"""Compare BM25 stemming variants on the labelled SIC eval and the probe ICPs.

    python -m evals.compare_stemmers

Variants swap `sic_index.stem` (applied to both index rows and query) at runtime:
none (identity), snowball (Snowball English), plural (the shipped plural-only folding).
Offline: the labelled eval replays its cassettes; probes run without expansion.
"""

from __future__ import annotations

from evals import sic_eval, sic_probes
from opencold import sic_index


def _snowball():
    import snowballstemmer  # comparison only: pip install snowballstemmer

    return snowballstemmer.stemmer("english").stemWord


VARIANTS = {
    "none": lambda w: w,
    "snowball": _snowball(),
    "plural": sic_index.stem.__wrapped__,  # the shipped stemmer (plural-only folding)
}


def run_variant(fn) -> tuple[dict, list[dict]]:
    original = sic_index.stem
    sic_index.stem = fn
    sic_index._index.cache_clear()
    try:
        return sic_eval.run(), sic_probes.run()
    finally:
        sic_index.stem = original
        sic_index._index.cache_clear()


def main() -> None:
    results = {name: run_variant(fn) for name, fn in VARIANTS.items()}
    print("labelled SIC eval")
    for name, (ev, _) in results.items():
        m = ev["metrics"]
        print(
            f"  {name:9} top1 {m['top1_accuracy']:.2f}  lenient {m['top1_lenient']:.2f}  "
            f"recall@5 {m['recall_at_5']:.2f}  sibling {m['sibling_confusion']}  abstain {m['abstain']}"
        )
    print("\nlabelled cases, top-1 per variant")
    cases = [c["icp"] for c in results["none"][0]["cases"]]
    for i, icp in enumerate(cases):
        cells = []
        for name, (ev, _) in results.items():
            c = ev["cases"][i]
            top = c["top5"][0]["code"] if c["top5"] else "-"
            cells.append(f"{name}={top}{'✓' if c['top1_correct'] else '✗'}")
        print(f"  {icp[:32]:32} " + "  ".join(cells))
    print("\nprobes, top-1 per variant (status)")
    for i, icp in enumerate(sic_probes.PROBES):
        cells = []
        for name, (_, probes) in results.items():
            p = probes[i]
            cells.append(
                f"{name}={p['code'] or '-':5} {p['status'][:6]:6} {p['description'][:24]:24}"
            )
        print(f"  {icp[:24]:24} " + " | ".join(cells))


if __name__ == "__main__":
    main()
