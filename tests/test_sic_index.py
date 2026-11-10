"""ONS index BM25 candidates and the low-confidence gate (real data, offline)."""

from opencold import sic_index, sic_match, sic_rank

DROP = sic_match.SIC_FILLER | sic_match.STRIP_WORDS


def test_index_maps_activity_phrases_to_codes():
    scores = sic_index.code_scores(["plastic", "pallets"], DROP)
    assert max(scores, key=scores.get) == "22290"


def test_no_fuzzy_matching_pallet_vs_pellet():
    pallet = sic_index.code_scores(["pallet"], DROP)
    pellet = sic_index.code_scores(["pellet"], DROP)
    assert "16240" in pallet and "16240" not in pellet  # wooden pallets
    assert "10910" in pellet and "10910" not in pallet  # alfalfa pellets


def test_scores_are_normalized_coverage():
    scores = sic_index.code_scores(["dental", "practice"], DROP)
    assert all(0.0 < s <= 1.0 for s in scores.values())


def test_unknown_words_lower_coverage():
    known = sic_index.code_scores(["dental"], DROP)
    diluted = sic_index.code_scores(["dental", "zzqxv"], DROP)
    assert diluted["86230"] < known["86230"]


def test_weak_top1_is_low_confidence():
    res = sic_match.match_icp_to_sics("car dealerships")
    assert res.status == "low_confidence"
    assert sic_rank.low_confidence_message(res).startswith("Low SIC confidence")


def test_strong_top1_is_ok():
    res = sic_match.match_icp_to_sics("dental clinics")
    assert res.status == "ok" and res.matches[0].code == "86230"
    assert sic_rank.low_confidence_message(res) == ""


def test_index_data_ships_with_the_package():
    from importlib import resources

    assert resources.files("opencold").joinpath("sic_index_data.csv").is_file()


def test_snowball_stemming_joins_plural_and_derived_forms():
    assert sic_index.stem("bakeries") == sic_index.stem("bakery")
    assert sic_index.stem("pallets") == sic_index.stem("pallet") != sic_index.stem("pellet")
    bakeries = sic_index.code_scores(["bakeries"], DROP)
    assert bakeries == sic_index.code_scores(["bakery"], DROP)  # same stems, same scores
    assert "10710" in bakeries  # bread & fresh pastry goods
