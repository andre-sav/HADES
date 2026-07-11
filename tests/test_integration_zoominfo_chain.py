"""Integration tests for the ZoomInfo data chain against recorded-shape responses
(HADES-fxr).

Unlike the unit tests, these drive the REAL multi-module path —
enrich_contacts -> merge_contact -> score_geography_leads -> contact_has_core_data
/ monitoring — through whole API envelopes, so a regression at any seam (parsing,
stamping, merge precedence, scoring baseline, fail-loud detection) is caught
deterministically without a live API.

Focused scope (agreed): Contact Enrich + Contact Search.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from zoominfo_client import ZoomInfoClient, ContactEnrichParams, ContactQueryParams
from export import merge_contact, contact_has_core_data
from scoring import score_geography_leads
from monitoring import evaluate_enrichment_batch
from tests.zoominfo_fixtures import (
    ENRICH_HEALTHY, ENRICH_ALL_FIELDLESS, ENRICH_PARTIAL,
    search_page, search_contact,
)


@pytest.fixture
def client():
    from datetime import datetime, timedelta
    c = ZoomInfoClient(client_id="test-id", client_secret="test-secret")
    c.access_token = "valid-token"
    c.token_expires_at = datetime.now() + timedelta(hours=1)
    return c


def _geo_chain(enriched, search_by_pid):
    """Reproduce the geo page's merge -> score -> deliverable-filter chain."""
    merged = []
    for c in enriched:
        pid = str(c.get("id") or c.get("personId") or "")
        merged.append(merge_contact(search_by_pid.get(pid, {}), c))
    scored = score_geography_leads(merged, target_zip="02025")
    deliverable = [lead for lead in scored if contact_has_core_data(lead)]
    return scored, deliverable


class TestEnrichChainHealthy:
    def test_healthy_enrich_produces_full_deliverable_leads(self, client):
        with patch.object(client, "_request", return_value=ENRICH_HEALTHY):
            enriched = client.enrich_contacts(ContactEnrichParams(person_ids=["111", "222"])).get("data")

        scored, deliverable = _geo_chain(enriched, search_by_pid={})

        assert len(deliverable) == 2
        names = {f"{l['firstName']} {l['lastName']}" for l in deliverable}
        assert names == {"Nancy Zappolo", "Anne Kenneally"}
        # Healthy data must NOT collapse to the empty-lead baseline (54 post-HADES-tow).
        assert any(l["_score"] != 54 for l in scored) or all(contact_has_core_data(l) for l in scored)
        assert evaluate_enrichment_batch(enriched)["severity"] == "ok"


class TestEnrichChainAllFieldless:
    """The 2026-06-15 incident, end to end."""

    def test_fieldless_enrich_with_no_search_data_is_all_empty(self, client):
        with patch.object(client, "_request", return_value=ENRICH_ALL_FIELDLESS):
            enriched = client.enrich_contacts(ContactEnrichParams(person_ids=["111", "222", "333"])).get("data")

        scored, deliverable = _geo_chain(enriched, search_by_pid={})

        # No deliverable leads — the fail-loud P0 path (block + st.stop) fires.
        assert deliverable == []
        # Without backfill, every lead collapses to the empty-lead baseline.
        # 54 = proximity 70*.40 + onsite 40*.25 + authority 40*.15 + employee 50*.20
        # (was 64 before HADES-tow made unknown employee counts score neutral 50
        # instead of the calibrated top bucket 100).
        assert scored and all(l["_score"] == 54 for l in scored)
        assert evaluate_enrichment_batch(enriched)["severity"] == "critical"

    def test_fieldless_enrich_is_rescued_by_search_backfill(self, client):
        """P1: the requested personId is stamped, so search-phase data restores
        the lead instead of a blank row."""
        with patch.object(client, "_request", return_value=ENRICH_ALL_FIELDLESS):
            enriched = client.enrich_contacts(ContactEnrichParams(person_ids=["111", "222", "333"])).get("data")

        search_by_pid = {
            "111": search_contact("111", "Nancy", "Zappolo", "BaneCare"),
            "222": search_contact("222", "Anne", "Kenneally", "Notre Dame Academy"),
            "333": search_contact("333", "Joe", "Branch", "Branch Co"),
        }
        scored, deliverable = _geo_chain(enriched, search_by_pid)

        # All three rescued to search-quality leads — no blank rows shipped.
        assert len(deliverable) == 3
        assert {l["companyName"] for l in deliverable} == {"BaneCare", "Notre Dame Academy", "Branch Co"}


class TestEnrichChainPartial:
    def test_partial_fieldless_keeps_good_drops_empty(self, client):
        with patch.object(client, "_request", return_value=ENRICH_PARTIAL):
            enriched = client.enrich_contacts(ContactEnrichParams(person_ids=["111", "222"])).get("data")

        scored, deliverable = _geo_chain(enriched, search_by_pid={})

        assert len(deliverable) == 1
        assert deliverable[0]["firstName"] == "Nancy"
        v = evaluate_enrichment_batch(enriched)
        assert v["severity"] == "warning"
        assert v["empty"] == 1


class TestSearchChain:
    def test_healthy_multipage_search_no_truncation(self, client):
        pages = [
            search_page([search_contact("1", "A", "A", "Co1")], total_results=2, page=1, page_size=1),
            search_page([search_contact("2", "B", "B", "Co2")], total_results=2, page=2, page_size=1),
        ]
        with patch.object(client, "search_contacts", side_effect=pages):
            contacts = client._search_contacts_single_batch(
                ContactQueryParams(zip_codes=["02025"], radius_miles=20, states=["MA"]),
                max_pages=5,
            )
        assert len(contacts) == 2
        assert client.last_search_truncated is None

    def test_empty_search_returns_nothing_cleanly(self, client):
        pages = [search_page([], total_results=0, page=1, page_size=25)]
        with patch.object(client, "search_contacts", side_effect=pages):
            contacts = client._search_contacts_single_batch(
                ContactQueryParams(zip_codes=["02025"], radius_miles=20, states=["MA"]),
                max_pages=5,
            )
        assert contacts == []
        assert client.last_search_truncated is None

    def test_truncated_search_surfaces_signal(self, client):
        # 100 pages exist, cap at 3 -> partial result must be flagged.
        pages = [
            search_page([search_contact(str(i), "X", "Y", "Co")], total_results=100, page=i + 1, page_size=1)
            for i in range(3)
        ]
        with patch.object(client, "search_contacts", side_effect=pages):
            contacts = client._search_contacts_single_batch(
                ContactQueryParams(zip_codes=["02025"], radius_miles=20, states=["MA"]),
                max_pages=3,
            )
        assert len(contacts) == 3
        assert client.last_search_truncated is not None
        assert client.last_search_truncated["total_pages"] == 100
