"""Curated industry synonym CLUSTERS for ICP expansion (Tier 1).

Offline, keyless, always-on floor for semantic ICP expansion. The source of truth is
`CLUSTERS` — a list of equivalence classes of *interchangeable* B2B search terms. From
them `merged_lexicon()` builds a SYMMETRIC map: every member of a cluster expands to
every other member, so "timber", "wood", "lumber" and "sawmill" all reach each other
(A↔B↔C), not just the one canonical key. A user override file
(`~/.opencold/icp_synonyms.json`, shape `{"timber": ["wood", ...]}`) is merged on top
as additional clusters. Mirrors `regions_data.py`: edit clusters here only.

Why clusters and not a flat key→list map: symmetry is only safe between genuinely
interchangeable terms. Three kinds of term are therefore kept OUT of clusters,
because members double as matcher evidence and as reverse lookup keys:
  * hub→spoke breadth that is not equivalence — a "courier" is logistics-adjacent but
    is not a "warehouse";
  * cross-industry polysemy — "policy"/"claims" (insurance), "development"/"platform"/
    "app" (software), "api" (pharma), "developer" (real estate), "agency"/"media"
    (marketing), "casting" (film vs foundry), "power"/"infrastructure", which mean
    different things standalone; and
  * everyday English, INCLUDING after stemming — "health" appears on insurance/food/
    fitness pages alike, and bare "lighting" stems to "light" so it would match
    "in light of" anywhere; such concepts enter only as specific multi-word forms
    ("led lighting", "commercial banking").
That looser, associative reach is supplied by the Datamuse + LLM expansion tiers
instead; the lexicon stays a high-precision symmetric core. Lookup in `icp_expansion`
is stem/substring aware, so "sawmills" covers "sawmill" and "timber merchants" keys to
"timber". Multi-word members also key by ICP substring, so an industry whose natural
name is a phrase ("paper mill", "private equity") still fires.
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
    ["carpentry", "carpenter", "joiner", "joinery"],
    ["construction", "contractor", "builder", "civil engineering", "general contractor",
     "groundworks", "renovation"],
    ["cement", "concrete", "ready-mix", "aggregates", "precast", "masonry", "building materials"],
    ["stonemasonry", "stonemason", "marble", "granite", "natural stone", "stonework"],
    ["steel", "metal", "metalworking", "fabrication", "foundry", "rebar", "structural steel", "ironworks"],
    ["glass", "glazing", "glassware", "fenestration", "windows", "float glass"],
    ["roofing", "roofer", "roof", "cladding", "waterproofing", "insulation"],
    ["flooring", "floor", "tiling", "laminate", "hardwood floors", "carpet", "screeding"],
    ["paint", "coatings", "paints", "varnish", "primer", "decorating", "finishes"],
    ["scaffolding", "scaffold", "access platforms", "formwork"],
    ["demolition", "dismantling", "wrecking", "site clearance", "asbestos removal"],
    ["prefabricated", "prefab", "modular construction", "modular buildings", "offsite construction"],
    ["road construction", "asphalt", "paving", "roadworks", "highway maintenance"],
    ["drilling", "borehole", "geotechnical", "piling"],
    ["hvac", "air conditioning", "ventilation", "refrigeration", "heat pump", "heating"],
    ["elevators", "elevator", "escalators", "lift installation"],
    # bare "lighting" stems to "light" (everyday word) and stays out.
    ["led lighting", "luminaires", "light fittings", "lighting manufacturer", "lighting design"],

    # ---- industry / manufacturing ----
    ["manufacturing", "factory", "fabrication", "production", "industrial", "assembly", "oem", "machining"],
    ["machinery", "equipment", "machine tools", "industrial equipment", "automation", "cnc", "tooling"],
    ["welding", "welder", "brazing", "metal fabrication"],
    # "casting" alone is polysemous (film) and stays out.
    ["forging", "foundry", "die casting", "metallurgy"],
    ["robotics", "industrial robots", "robot integration", "automation"],
    ["pumps", "valves", "compressors", "hydraulics", "pneumatics", "fluid handling"],
    ["filtration", "filter systems", "purification", "water treatment"],
    ["cranes", "lifting equipment", "hoists", "material handling", "forklifts"],
    ["packaging", "packing", "cartons", "corrugated", "flexible packaging", "labelling"],
    # "paper" alone is polysemous (newspaper, research paper) and stays out as a key;
    # the phrase keys carry the industry meaning.
    ["paper mill", "pulp mill", "papermaking", "pulp and paper", "paperboard", "tissue paper"],
    ["printing", "commercial printing", "print shop", "offset printing", "digital printing",
     "lithography", "printworks"],
    ["signage", "sign maker", "signwriting"],
    ["3d printing", "additive manufacturing", "rapid prototyping", "stereolithography", "3d printer"],
    ["plastics", "polymer", "injection moulding", "plastic", "extrusion", "moulding", "thermoforming"],
    ["rubber", "elastomers", "gaskets", "rubber moulding"],
    ["composites", "fiberglass", "fibreglass", "carbon fiber", "carbon fibre", "grp"],
    ["ceramics", "porcelain", "pottery", "earthenware", "tiles"],
    ["chemicals", "chemical", "specialty chemicals", "petrochemical", "coatings", "adhesives", "polymers"],
    ["lubricants", "greases", "lubrication"],
    ["textiles", "textile", "fabric", "apparel", "garment", "weaving", "knitwear", "clothing", "yarn"],
    ["footwear", "shoes", "shoemaker", "shoe manufacturer"],
    ["leather", "leather goods", "tannery"],
    ["jewellery", "jewelry", "jeweller", "jeweler", "goldsmith", "gemstones"],
    ["toys", "toy manufacturer"],
    ["fasteners", "fixings", "industrial hardware"],
    ["automotive", "auto parts", "vehicle", "car", "aftermarket", "motor", "ev"],
    ["electronics", "electronic", "pcb", "semiconductor", "embedded systems"],
    ["batteries", "battery", "energy storage", "battery storage", "lithium-ion"],
    ["aerospace", "aviation", "aircraft", "avionics", "mro", "aeronautics"],
    ["defence", "defense", "military equipment", "armaments", "munitions"],
    ["shipbuilding", "shipyard", "marine engineering", "boatbuilding", "naval architecture"],

    # ---- food / agriculture / commodities ----
    ["agriculture", "farming", "agri", "agribusiness", "crops", "agritech", "farm", "horticulture"],
    ["food", "food processing", "beverage", "fmcg", "catering", "bakery", "dairy", "confectionery"],
    ["meat", "meat processing", "abattoir", "slaughterhouse", "butchery", "poultry"],
    ["fishery", "seafood", "aquaculture", "fishing", "fish farm"],
    ["grain", "cereals", "flour mill", "flour milling", "grain trading", "grain storage"],
    ["animal feed", "feed mill", "fodder", "feedstuff"],
    ["fresh produce", "fruit", "vegetables", "fruit and vegetables", "greengrocery"],
    ["edible oils", "vegetable oil", "palm oil", "olive oil", "oilseed"],
    ["sugar", "sugarcane", "sugar mill", "sugar refinery"],
    ["coffee", "coffee roaster", "roastery", "arabica", "robusta", "green coffee", "specialty coffee"],
    ["tea", "tea estate", "tea processing"],
    ["cocoa", "cacao", "chocolate", "chocolatier", "confectionery"],
    ["spices", "seasonings", "herbs and spices"],
    ["winery", "wine", "vineyard", "winemaking", "winemaker", "vintner", "viticulture"],
    ["brewery", "brewing", "craft beer", "microbrewery", "brewhouse"],
    ["tobacco", "tobacco processing", "cigarette manufacturer"],
    ["cannabis", "cbd", "hemp"],
    ["fertilizer", "fertiliser", "agrochemicals", "pesticides", "crop protection"],
    ["agricultural machinery", "farm equipment", "tractors"],
    ["irrigation", "irrigation systems", "sprinkler systems"],
    ["florist", "floristry", "cut flowers", "floriculture"],
    ["pet care", "pet food", "pet grooming", "kennels", "pet supplies"],

    # ---- transport / trade ----
    ["logistics", "freight", "freight forwarding", "haulage", "shipping", "supply chain", "3pl", "distribution"],
    ["exporter", "export", "importer", "trader", "trading company", "commodity trader"],
    ["wholesale", "wholesaler", "wholesale distribution", "distribution"],
    ["courier", "parcel delivery", "last mile delivery"],
    ["warehousing", "fulfilment", "storage"],
    ["cold storage", "cold chain", "refrigerated transport", "temperature controlled"],
    ["removals", "moving company", "relocation", "movers"],
    ["airline", "air charter", "air cargo"],
    ["stevedoring", "port operations", "terminal operator", "shipping agency"],
    ["railway", "railroad", "rolling stock", "rail freight"],
    ["passenger transport", "bus operator", "coach hire"],
    ["car rental", "vehicle hire", "car hire", "fleet leasing"],
    ["car dealership", "auto repair", "bodyshop", "vehicle servicing", "mechanic", "tyre fitting", "tire fitting"],

    # ---- services ----
    ["insurance", "insurer", "underwriting", "reinsurance", "actuarial", "takaful", "insurance broker"],
    ["consulting", "consultancy", "advisory", "consultant", "professional services"],
    ["marketing", "advertising", "branding", "digital marketing"],
    ["seo", "search engine optimisation", "search engine optimization", "ppc", "digital marketing"],
    ["public relations", "pr agency", "communications agency", "press office"],
    ["graphic design", "design agency", "design studio", "creative agency", "branding agency"],
    ["web design", "web development", "digital agency", "app development", "software house"],
    ["photography", "photographer", "videography", "video production"],
    ["event management", "events agency", "conference organiser", "conference organizer",
     "exhibition organiser", "exhibition organizer", "event planning"],
    ["translation", "interpreting", "localisation", "localization", "language services"],
    ["accounting", "accountant", "bookkeeping", "audit", "tax", "payroll", "cpa", "financial reporting"],
    ["legal", "law firm", "solicitor", "attorney", "legal services", "barrister", "counsel",
     "conveyancing", "notary", "paralegal"],
    ["recruitment", "staffing", "recruiter", "talent", "headhunting", "employment agency"],
    ["call center", "call centre", "contact center", "contact centre", "bpo", "telemarketing"],
    ["real estate", "property", "realtor", "estate agent", "letting", "property developer"],
    ["property management", "block management", "letting agency", "estate management"],
    ["architecture", "architect", "architectural design"],
    ["interior design", "interior designer", "fit-out", "shopfitting", "shop fitting"],
    ["surveying", "surveyor", "land surveying", "quantity surveying", "geomatics"],
    # bare "engineering" is polysemous (software pages say it constantly) and stays out.
    ["structural engineering", "civil engineering", "engineering consultancy", "mep"],
    ["testing and certification", "inspection", "certification body", "laboratory testing",
     "calibration", "ndt"],
    ["hospitality", "hotel", "restaurant", "catering", "tourism", "accommodation", "leisure"],
    ["travel agency", "tour operator", "travel agent", "tourism"],
    ["education", "training", "edtech", "school", "academy", "e-learning", "tutoring", "vocational"],
    ["childcare", "daycare", "preschool", "kindergarten"],
    ["cleaning", "janitorial", "facilities", "sanitation", "hygiene", "facility management"],
    ["laundry", "dry cleaning", "linen services", "launderette"],
    ["pest control", "pest management", "exterminator", "fumigation"],
    ["locksmith", "locksmithing", "key cutting"],
    ["security", "guarding", "surveillance", "cctv", "alarm", "access control"],
    ["landscape", "landscaping", "groundskeeping", "horticulture", "garden", "grounds maintenance",
     "turf", "arboriculture", "lawn care"],
    ["plumbing", "plumber", "heating", "drainage", "hvac", "sanitary", "pipework"],
    ["electrical", "electrician", "wiring", "electrics", "switchgear"],
    ["funeral services", "funeral home", "undertaker", "mortuary"],
    ["nonprofit", "non-profit", "ngo", "charitable organisation", "charitable organization"],

    # ---- health / care / lifestyle ----
    # "health" (everyday word: insurance, food, fitness pages all say it) stays out
    # as a member — cluster members are matcher evidence and must be specific.
    ["healthcare", "medical", "clinic", "hospital", "diagnostics"],
    ["dental", "dentist", "dentistry", "orthodontics", "dental clinic"],
    ["pharmaceutical", "pharma", "drug", "biotech", "medicine", "life sciences", "generics"],
    ["medical devices", "medtech", "medical equipment", "surgical instruments", "diagnostics"],
    ["laboratory", "laboratories", "lab equipment", "scientific instruments", "analytical instruments"],
    ["veterinary", "veterinarian", "animal health", "animal hospital", "vet practice"],
    ["care home", "nursing home", "elderly care", "assisted living", "domiciliary care"],
    ["physiotherapy", "physical therapy", "chiropractic", "osteopathy", "sports therapy"],
    ["optician", "optometry", "eyewear"],
    ["cosmetics", "skincare", "skin care", "beauty products", "personal care", "toiletries", "haircare"],
    ["hairdressing", "hairdresser", "barbershop", "barber", "beauty salon", "nail salon"],
    ["spa", "wellness", "massage therapy", "day spa"],
    ["fitness", "gym", "health club", "personal training", "leisure centre", "leisure center"],

    # ---- energy / environment ----
    ["energy", "renewable", "utilities", "oil and gas", "electricity"],
    ["solar", "photovoltaic", "solar panels", "clean energy", "renewable"],
    ["wind energy", "wind turbines", "wind farm", "offshore wind", "wind power", "renewable"],
    ["hydrogen", "fuel cell", "electrolyser", "electrolyzer", "green hydrogen"],
    ["nuclear", "nuclear power", "nuclear energy"],
    ["petroleum", "oilfield", "refinery", "lng", "oil and gas"],
    ["recycling", "waste", "scrap", "waste management", "circular economy", "reclamation"],
    ["water treatment", "wastewater", "desalination", "sewage treatment", "effluent"],
    ["sustainability", "esg", "csr", "sustainable", "environmental", "carbon footprint",
     "net zero", "decarbonisation", "decarbonization", "greenhouse gas"],
    ["mining", "minerals", "quarry", "extraction", "ore", "metals"],

    # ---- finance ----
    ["fintech", "payments", "financial technology", "lending", "neobank"],
    # bare "banking"/"bank" stem-match "bank transfer" on any contact page and stay out.
    ["commercial banking", "retail banking", "investment banking", "microfinance",
     "credit union", "building society"],
    ["wealth management", "asset management", "investment management", "fund management"],
    ["private equity", "venture capital", "investment fund"],

    # ---- tech / digital / media ----
    # bare "software" is a GENERIC_ICP_TERMS word: never looked up as a key and
    # too broad as evidence; the multi-word forms carry the meaning.
    ["saas", "it services", "software development", "cloud computing", "software house"],
    ["managed services", "msp", "it support", "helpdesk"],
    ["cybersecurity", "infosec", "penetration testing", "information security"],
    ["data analytics", "business intelligence", "data science", "big data"],
    ["artificial intelligence", "machine learning", "deep learning", "ai"],
    ["iot", "internet of things", "connected devices", "smart sensors"],
    ["blockchain", "cryptocurrency", "crypto", "web3"],
    ["erp", "crm", "enterprise software", "business software"],
    ["web hosting", "data center", "data centre", "colocation"],
    ["telecommunications", "telecom", "telco", "broadband", "isp", "fibre optic", "fiber optic"],
    ["ecommerce", "online retail", "e-commerce", "webshop", "d2c"],
    ["video games", "game development", "game studio"],
    ["casino", "gambling", "betting", "igaming", "bookmaker"],
    ["publishing", "publisher", "book publishing", "periodicals"],
    ["broadcasting", "broadcaster", "tv production", "radio station"],
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
