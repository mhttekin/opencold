"""Tests for phrase-aware ICP parsing and matching (opencold.icp_phrases).

Pure unit tests: the chunker state machine, the phrase/window/compound matcher,
per-token evidence (incl. provenance classes), and the all-core-tokens gate that
stops a single generic word ("consultancy") from confirming a multi-word ICP.
"""

from opencold import icp_phrases
from opencold.icp_phrases import (
    CoreMatch,
    evidence_core,
    parse_icp,
    phrase_hit,
    stem,
    text_words,
    token_evidenced,
)


def _chunks(icp):
    return [(c.role, list(c.tokens)) for c in parse_icp(icp).chunks]


class TestParseIcp:
    def test_single_word(self):
        p = parse_icp("Plumbing")
        assert _chunks("Plumbing") == [("core", ["plumbing"])]
        assert p.core_tokens == ("plumbing",)
        assert p.qualifier_tokens == ()
        assert p.core_phrases == ()

    def test_modifier_head_with_qualifier(self):
        p = parse_icp("Sustainability Consultancy for SMEs")
        assert _chunks("Sustainability Consultancy for SMEs") == [
            ("core", ["sustainability", "consultancy"]),
            ("qualifier", ["smes"]),
        ]
        assert p.core_tokens == ("sustainability", "consultancy")
        assert p.qualifier_tokens == ("smes",)
        assert p.core_phrases == (("sustainability", "consultancy"),)

    def test_two_word_core(self):
        p = parse_icp("Paper Mill")
        assert p.core_tokens == ("paper", "mill")
        assert p.core_phrases == (("paper", "mill"),)

    def test_of_attachment_stays_core(self):
        p = parse_icp("Manufacturers of Industrial Pumps")
        assert _chunks("Manufacturers of Industrial Pumps") == [
            ("core", ["manufacturers"]),
            ("core", ["industrial", "pumps"]),
        ]
        assert p.core_tokens == ("manufacturers", "industrial", "pumps")
        # Only the multi-token sub-chunk is a phrase unit.
        assert p.core_phrases == (("industrial", "pumps"),)

    def test_all_generic_core_has_empty_gate_set(self):
        p = parse_icp("software companies")
        assert [c.tokens for c in p.chunks] == [("software", "companies")]
        assert p.core_tokens == ()           # legacy gate semantics downstream
        assert p.core_phrases == ()          # no required token -> not a phrase unit

    def test_transparent_conjunction_keeps_one_chunk(self):
        p = parse_icp("Health and Safety Consultants")
        assert p.core_tokens == ("health", "safety", "consultants")
        assert p.core_phrases == (("health", "safety", "consultants"),)

    def test_qualifier_flip_is_permanent(self):
        p = parse_icp("B2B SaaS for dentists in Germany")
        assert _chunks("B2B SaaS for dentists in Germany") == [
            ("core", ["b2b", "saas"]),
            ("qualifier", ["dentists"]),
            ("qualifier", ["germany"]),
        ]
        assert p.core_tokens == ("b2b", "saas")
        assert p.qualifier_tokens == ("dentists", "germany")

    def test_long_core(self):
        p = parse_icp("renewable energy project developers in DACH")
        assert p.core_tokens == ("renewable", "energy", "project", "developers")
        assert p.qualifier_tokens == ("dach",)

    def test_hyphenated_token_preserved(self):
        p = parse_icp("e-commerce stores")
        assert p.core_tokens == ("e-commerce", "stores")

    def test_generic_token_stays_in_phrase_but_not_required(self):
        p = parse_icp("software consultancy")
        assert [c.tokens for c in p.chunks] == [("software", "consultancy")]
        assert p.core_tokens == ("consultancy",)
        assert p.core_phrases == (("software", "consultancy"),)

    def test_empty_and_junk(self):
        assert parse_icp("").chunks == ()
        assert parse_icp("for the and of").chunks == ()


