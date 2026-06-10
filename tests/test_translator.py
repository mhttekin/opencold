"""Tests for the keyless translator: dead-instance memory, walk budget, fallbacks.

The whole public Lingva pool has been observed dead at once (500s, 403/404,
NXDOMAIN). These tests pin the behaviour that keeps discovery responsive in that
world: a failed instance is skipped on later calls, one call's walk is bounded,
and the MyMemory fallback never caches its own quota-warning text as a
translation.
"""

import json
from unittest.mock import patch

import pytest

from opencold import translator


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Isolate the process-lifetime cache and instance cooldowns per test."""
    monkeypatch.setattr(translator, "_CACHE", {})
    monkeypatch.setattr(translator, "_SKIP_UNTIL", {})


def _lingva_urls(calls):
    return [u for u in calls if "mymemory" not in u]


def _mymemory_urls(calls):
    return [u for u in calls if "mymemory" in u]


class TestDeadInstanceMemory:
    def test_failed_instances_skipped_on_later_calls(self):
        calls = []

        def fake_get(url, timeout=translator._TIMEOUT):
            calls.append(url)
            return None  # every provider down

        with patch.object(translator, "_get", side_effect=fake_get):
            assert translator.translate("timber", "pl", source="en") == "timber"
            first_walk = len(_lingva_urls(calls))
            assert first_walk == len(translator._LINGVA_INSTANCES)

            # A NEW text must not re-walk the dead pool — straight to MyMemory.
            assert translator.translate("plywood", "pl", source="en") == "plywood"
            assert len(_lingva_urls(calls)) == first_walk
            assert len(_mymemory_urls(calls)) == 2

    def test_cooldown_expiry_reenables_instance(self):
        calls = []

        def fake_get(url, timeout=translator._TIMEOUT):
            calls.append(url)
            return None

        now = translator.time.monotonic()
        # All instances cooling except one whose cooldown has lapsed.
        for inst in translator._LINGVA_INSTANCES:
            translator._SKIP_UNTIL[inst] = now + 600
        lapsed = translator._LINGVA_INSTANCES[0]
        translator._SKIP_UNTIL[lapsed] = now - 1

        with patch.object(translator, "_get", side_effect=fake_get):
            translator.translate("timber", "pl", source="en")
        assert _lingva_urls(calls) == [f"{lapsed}/api/v1/en/pl/timber"]
        # ... and it failed again, so it went back on cooldown.
        assert translator._SKIP_UNTIL[lapsed] > now

    def test_success_clears_cooldown_and_stops_walk(self):
        calls = []

        def fake_get(url, timeout=translator._TIMEOUT):
            calls.append(url)
            return json.dumps({"translation": "drewno"})

        with patch.object(translator, "_get", side_effect=fake_get):
            assert translator.translate("timber", "pl", source="en") == "drewno"
        assert len(calls) == 1
        assert translator._SKIP_UNTIL == {}

    def test_garbage_response_marks_instance(self):
        """An instance serving non-JSON (HTML error page behind a 200) is as dead
        as one that times out."""
        calls = []

        def fake_get(url, timeout=translator._TIMEOUT):
            calls.append(url)
            return "<html>borked</html>" if "mymemory" not in url else None

        with patch.object(translator, "_get", side_effect=fake_get):
            translator.translate("timber", "pl", source="en")
        assert set(translator._SKIP_UNTIL) == set(translator._LINGVA_INSTANCES)


class TestWalkBudget:
    def test_walk_stops_once_budget_spent(self, monkeypatch):
        clock = {"t": 1000.0}
        monkeypatch.setattr(translator.time, "monotonic", lambda: clock["t"])
        calls = []

        def slow_get(url, timeout=translator._TIMEOUT):
            calls.append(url)
            clock["t"] += 5.0  # each attempt slower than _TIMEOUT bounds (DNS hang)
            return None

        with patch.object(translator, "_get", side_effect=slow_get):
            translator._lingva("timber", "pl", "en")
        # 8s budget / 5s per attempt -> the walk stops after the second attempt.
        assert len(calls) == 2


class TestMyMemoryFallback:
    def test_serves_translation_when_lingva_pool_is_dead(self):
        def fake_get(url, timeout=translator._TIMEOUT):
            if "mymemory" in url:
                return json.dumps(
                    {"responseStatus": 200,
                     "responseData": {"translatedText": "drewno"}})
            return None

        with patch.object(translator, "_get", side_effect=fake_get):
            assert translator.translate("timber", "pl", source="en") == "drewno"

    def test_quota_warning_is_not_a_translation(self):
        def fake_get(url, timeout=translator._TIMEOUT):
            if "mymemory" in url:
                return json.dumps(
                    {"responseStatus": "403",
                     "responseData": {"translatedText":
                                      "MYMEMORY WARNING: YOU USED ALL AVAILABLE "
                                      "FREE TRANSLATIONS FOR TODAY"}})
            return None

        with patch.object(translator, "_get", side_effect=fake_get):
            assert translator.translate("timber", "pl", source="en") == "timber"
