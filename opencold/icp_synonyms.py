"""Curated industry synonym CLUSTERS for ICP expansion (Tier 1).

Offline, keyless, always-on floor for semantic ICP expansion. The source of truth is
`CLUSTERS` — a list of equivalence classes of *interchangeable* B2B search terms. From
them `merged_lexicon()` builds a SYMMETRIC map: every member of a cluster expands to
every other member, so "timber", "wood", "lumber" and "sawmill" all reach each other
(A↔B↔C), not just the one canonical key. A user override file
(`~/.opencold/icp_synonyms.json`, shape `{"timber": ["wood", ...]}`) is merged on top
as additional clusters. Mirrors `regions_data.py`: edit clusters here only.

Why clusters and not a flat key→list map: symmetry is only safe between genuinely
interchangeable terms. Two kinds of term are therefore kept OUT of clusters, because
reversing them would mislead:
  * hub→spoke breadth that is not equivalence — a "courier" is logistics-adjacent but
    is not a "warehouse"; and
  * cross-industry polysemy — "policy"/"claims" (insurance), "development"/"platform"/
    "app" (software), "api" (pharma), "developer" (real estate), "agency"/"media"
    (marketing), "power"/"infrastructure", etc., which mean different things standalone.
That looser, associative reach is supplied by the Datamuse + LLM expansion tiers
instead; the lexicon stays a high-precision symmetric core. Lookup in `icp_expansion`
is stem/substring aware, so "sawmills" covers "sawmill" and "timber merchants" keys to
"timber".
"""

from __future__ import annotations

import json


