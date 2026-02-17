"""
Pipeline Test - Verify the full ZoomInfo pipeline works end-to-end.
Searches for 1 contact, enriches it (1 credit), scores, and exports.
"""

import json
from datetime import datetime

import streamlit as st
import pandas as pd

from errors import PipelineError
from zoominfo_client import (
    get_zoominfo_client,
    ContactQueryParams,
    DEFAULT_ENRICH_OUTPUT_FIELDS,
)
from scoring import score_geography_leads, get_priority_label
from export import export_leads_to_csv
from utils import get_sic_codes, get_employee_minimum, get_employee_maximum
from geo import get_zips_in_radius, get_states_from_zips
from cost_tracker import CostTracker
from turso_db import get_database
from ui_components import inject_base_styles, page_header, step_indicator

st.set_page_config(page_title="Pipeline Test", page_icon="🧪", layout="wide")

# Apply design system styles
inject_base_styles()

page_header("Pipeline Test", "Verify the full ZoomInfo pipeline with a single contact (1 credit)")

# --- Session State ---
if "test_request_confirmed" not in st.session_state:
    st.session_state.test_request_confirmed = False
if "test_search_request" not in st.session_state:
    st.session_state.test_search_request = None
if "test_params" not in st.session_state:
    st.session_state.test_params = None

st.markdown("---")

# --- Test Configuration ---
st.subheader("1. Test Configuration")

col1, col2 = st.columns(2)

with col1:
    test_zip = st.text_input(
        "Test ZIP Code",
        value="75201",  # Dallas downtown - good test location
        help="Center ZIP for the test search",
    )

with col2:
    test_radius = st.number_input(
        "Radius (miles)",
        min_value=5,
        max_value=25,
        value=15,
        help="Search radius",
    )

# Validate and calculate ZIPs
valid_config = False
zip_codes = []
states = []

if test_zip and len(test_zip) == 5 and test_zip.isdigit():
    calculated_zips = get_zips_in_radius(test_zip, test_radius)
    zip_codes = [z["zip"] for z in calculated_zips]
    states = get_states_from_zips(calculated_zips)
    valid_config = bool(zip_codes and states)

    st.success(f"📍 **{len(zip_codes)}** ZIP codes in radius  ·  States: {', '.join(states)}")
else:
    st.warning("Enter a valid 5-digit ZIP code")

st.markdown("---")

# --- Step 2: Review API Request ---
st.subheader("2. Review API Request")

if valid_config:
    # Build the exact request body that will be sent
    sic_codes = get_sic_codes()
    employee_min = get_employee_minimum()
    employee_max = get_employee_maximum()

    # Body params (per official docs)
    search_request_body = {
        "state": states,
        "zipCode": zip_codes,
        "locationSearchType": "PersonAndHQ",
        "employeeRangeMin": employee_min,
        "employeeRangeMax": employee_max,
        "sicCodes": sic_codes,
        "contactAccuracyScoreMin": 95,
        "excludePartialProfiles": True,
        "companyPastOrPresent": "present",
        "managementLevel": ["Manager"],
    }

    # Query params (pagination per official docs)
    query_params = {
        "page[size]": 10,
        "page[number]": 1,
        "sort": "contactAccuracyScore",
    }

    # Store for later use
    st.session_state.test_search_request = search_request_body
    st.session_state.test_query_params = query_params
    st.session_state.test_params = {
        "zip_codes": zip_codes,
        "states": states,
        "test_zip": test_zip,
        "test_radius": test_radius,
    }

    st.markdown("**POST** `https://api.zoominfo.com/search/contact`")

    # Show full request with truncated ZIP list for readability
    display_request = search_request_body.copy()
    if len(zip_codes) > 10:
        display_request["zipCode"] = display_request["zipCode"][:10]
        display_request["_note"] = f"Showing 10 of {len(zip_codes)} ZIP codes"

    st.markdown("**Request Body:**")
    st.code(json.dumps(display_request, indent=2), language="json")

    st.markdown("**Query Params:**")
    st.code(json.dumps(query_params, indent=2), language="json")

    if len(zip_codes) > 10:
        st.caption(f"Full request includes all {len(zip_codes)} ZIP codes")

    # Enrich request preview
    st.markdown("---")
    st.markdown("**POST** `https://api.zoominfo.com/enrich/contact` (after search)")

    enrich_preview = {
        "matchPersonInput": [{"personId": "<selected from search results>"}],
        "outputFields": DEFAULT_ENRICH_OUTPUT_FIELDS[:10] + ["..."],
        "_note": f"Full request includes {len(DEFAULT_ENRICH_OUTPUT_FIELDS)} output fields",
    }
    st.code(json.dumps(enrich_preview, indent=2), language="json")

    st.markdown("---")

    # Confirm and Send
    st.subheader("3. Confirm & Run Test")

    st.warning("⚡ This will use **1 ZoomInfo credit** for enrichment.")

    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button("✅ Confirm & Run Test", type="primary", use_container_width=True):
            st.session_state.test_request_confirmed = True
            st.rerun()

    with col2:
        if st.session_state.test_request_confirmed:
            if st.button("🔄 Reset", use_container_width=True):
                st.session_state.test_request_confirmed = False
                st.session_state.test_search_request = None
                st.session_state.test_params = None
                st.rerun()

