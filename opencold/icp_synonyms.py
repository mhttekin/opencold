"""Curated industry → related-term lexicon for ICP expansion (Tier 1).

Offline, keyless, always-on floor for semantic ICP expansion: maps a canonical
industry key to English related terms that widen search recall and matching
(e.g. "timber" → wood, lumber, sawmill, plywood). A user override file
(``~/.opencold/icp_synonyms.json``) is merged on top at load time, so users widen
coverage without editing the repo. Mirrors ``regions_data.py``: this file is the
single source of truth for the built-in lexicon.

Keys are lower-case canonical industry words; values are related English terms
(the key itself is omitted — the original ICP token always matches on its own).
Keep terms noun-ish, B2B-relevant, and morphology-friendly (the lookup in
``icp_expansion`` is stem/substring aware, so "sawmill" already covers "sawmills"
and "timber merchants" keys to "timber").
"""

from __future__ import annotations

import json


INDUSTRY_SYNONYMS: dict[str, set[str]] = {
    # ---- materials / wood / building ----
    "timber": {"wood", "lumber", "sawmill", "plywood", "hardwood", "softwood",
               "joinery", "forestry", "woodworking", "timber merchant", "veneer", "decking"},
    "lumber": {"timber", "wood", "sawmill", "plywood", "hardwood", "millwork", "building materials"},
    "furniture": {"furnishings", "cabinetry", "joinery", "upholstery", "woodworking", "millwork", "fit-out"},
    "construction": {"contractor", "builder", "civil engineering", "building", "general contractor",
                     "groundworks", "renovation", "infrastructure"},
    "cement": {"concrete", "ready-mix", "aggregates", "precast", "masonry", "building materials"},
    "steel": {"metal", "metalworking", "fabrication", "foundry", "rebar", "structural steel", "ironworks"},
    "glass": {"glazing", "glassware", "fenestration", "windows", "float glass"},
    "roofing": {"roofer", "roof", "cladding", "waterproofing", "insulation"},
    "flooring": {"floor", "tiling", "laminate", "hardwood floors", "carpet", "screeding"},
    "paint": {"coatings", "paints", "varnish", "primer", "decorating", "finishes"},

    # ---- industry / manufacturing ----
    "manufacturing": {"factory", "fabrication", "production", "industrial", "assembly", "oem", "machining"},
    "machinery": {"equipment", "machine tools", "industrial equipment", "automation", "cnc", "tooling"},
    "packaging": {"packing", "cartons", "corrugated", "flexible packaging", "labelling", "containers"},
    "plastics": {"polymer", "injection moulding", "plastic", "extrusion", "moulding", "thermoforming"},
    "chemicals": {"chemical", "specialty chemicals", "petrochemical", "coatings", "adhesives", "polymers"},
    "textiles": {"textile", "fabric", "apparel", "garment", "weaving", "knitwear", "clothing", "yarn"},
    "automotive": {"auto parts", "vehicle", "car", "aftermarket", "components", "motor", "ev"},
    "electronics": {"electronic", "pcb", "semiconductor", "components", "hardware", "embedded"},

    # ---- food / agriculture ----
    "agriculture": {"farming", "agri", "agribusiness", "crops", "agritech", "farm", "horticulture"},
    "food": {"food processing", "beverage", "fmcg", "catering", "bakery", "dairy", "confectionery"},
    "fishery": {"seafood", "aquaculture", "fishing", "fish", "fish farm"},

    # ---- services ----
    "logistics": {"freight", "haulage", "shipping", "courier", "warehousing", "fulfilment",
                  "supply chain", "3pl", "transport", "distribution", "forwarding"},
    "insurance": {"insurer", "underwriting", "broker", "reinsurance", "actuarial", "policy", "claims", "takaful"},
    "consulting": {"consultancy", "advisory", "consultant", "professional services", "strategy"},
    "marketing": {"advertising", "agency", "branding", "digital marketing", "media", "pr", "creative"},
    "accounting": {"accountant", "bookkeeping", "audit", "tax", "payroll", "cpa", "financial reporting"},
    "legal": {"law firm", "solicitor", "attorney", "legal services", "barrister", "counsel"},
    "recruitment": {"staffing", "recruiter", "talent", "headhunting", "hr", "employment agency"},
    "real estate": {"property", "realtor", "estate agent", "letting", "brokerage", "developer"},
    "hospitality": {"hotel", "restaurant", "catering", "tourism", "accommodation", "leisure", "f&b"},
    "education": {"training", "edtech", "school", "academy", "e-learning", "tutoring", "vocational"},
    "healthcare": {"medical", "clinic", "health", "hospital", "pharma", "care", "diagnostics", "dental"},
    "pharmaceutical": {"pharma", "drug", "biotech", "medicine", "life sciences", "generics", "api"},
    "cleaning": {"janitorial", "facilities", "sanitation", "hygiene", "facility management", "fm"},
    "security": {"guarding", "surveillance", "cctv", "alarm", "access control", "cybersecurity"},
    "landscape": {"landscaping", "groundskeeping", "horticulture", "garden", "grounds maintenance",
                  "turf", "arboriculture", "lawn care"},
    "plumbing": {"plumber", "heating", "drainage", "hvac", "sanitary", "pipework"},
    "electrical": {"electrician", "wiring", "electrics", "power", "switchgear", "installation"},

    # ---- energy / environment ----
    "energy": {"power", "renewable", "solar", "utilities", "oil and gas", "wind", "electricity"},
    "solar": {"photovoltaic", "pv", "renewable", "solar panels", "clean energy"},
    "recycling": {"waste", "scrap", "waste management", "recovery", "circular economy", "reclamation"},
    "mining": {"minerals", "quarry", "extraction", "ore", "aggregates", "metals"},

    # ---- tech ----
    "software": {"saas", "app", "platform", "development", "it services", "cloud", "software development"},
    "fintech": {"payments", "banking", "financial technology", "lending", "wallet", "neobank"},
    "ecommerce": {"online retail", "e-commerce", "marketplace", "d2c", "webshop", "retail"},
}


def _load_user_synonyms() -> dict[str, set[str]]:
    """Merge ``~/.opencold/icp_synonyms.json`` over the built-in lexicon. Best-effort:
    returns {} on any failure (missing file, bad JSON) so a broken override never
    breaks discovery. JSON shape: ``{"timber": ["wood", "lumber", ...], ...}``."""
    try:
        from opencold import config
        path = config.CONFIG_DIR / "icp_synonyms.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(k).lower().strip(): {str(t).lower().strip() for t in v if str(t).strip()}
            for k, v in raw.items()
            if isinstance(v, (list, set)) and str(k).strip()
        }
    except Exception:
        return {}


def merged_lexicon() -> dict[str, set[str]]:
    """Built-in lexicon with the user override merged in (user terms add, not replace)."""
    out = {k: set(v) for k, v in INDUSTRY_SYNONYMS.items()}
    for key, terms in _load_user_synonyms().items():
        out.setdefault(key, set()).update(terms)
    return out