# Each inner list is an equivalence class: every member is interchangeable with every
# other as a B2B search target. Order is cosmetic. Terms appearing in two clusters
# (e.g. "joinery" in timber+furniture) bridge those clusters — and ONLY those — which
# is intended; there is no transitive merging beyond a shared term.
CLUSTERS: list[list[str]] = [
    # ---- materials / wood / building ----
    ["timber", "wood", "lumber", "sawmill", "plywood", "hardwood", "softwood",
     "joinery", "forestry", "woodworking", "timber merchant", "veneer", "decking", "millwork"],
    ["furniture", "furnishings", "cabinetry", "joinery", "upholstery", "woodworking", "millwork", "fit-out"],
    ["construction", "contractor", "builder", "civil engineering", "general contractor",
     "groundworks", "renovation"],
    ["cement", "concrete", "ready-mix", "aggregates", "precast", "masonry", "building materials"],
    ["steel", "metal", "metalworking", "fabrication", "foundry", "rebar", "structural steel", "ironworks"],
    ["glass", "glazing", "glassware", "fenestration", "windows", "float glass"],
    ["roofing", "roofer", "roof", "cladding", "waterproofing", "insulation"],
    ["flooring", "floor", "tiling", "laminate", "hardwood floors", "carpet", "screeding"],
    ["paint", "coatings", "paints", "varnish", "primer", "decorating", "finishes"],

    # ---- industry / manufacturing ----
    ["manufacturing", "factory", "fabrication", "production", "industrial", "assembly", "oem", "machining"],
    ["machinery", "equipment", "machine tools", "industrial equipment", "automation", "cnc", "tooling"],
    ["packaging", "packing", "cartons", "corrugated", "flexible packaging", "labelling"],
    ["plastics", "polymer", "injection moulding", "plastic", "extrusion", "moulding", "thermoforming"],
    ["chemicals", "chemical", "specialty chemicals", "petrochemical", "coatings", "adhesives", "polymers"],
    ["textiles", "textile", "fabric", "apparel", "garment", "weaving", "knitwear", "clothing", "yarn"],
    ["automotive", "auto parts", "vehicle", "car", "aftermarket", "motor", "ev"],
    ["electronics", "electronic", "pcb", "semiconductor", "embedded systems"],

    # ---- food / agriculture ----
    ["agriculture", "farming", "agri", "agribusiness", "crops", "agritech", "farm", "horticulture"],
    ["food", "food processing", "beverage", "fmcg", "catering", "bakery", "dairy", "confectionery"],
    ["fishery", "seafood", "aquaculture", "fishing", "fish farm"],

    # ---- services ----
    ["logistics", "freight", "freight forwarding", "haulage", "shipping", "supply chain", "3pl", "distribution"],
    ["courier", "parcel delivery", "last mile delivery"],
    ["warehousing", "fulfilment", "storage"],
    ["insurance", "insurer", "underwriting", "reinsurance", "actuarial", "takaful"],
    ["consulting", "consultancy", "advisory", "consultant", "professional services"],
    ["marketing", "advertising", "branding", "digital marketing"],
    ["accounting", "accountant", "bookkeeping", "audit", "tax", "payroll", "cpa", "financial reporting"],
    ["legal", "law firm", "solicitor", "attorney", "legal services", "barrister", "counsel"],
    ["recruitment", "staffing", "recruiter", "talent", "headhunting", "employment agency"],
    ["real estate", "property", "realtor", "estate agent", "letting"],
    ["hospitality", "hotel", "restaurant", "catering", "tourism", "accommodation", "leisure"],
    ["education", "training", "edtech", "school", "academy", "e-learning", "tutoring", "vocational"],
    ["healthcare", "medical", "clinic", "health", "hospital", "diagnostics", "dental"],
    ["pharmaceutical", "pharma", "drug", "biotech", "medicine", "life sciences", "generics"],
    ["cleaning", "janitorial", "facilities", "sanitation", "hygiene", "facility management"],
    ["security", "guarding", "surveillance", "cctv", "alarm", "access control"],
    ["landscape", "landscaping", "groundskeeping", "horticulture", "garden", "grounds maintenance",
     "turf", "arboriculture", "lawn care"],
    ["plumbing", "plumber", "heating", "drainage", "hvac", "sanitary", "pipework"],
    ["electrical", "electrician", "wiring", "electrics", "switchgear"],

    # ---- energy / environment ----
    ["energy", "renewable", "utilities", "oil and gas", "electricity"],
    ["solar", "photovoltaic", "solar panels", "clean energy", "renewable"],
    ["recycling", "waste", "scrap", "waste management", "circular economy", "reclamation"],
    ["mining", "minerals", "quarry", "extraction", "ore", "metals"],

    # ---- tech ----
    ["software", "saas", "it services", "software development", "cloud computing"],
    ["fintech", "payments", "financial technology", "lending", "neobank"],
    ["ecommerce", "online retail", "e-commerce", "webshop", "d2c"],
]


def _symmetric_from_clusters(clusters: list) -> dict[str, set[str]]:
    """Build term -> co-members from equivalence clusters. A term in several clusters
    maps to the union of its clusters' members (only directly-shared terms bridge)."""
    out: dict[str, set[str]] = {}
    for cluster in clusters:
        members = {str(m).strip().lower() for m in cluster if str(m).strip()}
        for m in members:
            out.setdefault(m, set()).update(members - {m})
    return out


def _load_user_synonyms() -> list[list[str]]:
    """User override clusters from `~/.opencold/icp_synonyms.json`. Each entry
    `{"timber": ["wood", ...]}` becomes the cluster `[timber, wood, ...]` (so override
    links are symmetric too). Best-effort: returns [] on any failure (missing/bad file)
    so a broken override never breaks discovery."""
    try:
        from opencold import config
        path = config.CONFIG_DIR / "icp_synonyms.json"
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            [str(k)] + [str(t) for t in v if str(t).strip()]
            for k, v in raw.items()
            if isinstance(v, (list, set)) and str(k).strip()
        ]
    except Exception:
        return []


def merged_lexicon() -> dict[str, set[str]]:
    """Symmetric term -> related-terms map from the built-in clusters plus the user
    override clusters. Every cluster member is a lookup key, so expansion is
    bidirectional (timber<->wood<->sawmill)."""
    return _symmetric_from_clusters(CLUSTERS + _load_user_synonyms())