class TestPhraseHit:
    def _hit(self, tokens, text):
        return phrase_hit(tuple(tokens), text_words(text))

    def test_adjacent(self):
        assert self._hit(["sustainability", "consultancy"],
                         "We are a sustainability consultancy in Utrecht.")

    def test_morphology_inside_phrase(self):
        # "mills" stems to "mill"
        assert self._hit(["paper", "mill"], "One of Europe's largest paper mills.")

    def test_gap_window_allows_two_words(self):
        assert self._hit(["health", "safety", "consultants"],
                         "health and safety consultants for industry")
        assert self._hit(["timber", "merchants"], "timber and wood merchants")

    def test_gap_window_rejects_far_apart(self):
        assert not self._hit(
            ["sustainability", "consultancy"],
            "sustainability is our passion; we also run a consultancy division",
        )

    def test_hyphen_and_slug_text(self):
        assert self._hit(["sustainability", "consulting"],
                         "see /services/sustainability-consulting/ for details")

    def test_compound_concatenation(self):
        assert self._hit(["paper", "mill"], "the papermill has run since 1900")
        assert self._hit(["paper", "mill"], "two papermills in Finland")
        assert self._hit(["saw", "mill"], "a family sawmill")

    def test_no_hit(self):
        assert not self._hit(["paper", "mill"], "a steel mill near the paper museum is far away")
        assert not self._hit(["paper", "mill"], "")


class TestTokenEvidenced:
    def _ev(self, token, text, derived=None):
        words = text_words(text)
        return token_evidenced(token, set(words), {stem(w) for w in words},
                               text.lower(), derived)

    def test_stem_match(self):
        assert self._ev("consultancy", "consultancy services since 1990")
        assert self._ev("landscape", "we do landscaping")

    def test_substring_for_long_tokens(self):
        assert self._ev("tech", "a fintech scale-up")

    def test_short_token_needs_whole_word(self):
        assert not self._ev("ai", "maintain our chains")   # no substring leak
        assert self._ev("ai", "an AI lab")

    def test_singular_fallback_for_acronym_plural(self):
        # _stem can't reduce "smes" (needs >=4 remaining chars); the bare-plural
        # fallback matches the singular form in text.
        assert self._ev("smes", "we help every SME grow")

    def test_derived_terms(self):
        assert self._ev("sustainability", "our ESG consultants", derived={"esg"})
        assert self._ev("consultancy", "advisory for industry", derived={"advisory"})
        assert not self._ev("sustainability", "general business advice", derived={"esg"})

    def test_derived_multiword_phrase_substring(self):
        assert self._ev("waste", "expert en gestion des déchets",
                        derived={"gestion des déchets"})


class TestEvidenceCore:
    ICP = "Sustainability Consultancy for SMEs"

    def test_phrase_hit_confirms(self):
        core = evidence_core(parse_icp(self.ICP),
                             "A sustainability consultancy serving Dutch SMEs.")
        assert core.confirmed
        assert core.phrase_chunks == (("sustainability", "consultancy"),)
        assert core.matched_qualifiers == ("smes",)

    def test_cooccurrence_via_provenance_confirms(self):
        # "ESG" evidences sustainability, "consulting" evidences consultancy —
        # no adjacent phrase, but every core token is covered.
        core = evidence_core(
            parse_icp(self.ICP),
            "We provide ESG strategy and management consulting.",
            provenance={"sustainability": {"esg"}, "consultancy": {"consulting"}},
        )
        assert core.confirmed
        assert core.phrase_chunks == ()
        assert core.evidenced == {"sustainability", "consultancy"}

    def test_partial_core_not_confirmed(self):
        # The consultancy.eu case: consulting morphology everywhere, zero
        # sustainability evidence.
        core = evidence_core(
            parse_icp(self.ICP),
            "The online platform for the consulting industry: news, consultancy "
            "rankings, consultants and advisory jobs.",
            provenance={"consultancy": {"consulting", "advisory", "consultant"}},
        )
        assert not core.confirmed
        assert core.evidenced == {"consultancy"}

    def test_qualifier_only_not_confirmed(self):
        core = evidence_core(parse_icp(self.ICP), "Services for SMEs across Europe.")
        assert not core.confirmed
        assert core.evidenced == set()
        assert core.matched_qualifiers == ("smes",)

    def test_native_compound_confirms_whole_chunk(self):
        # Whole-phrase translation attributed the Dutch compound to BOTH tokens.
        prov = {"sustainability": {"duurzaamheidsadvies"},
                "consultancy": {"duurzaamheidsadvies"}}
        core = evidence_core(parse_icp(self.ICP),
                             "Duurzaamheidsadvies voor het MKB.", provenance=prov)
        assert core.confirmed

    def test_single_token_core_behaves_like_today(self):
        core = evidence_core(parse_icp("Plumbing"), "emergency plumbing and heating")
        assert core.confirmed
        assert core.evidenced == {"plumbing"}

    def test_all_generic_core_never_confirms_here(self):
        core = evidence_core(parse_icp("software companies"),
                             "software companies directory")
        assert not core.confirmed      # legacy gate handles this case downstream
        assert core.required == frozenset()
