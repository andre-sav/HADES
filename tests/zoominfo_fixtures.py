"""Recorded-shape ZoomInfo API response fixtures (HADES-fxr).

These mirror the real ZoomInfo response envelopes so integration tests can drive
the full extract -> merge -> score -> filter chain against healthy AND degraded
inputs deterministically, with no live API. The degraded shapes are the ones
this hardening campaign exists for — especially the matched-but-fieldless enrich
payload that caused the 2026-06-15 blank-leads incident.

Shapes are taken from the live envelopes already exercised in
tests/test_zoominfo_client.py:
  enrich:  {"success": [...], "data": {"result": [{"input", "data": [contact], "matchStatus"}], ...}}
  search:  {"data": [contact, ...], "totalResults": N}
"""

from __future__ import annotations


# --------------------------------------------------------------------------- #
# Contact Enrich (/enrich/contact)
# --------------------------------------------------------------------------- #

def enrich_response(contacts_by_pid: dict[str, dict | None]) -> dict:
    """Build an enrich envelope.

    contacts_by_pid maps requested personId -> the contact dict to return in
    data[0], or None to simulate a matched-but-FIELDLESS payload (data: [{}]),
    the incident signature.
    """
    result = []
    success = []
    for pid, contact in contacts_by_pid.items():
        success.append({"personId": pid})
        result.append({
            "input": {"personId": pid},
            "data": [contact if contact is not None else {}],
            "matchStatus": "FULL_MATCH",
        })
    return {
        "success": success,
        "noMatch": [],
        "data": {"outputFields": [], "result": result, "requiredFields": []},
    }


def healthy_contact(pid: str, first: str, last: str, company: str, **extra) -> dict:
    base = {
        "id": int(pid) if pid.isdigit() else pid,
        "firstName": first,
        "lastName": last,
        "companyName": company,
        "email": f"{first.lower()}@{company.lower().replace(' ', '')}.com",
        "phone": "(781) 555-0100",
        "jobTitle": "VP Operations",
        "contactAccuracyScore": 95,
        "companyId": "co" + pid,
    }
    base.update(extra)
    return base


# Canonical fixtures -------------------------------------------------------- #

ENRICH_HEALTHY = enrich_response({
    "111": healthy_contact("111", "Nancy", "Zappolo", "BaneCare"),
    "222": healthy_contact("222", "Anne", "Kenneally", "Notre Dame Academy"),
})

# The incident: every match returns an empty data[0].
ENRICH_ALL_FIELDLESS = enrich_response({"111": None, "222": None, "333": None})

# Partial degradation: one good, one fieldless.
ENRICH_PARTIAL = enrich_response({
    "111": healthy_contact("111", "Nancy", "Zappolo", "BaneCare"),
    "222": None,
})


# --------------------------------------------------------------------------- #
# Contact Search (/search/contact) — per-page envelopes
# --------------------------------------------------------------------------- #

def search_page(contacts: list[dict], total_results: int, page: int, page_size: int) -> dict:
    total_pages = (total_results + page_size - 1) // page_size if total_results else 1
    return {
        "data": contacts,
        "pagination": {
            "totalResults": total_results,
            "pageSize": page_size,
            "currentPage": page,
            "totalPages": total_pages,
        },
    }


def search_contact(pid: str, first: str, last: str, company: str) -> dict:
    return {
        "personId": pid,
        "id": pid,
        "firstName": first,
        "lastName": last,
        "companyName": company,
        "personCity": "Scituate",
        "personState": "MA",
        "companyId": "co" + pid,
        "contactAccuracyScore": 95,
    }
