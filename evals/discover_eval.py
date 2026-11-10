"""Discover eval: score a `discover` output CSV against evals/labels/discover_tr_pallets.csv.

Offline: reads the CSV only. Rows are joined to labels by domain (scheme, path and
a leading "www." stripped); the blank gap row and the REVIEW BELOW banner are skipped.

    python -m evals.discover_eval <output.csv> [--labels PATH] [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
LABELS = ROOT / "labels" / "discover_tr_pallets.csv"
RESERVED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}


def domain_of(url: str) -> str:
    u = (url or "").strip().lower()
    if not u:
        return ""
    host = urlparse(u if "://" in u else f"//{u}").netloc or u
    host = host.split("@")[-1].split(":")[0].rstrip(".")
    return host[4:] if host.startswith("www.") else host


def norm_name(s: str) -> str:
    """Casefold, strip diacritics (Turkish dotless ı -> i), punctuation -> single spaces.
    Word boundaries are kept, so 'Sahinlerpalet' != 'Şahinler Palet'."""
    s = (s or "").replace("ı", "i").replace("İ", "I")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s.casefold()).split())


def email_invalid(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False  # empty is "missing", not "invalid"
    host = email.rsplit("@", 1)[1]
    return any(host == d or host.endswith("." + d) for d in RESERVED_EMAIL_DOMAINS)


def phone_invalid(phone: str) -> bool:
    """Invalid unless it is E.164-shaped: a leading '+' and 8-15 digits. Local
    formats with no country code ('05333932020') can't be converted without
    guessing the country, so they count as invalid."""
    p = (phone or "").strip()
    if not p:
        return False  # empty is "missing", not "invalid"
    digits = re.sub(r"\D", "", p)
    return not (p.startswith("+") and 8 <= len(digits) <= 15)


def load_labels(path: Path = LABELS) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return {domain_of(r["website"]): r for r in csv.DictReader(f)}


def load_output(path: Path) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if domain_of(r.get("website", ""))]
    return {domain_of(r["website"]): r for r in rows}


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def score(output_csv: Path, labels_csv: Path = LABELS) -> dict:
    labels = load_labels(labels_csv)
    out = load_output(output_csv)

    def is_verified(d: str) -> bool:
        return out.get(d, {}).get("match_confidence") == "verified"

    def labelled(kind: str) -> set[str]:
        return {d for d, r in labels.items() if r["expected"] == kind}

    verified = {d for d in out if is_verified(d)}
    match, no_match, exclude = labelled("match"), labelled("no_match"), labelled("exclude")

    named = [d for d in labels if labels[d]["expected_name"] and d in out]
    name_ok = [
        d for d in named if norm_name(out[d]["company"]) == norm_name(labels[d]["expected_name"])
    ]

    bad_emails = sorted(
        {
            e
            for r in out.values()
            for e in (r.get("email"), r.get("company_email"))
            if email_invalid(e)
        }
    )
    bad_phones = sorted({r["phone"] for r in out.values() if phone_invalid(r.get("phone", ""))})

    rows = []
    for d in sorted(set(labels) | set(out)):
        r = out.get(d, {})
        rows.append(
            {
                "domain": d,
                "label": labels.get(d, {}).get("expected", "unlabelled"),
                "confidence": r.get("match_confidence", "(absent)"),
                "company": r.get("company", ""),
                "expected_name": labels.get(d, {}).get("expected_name", ""),
            }
        )

    return {
        "output": str(output_csv),
        "metrics": {
            "output_rows": len(out),
            "verified": len(verified),
            "unlabelled_rows": len(set(out) - set(labels)),
            "precision": _ratio(len(verified & match), len(verified & set(labels))),
            "recall": _ratio(len(match & verified), len(match)),
            "no_match_verified": len(no_match & verified),
            "exclude_verified": len(exclude & verified),
            "exclude_leakage": len(exclude & set(out)),
            "exclude_total": len(exclude),
            "name_accuracy": _ratio(len(name_ok), len(named)),
            "invalid_emails": len(bad_emails),
            "invalid_phones": len(bad_phones),
        },
        "invalid_emails": bad_emails,
        "invalid_phones": bad_phones,
        "name_mismatches": [
            {"domain": d, "got": out[d]["company"], "expected": labels[d]["expected_name"]}
            for d in named
            if d not in name_ok
        ],
        "rows": rows,
    }


def _fmt(x) -> str:
    return "n/a" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


def print_report(result: dict) -> None:
    m = result["metrics"]
    print(f"Discover: {result['output']}")
    for k in (
        "output_rows",
        "verified",
        "precision",
        "recall",
        "no_match_verified",
        "exclude_verified",
        "exclude_leakage",
        "name_accuracy",
        "invalid_emails",
        "invalid_phones",
    ):
        extra = f" / {m['exclude_total']}" if k == "exclude_leakage" else ""
        print(f"  {k:18} {_fmt(m[k])}{extra}")
    if result["invalid_emails"]:
        print("  invalid emails:", ", ".join(result["invalid_emails"]))
    if result["invalid_phones"]:
        print("  invalid phones:", ", ".join(result["invalid_phones"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("output_csv", type=Path)
    ap.add_argument("--labels", type=Path, default=LABELS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = score(args.output_csv, args.labels)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
