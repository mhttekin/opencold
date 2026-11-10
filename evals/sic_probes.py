"""Unlabelled SIC probe ICPs: a sanity check on varied wording, NOT a scored eval.

Prints the top-1 SIC (and status) per probe so ranking/stemming changes can be
eyeballed beyond the six labelled cases. Offline: no expansion, no LLM.

    python -m evals.sic_probes
"""

from __future__ import annotations

from opencold import sic_match

PROBES = [
    # varied industries (used to choose SIC_CONFIDENCE_MIN; not tuned to labels)
    "dental clinics",
    "bakeries",
    "craft breweries",
    "metal fabrication",
    "software consultancy",
    "accountants",
    "furniture manufacturers",
    "organic dairy farms",
    "solar panel installers",
    "printing services",
    "dog grooming",
    "boat builders",
    "car dealerships",
    "recruitment agencies",
    "glass bottle manufacturers",
    # plural / derived forms
    "bakery",
    "breweries",
    "brewers",
    "printers",
    "roofers",
    "roofing contractors",
    "plumbers",
    "joiners",
    "upholsterers",
    "galvanising",
    "machinists",
    "manufacturing of furniture",
    "dentists",
    # nonsense / too vague (should stay low-confidence or empty)
    "zebra quantum",
    "blorp widgets",
    "stuff",
    "industrial things",
]


def run() -> list[dict]:
    out = []
    for icp in PROBES:
        r = sic_match.match_icp_to_sics(icp, roles=sic_match.detect_icp_roles(icp))
        top = r.matches[0] if r.matches else None
        out.append(
            {
                "icp": icp,
                "status": r.status,
                "code": top.code if top else "",
                "score": top.score if top else 0.0,
                "description": top.description if top else "",
            }
        )
    return out


def main() -> None:
    for p in run():
        print(
            f"{p['icp']:28} {p['status']:14} {p['score']:5.2f} {p['code']:5} {p['description'][:55]}"
        )


if __name__ == "__main__":
    main()
