"""Category -> member-term expansion for SIC matching, grounded in SIC names.

Asymmetric (one-directional): a broad ICP category like "food" should also match
the specific things food SICs are named after -- meat, dairy, fish, bread -- but
"meat" must NOT pull in "dairy". That one-directionality is why this is separate
from the symmetric synonym lexicon in icp_synonyms.py.

Every member is verified to appear in actual Companies House SIC descriptions, so
expansion improves recall without drifting off-sector. Ambiguous members are
omitted on purpose (e.g. "oil" would hit "Mineral oil refining"; "rope" is a
substring of "property"). Keep additions conservative and SIC-grounded.
"""
from __future__ import annotations

from opencold.icp_phrases import stem

CATEGORY_HYPONYMS: dict[str, list[str]] = {
    "food": ["meat", "poultry", "fish", "crustacean", "fruit", "vegetable",
             "potato", "dairy", "milk", "cheese", "bread", "pastry", "biscuit",
             "confectionery", "chocolate", "cocoa", "sugar", "cereal", "grain",
             "flour", "starch", "spice", "margarine"],
    "beverage": ["beer", "wine", "cider", "spirit", "malt", "juice"],
    "clothing": ["apparel", "workwear", "underwear", "outerwear", "hosiery", "fur"],
    "textile": ["fabric", "woven", "knitted", "fibre", "carpet", "twine", "cordage"],
    "metal": ["steel", "iron", "aluminium", "copper", "zinc", "lead", "tin", "brass"],
    "vehicle": ["motor", "trailer", "bicycle", "motorcycle"],
    "chemical": ["paint", "varnish", "soap", "detergent", "pesticide", "explosive", "ink"],
    "paper": ["pulp", "paperboard", "corrugated", "stationery"],
    "electronic": ["computer", "electronic"],
    "electrical": ["cable", "wiring", "appliance"],
    "cosmetic": ["perfume", "cosmetic"],
    "leather": ["leather", "tanning", "luggage", "footwear"],
    "ceramic": ["ceramic", "tile", "brick", "refractory"],
    "construction": ["building", "cement", "concrete", "brick"],
    "furniture": ["furniture", "mattress"],
    # single-member bridges: the user's word -> the spelling SIC titles use.
    "footwear": ["footwear"],
    "jewellery": ["jewellery"],
    "pharmaceutical": ["pharmaceutical"],
}

# Extra user spellings/abbreviations -> canonical category above.
_ALIASES: dict[str, str] = {
    "drink": "beverage", "drinks": "beverage",
    "clothes": "clothing", "apparel": "clothing", "garment": "clothing",
    "automotive": "vehicle", "auto": "vehicle",
    "electronics": "electronic", "cosmetics": "cosmetic",
    "jewelry": "jewellery", "pharma": "pharmaceutical",
    "shoes": "footwear", "shoe": "footwear",
}

# Looked up by stem so "foods"/"metals"/"clothing" resolve like their canonical.
_BY_STEM: dict[str, list[str]] = {}
for _k, _members in CATEGORY_HYPONYMS.items():
    _BY_STEM[stem(_k)] = _members
for _alias, _canon in _ALIASES.items():
    _BY_STEM.setdefault(stem(_alias), CATEGORY_HYPONYMS[_canon])


def category_members(token: str) -> set[str]:
    """Member sub-sector terms for an ICP token that names a broad category
    (e.g. 'food' -> {meat, dairy, ...}); empty set if it isn't a known category."""
    return set(_BY_STEM.get(stem(token), ()))