else:
    st.info("Configure test parameters above to see the API request preview.")

# --- Execute Test (only after confirmation) ---
if st.session_state.test_request_confirmed and st.session_state.test_search_request:
    st.markdown("---")
    st.subheader("4. Test Execution")

    # Retrieve stored params
    params_data = st.session_state.test_params
    zip_codes = params_data["zip_codes"]
    states = params_data["states"]
    test_zip = params_data["test_zip"]
    test_radius = params_data["test_radius"]

    # Track results for each step
    results = {
        "auth": {"status": "pending", "message": "", "data": None},
        "search": {"status": "pending", "message": "", "data": None},
        "enrich": {"status": "pending", "message": "", "data": None},
        "score": {"status": "pending", "message": "", "data": None},
        "export": {"status": "pending", "message": "", "data": None},
    }

    # Progress container
    progress_container = st.container()

    with progress_container:
        # Step 1: Authentication
        with st.status("Step 1: Authenticating with ZoomInfo...", expanded=True) as status:
            try:
                client = get_zoominfo_client()
                # Force token refresh to verify credentials
                client._get_token()
                results["auth"] = {
                    "status": "pass",
                    "message": "Authentication successful",
                    "data": {"token_expires": str(client.token_expires_at)},
                }
                status.update(label="Step 1: Authentication ✅", state="complete")
            except PipelineError as e:
                results["auth"] = {
                    "status": "fail",
                    "message": f"Auth failed: {e.user_message}",
                    "data": None,
                }
                status.update(label="Step 1: Authentication ❌", state="error")
                st.error(f"Authentication failed: {e.user_message}")
                st.stop()
            except Exception as e:
                results["auth"] = {
                    "status": "fail",
                    "message": f"Unexpected error: {str(e)}",
                    "data": None,
                }
                status.update(label="Step 1: Authentication ❌", state="error")
                st.error(f"Authentication error: {str(e)}")
                st.stop()

        # Step 2: Contact Search (free - no credits)
        with st.status("Step 2: Searching for contacts (free)...", expanded=True) as status:
            try:
                params = ContactQueryParams(
                    zip_codes=zip_codes,
                    radius_miles=0,  # Explicit ZIP list
                    states=states,
                    location_type="PersonAndHQ",
                    employee_min=get_employee_minimum(),
                    sic_codes=get_sic_codes(),
                    company_past_or_present="present",
                    exclude_partial_profiles=True,
                    required_fields=["mobilePhone", "directPhone", "phone"],
                    required_fields_operator="or",
                    contact_accuracy_score_min=95,
                    exclude_org_exported=True,
                    management_levels=["Manager"],
                    page_size=10,  # Only need a few for test
                    page=1,
                )

                search_result = client.search_contacts(params)
                contacts = search_result.get("data", [])
                total = search_result.get("pagination", {}).get("totalResults", 0)

                if not contacts:
                    results["search"] = {
                        "status": "fail",
                        "message": "No contacts found. Try different parameters.",
                        "data": {"total": 0},
                    }
                    status.update(label="Step 2: Search ❌ (no results)", state="error")
                    st.error("No contacts found matching criteria. Try a different ZIP code or expand filters.")
                    st.stop()

                # Take the first contact (highest accuracy score due to sorting)
                test_contact = contacts[0]
                person_id = test_contact.get("personId") or test_contact.get("id")

                results["search"] = {
                    "status": "pass",
                    "message": f"Found {total} contacts, selected top result",
                    "data": {
                        "total_found": total,
                        "selected_person_id": person_id,
                        "selected_name": f"{test_contact.get('firstName', '')} {test_contact.get('lastName', '')}".strip(),
                        "selected_company": test_contact.get("companyName", ""),
                        "accuracy_score": test_contact.get("contactAccuracyScore", 0),
                    },
                }
                status.update(label=f"Step 2: Search ✅ ({total} found)", state="complete")

                st.markdown(f"""
                **Selected contact:** {results['search']['data']['selected_name']}
                **Company:** {results['search']['data']['selected_company']}
                **Accuracy:** {results['search']['data']['accuracy_score']}
                """)

            except PipelineError as e:
                results["search"] = {
                    "status": "fail",
                    "message": e.user_message,
                    "data": None,
                }
                status.update(label="Step 2: Search ❌", state="error")
                st.error(f"Search failed: {e.user_message}")
                st.stop()
            except Exception as e:
                results["search"] = {
                    "status": "fail",
                    "message": str(e),
                    "data": None,
                }
                status.update(label="Step 2: Search ❌", state="error")
                st.error(f"Search error: {str(e)}")
                st.stop()

        # Step 3: Enrich (uses 1 credit)
        with st.status("Step 3: Enriching contact (1 credit)...", expanded=True) as status:
            try:
                enriched_list = client.enrich_contacts_batch(
                    person_ids=[person_id],
                    output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
                )

                if not enriched_list:
                    results["enrich"] = {
                        "status": "fail",
                        "message": "Enrichment returned no data",
                        "data": None,
                    }
                    status.update(label="Step 3: Enrich ❌ (no data)", state="error")
                    st.error("Enrichment returned no data for this contact.")
                    st.stop()

                enriched_contact = enriched_list[0]

                # Handle case where response might not be a dict
                if isinstance(enriched_contact, str):
                    st.warning(f"Unexpected response format: {enriched_contact[:200]}")
                    enriched_contact = {"_raw": enriched_contact}

                # Count populated fields
                populated_fields = sum(1 for v in enriched_contact.values() if v) if isinstance(enriched_contact, dict) else 0

                results["enrich"] = {
                    "status": "pass",
                    "message": f"Enriched with {populated_fields} fields",
                    "data": enriched_contact,
                }
                status.update(label=f"Step 3: Enrich ✅ ({populated_fields} fields)", state="complete")

                # Show key enriched fields
                st.markdown(f"""
                **Name:** {enriched_contact.get('firstName', '')} {enriched_contact.get('lastName', '')}
                **Title:** {enriched_contact.get('jobTitle', 'N/A')}
                **Company:** {enriched_contact.get('companyName', 'N/A')}
                **Phone:** {enriched_contact.get('directPhone', '') or enriched_contact.get('mobilePhone', '') or enriched_contact.get('phone', 'N/A')}
                **Email:** {enriched_contact.get('email', 'N/A')}
                **City/State:** {enriched_contact.get('city', '')}, {enriched_contact.get('state', '')}
                """)

                # Log usage to internal tracking
                try:
                    db = get_database()
                    tracker = CostTracker(db)
                    query_params = {
                        "zip": st.session_state.test_params.get("test_zip", ""),
                        "radius": st.session_state.test_params.get("test_radius", 0),
                        "states": st.session_state.test_params.get("states", []),
                    }
                    tracker.log_usage(
                        workflow_type="geography",  # Count as geography for tracking
                        query_params=query_params,
                        credits_used=1,  # Pipeline test uses 1 credit
                        leads_returned=1,
                    )
                    # log_query signature: (workflow_type, query_params, leads_returned, leads_exported=0)
                    db.log_query(
                        workflow_type="geography",
                        query_params=query_params,
                        leads_returned=1,
                    )
                except Exception as log_err:
                    st.warning(f"Usage logging failed: {log_err}")

            except PipelineError as e:
                results["enrich"] = {
                    "status": "fail",
                    "message": e.user_message,
                    "data": None,
                }
                status.update(label="Step 3: Enrich ❌", state="error")
                st.error(f"Enrichment failed: {e.user_message}")
                st.stop()
            except Exception as e:
                results["enrich"] = {
                    "status": "fail",
                    "message": str(e),
                    "data": None,
                }
                status.update(label="Step 3: Enrich ❌", state="error")
                st.error(f"Enrichment error: {str(e)}")
                st.stop()

        # Step 4: Scoring
        with st.status("Step 4: Scoring contact...", expanded=True) as status:
            try:
                scored_leads = score_geography_leads([enriched_contact], target_zip=test_zip)
                scored_contact = scored_leads[0]

                score = scored_contact.get("_score", 0)
                priority = get_priority_label(score)

                # Add metadata
                scored_contact["_lead_source"] = f"Pipeline Test · {test_zip} · {test_radius}mi"
                scored_contact["_priority"] = priority

                results["score"] = {
                    "status": "pass",
                    "message": f"Score: {score}, Priority: {priority}",
                    "data": {"score": score, "priority": priority},
                }
                status.update(label=f"Step 4: Score ✅ ({score} - {priority})", state="complete")

                st.markdown(f"**Score:** {score}/100 → **{priority}** priority")

            except Exception as e:
                results["score"] = {
                    "status": "fail",
                    "message": str(e),
                    "data": None,
                }
                status.update(label="Step 4: Score ❌", state="error")
                st.error(f"Scoring error: {str(e)}")
                st.stop()

        # Step 5: Export (generate CSV)
        with st.status("Step 5: Generating VanillaSoft CSV...", expanded=True) as status:
            try:
                # Create test operator for export
                test_operator = {
                    "operator_name": "Test Operator",
                    "vending_business_name": "Pipeline Test",
                    "operator_phone": "",
                    "operator_email": "",
                    "operator_zip": test_zip,
                    "operator_website": "",
                    "team": "Test",
                }

                csv_content, _ = export_leads_to_csv([scored_contact], test_operator, workflow_type="test")

                # Count lines (header + data)
                csv_lines = csv_content.strip().split("\n")

                results["export"] = {
                    "status": "pass",
                    "message": f"Generated CSV with {len(csv_lines)} lines",
                    "data": {"csv_content": csv_content, "lines": len(csv_lines)},
                }
                status.update(label=f"Step 5: Export ✅ ({len(csv_lines)} lines)", state="complete")

                st.markdown(f"**CSV generated:** {len(csv_lines)} lines (header + 1 contact)")

            except Exception as e:
                results["export"] = {
                    "status": "fail",
                    "message": str(e),
                    "data": None,
                }
                status.update(label="Step 5: Export ❌", state="error")
                st.error(f"Export error: {str(e)}")
                st.stop()

    # --- Final Summary ---
    st.markdown("---")
    st.subheader("Test Results")

    # Count passes/fails
    passes = sum(1 for r in results.values() if r["status"] == "pass")
    fails = sum(1 for r in results.values() if r["status"] == "fail")

    if fails == 0:
        st.success(f"🎉 **All {passes} steps passed!** Pipeline is working correctly.")
    else:
        st.error(f"❌ **{fails} step(s) failed.** See details above.")

    # Results table
    results_df = pd.DataFrame([
        {
            "Step": step.title(),
            "Status": "✅ Pass" if r["status"] == "pass" else "❌ Fail",
            "Message": r["message"],
        }
        for step, r in results.items()
    ])

    st.dataframe(results_df, use_container_width=True, hide_index=True)

    # Download options
    if results["export"]["status"] == "pass":
        st.markdown("---")
        st.subheader("Download Test Results")

        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                "📥 Download Test CSV",
                data=results["export"]["data"]["csv_content"],
                file_name=f"pipeline_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with col2:
            # Full enriched contact as JSON for debugging
            st.download_button(
                "📥 Download Raw JSON",
                data=json.dumps(enriched_contact, indent=2, default=str),
                file_name=f"pipeline_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )

    # Show raw enriched data in expander
    if results["enrich"]["status"] == "pass":
        with st.expander("Raw Enriched Contact Data"):
            st.json(results["enrich"]["data"])

st.markdown("---")
st.caption("💡 This test uses real ZoomInfo API calls. Each run consumes 1 credit for enrichment.")
