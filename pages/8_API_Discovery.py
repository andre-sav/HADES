"""
API Discovery - Query ZoomInfo API to discover available field names.
Useful for debugging and finding correct parameter names.
"""

import json
import streamlit as st

from errors import PipelineError
from zoominfo_client import get_zoominfo_client
from ui_components import inject_base_styles, page_header

st.set_page_config(page_title="API Discovery", page_icon="🔬", layout="wide")

# Apply design system styles
inject_base_styles()

page_header("API Field Discovery", "Query ZoomInfo API to discover available search and enrich field names")

st.markdown("---")

# List of potential lookup endpoints to try
LOOKUP_ENDPOINTS = [
    "/lookup/inputfields",
    "/lookup/outputfields",
    "/lookup/inputfields/contact",
    "/lookup/outputfields/contact",
    "/lookup/contact/inputfields",
    "/lookup/contact/outputfields",
    "/lookup",
    "/lookup/fields",
    "/lookup/search",
    "/lookup/enrich",
]

st.subheader("Try Lookup Endpoints")
st.caption("Attempting various endpoint paths to find available fields")

if st.button("🔍 Probe Lookup Endpoints", type="primary"):
    try:
        client = get_zoominfo_client()

        results = {}

        for endpoint in LOOKUP_ENDPOINTS:
            with st.spinner(f"Trying {endpoint}..."):
                try:
                    response = client._request("GET", endpoint)
                    results[endpoint] = {"status": "success", "data": response}
                    st.success(f"✅ {endpoint} - Success!")
                except PipelineError as e:
                    results[endpoint] = {"status": "error", "message": str(e.message)}
                    st.error(f"❌ {endpoint} - {e.message[:100]}")
                except Exception as e:
                    results[endpoint] = {"status": "error", "message": str(e)}
                    st.error(f"❌ {endpoint} - {str(e)[:100]}")

        # Show successful results
        st.markdown("---")
        st.subheader("Successful Endpoints")

        success_count = 0
        for endpoint, result in results.items():
            if result["status"] == "success":
                success_count += 1
                with st.expander(f"📗 {endpoint}"):
                    st.json(result["data"])

        if success_count == 0:
            st.warning("No lookup endpoints found. The API may require different paths.")

    except PipelineError as e:
        st.error(f"Failed to connect to ZoomInfo: {e.user_message}")
    except Exception as e:
        st.error("Failed to connect to ZoomInfo. Check application logs.")

st.markdown("---")

# Minimal contact search test
st.subheader("Test Minimal Contact Search")
st.caption("Try a minimal search request to see what parameters work")

test_state = st.text_input("State", value="TX")
test_zip = st.text_input("ZIP Code", value="75201")

if st.button("🧪 Test Minimal Search"):
    try:
        client = get_zoominfo_client()

        # Try the most minimal request possible - API expects comma-separated strings
        minimal_request = {
            "state": test_state,  # String, not array
            "locationSearchType": "PersonAndHQ",
        }
        query_params = {
            "page[size]": 1,
            "page[number]": 1,
        }

        st.markdown("**Request Body:**")
        st.code(json.dumps(minimal_request, indent=2), language="json")
        st.markdown("**Query Params:**")
        st.code(json.dumps(query_params, indent=2), language="json")

        with st.spinner("Testing minimal search..."):
            try:
                response = client._request("POST", "/search/contact", json=minimal_request, params=query_params)
                st.success("✅ Minimal search succeeded!")
                st.json(response)
            except PipelineError as e:
                st.error(f"❌ Failed: {e.message}")

                # If that failed, try with just zipCode
                st.markdown("---")
                st.markdown("**Trying with zipCode instead...**")

                minimal_request_2 = {
                    "zipCode": test_zip,  # String, not array
                    "locationSearchType": "PersonAndHQ",
                }
                st.markdown("**Request Body:**")
                st.code(json.dumps(minimal_request_2, indent=2), language="json")

                try:
                    response = client._request("POST", "/search/contact", json=minimal_request_2, params=query_params)
                    st.success("✅ ZIP code search succeeded!")
                    st.json(response)
                except PipelineError as e2:
                    st.error(f"❌ Also failed: {e2.user_message}")

    except PipelineError as e:
        st.error(f"Connection error: {e.user_message}")
    except Exception as e:
        st.error("Connection error. Check application logs.")

st.markdown("---")
st.caption("💡 Use this page to discover the correct field names for the ZoomInfo API.")
