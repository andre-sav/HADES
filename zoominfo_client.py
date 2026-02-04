"""
ZoomInfo API client with OAuth authentication, rate limiting, and error handling.
"""

import logging
import time
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests
import streamlit as st

from utils import get_sic_codes, get_employee_minimum, get_employee_maximum

# Configure logging
logger = logging.getLogger(__name__)

# Set up console handler if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ZoomInfoError(Exception):
    """Base exception for ZoomInfo API errors."""

    def __init__(self, message: str, user_message: str, recoverable: bool = True):
        self.message = message
        self.user_message = user_message
        self.recoverable = recoverable
        super().__init__(message)


class ZoomInfoAuthError(ZoomInfoError):
    """Authentication failed."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            user_message="ZoomInfo authentication failed. Please check your API credentials.",
            recoverable=False,
        )


class ZoomInfoRateLimitError(ZoomInfoError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(
            message=f"Rate limit exceeded. Retry after {retry_after} seconds.",
            user_message=f"ZoomInfo rate limit reached. Please wait {retry_after} seconds and try again.",
            recoverable=True,
        )


class ZoomInfoAPIError(ZoomInfoError):
    """General API error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(
            message=f"API error {status_code}: {message}",
            user_message=f"ZoomInfo API error: {message}",
            recoverable=status_code >= 500,
        )


@dataclass
class IntentQueryParams:
    """Parameters for Intent API query."""

    topics: list[str]
    signal_strengths: list[str] | None = None  # High, Medium, Low
    employee_min: int | None = None
    sic_codes: list[str] | None = None
    page_size: int = 100
    page: int = 1


@dataclass
class GeoQueryParams:
    """Parameters for Company Search (Geography) API query."""

    zip_codes: list[str]
    radius_miles: int
    employee_min: int | None = None
    sic_codes: list[str] | None = None
    page_size: int = 100
    page: int = 1


@dataclass
class ContactQueryParams:
    """Parameters for Contact Search API query."""

    zip_codes: list[str]
    radius_miles: int
    states: list[str]  # State codes (e.g., ["CA", "TX"]) - REQUIRED
    location_type: str = "PersonAndHQ"  # PersonAndHQ, PersonOrHQ, Person, HQ, PersonThenHQ
    employee_min: int | None = None
    employee_max: int | None = None  # None = use config default, explicit None after init = no max
    sic_codes: list[str] | None = None
    sort_by: str = "contactAccuracyScore"
    sort_order: str = "desc"
    page_size: int = 100
    page: int = 1
    # Quality filters
    company_past_or_present: str = "present"  # Only current employees
    exclude_partial_profiles: bool = True  # Better data quality
    required_fields: list[str] | None = None  # e.g., ["mobilePhone", "directPhone", "phone"]
    required_fields_operator: str = "or"  # "or" = any field, "and" = all fields
    contact_accuracy_score_min: int = 95  # Quality threshold (0-100)
    exclude_org_exported: bool = True  # Exclude contacts already exported by org
    # Job title/role filters
    management_levels: list[str] | None = None  # Valid: Manager, Director, VP Level Exec, C Level Exec, Board Member, Non Manager
    job_titles: list[str] | None = None  # Specific titles to search for


@dataclass
class ContactEnrichParams:
    """Parameters for Contact Enrich API query."""

    person_ids: list[str]  # List of personId values from search results
    output_fields: list[str] | None = None  # Fields to return (None = all available)


# Default output fields for contact enrichment - comprehensive list for VanillaSoft export
DEFAULT_ENRICH_OUTPUT_FIELDS = [
    # Identity
    "id",
    "firstName",
    "lastName",
    "middleName",
    "salutation",
    "suffix",
    # Contact info
    "email",
    "phone",
    # "directPhone",  # Requires additional subscription
    "mobilePhone",
    "externalUrls",
    # Job info
    "jobTitle",
    "jobFunction",
    "managementLevel",
    "contactAccuracyScore",
    # Location
    "street",
    "city",
    "state",
    "zipCode",
    "country",
    "personHasMoved",
    # Company info
    "companyId",
    "companyName",
    "companyPhone",
    "companyWebsite",
    "companyStreet",
    "companyCity",
    "companyState",
    "companyZipCode",
    "companyCountry",
    # Fields below require additional subscription:
    # "directPhone", "employeeCount", "revenue", "sicCode", "naicsCode", "industry"
]


class ZoomInfoClient:
    """
    ZoomInfo API client with authentication, rate limiting, and error handling.
    """

    BASE_URL = "https://api.zoominfo.com"
    TOKEN_URL = "https://api.zoominfo.com/authenticate"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None
        self._session = requests.Session()

    def _get_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        if self.access_token and self.token_expires_at:
            # Refresh 5 minutes before expiry
            if datetime.now() < self.token_expires_at - timedelta(minutes=5):
                return self.access_token

        self._authenticate()
        return self.access_token

    def _authenticate(self) -> None:
        """Obtain OAuth access token."""
        logger.info("Authenticating with ZoomInfo API...")
        try:
            response = self._session.post(
                self.TOKEN_URL,
                json={
                    "username": self.client_id,
                    "password": self.client_secret,
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code == 401:
                logger.error("Authentication failed: Invalid credentials")
                raise ZoomInfoAuthError("Invalid credentials")

            if response.status_code != 200:
                logger.error(f"Authentication failed: HTTP {response.status_code}")
                raise ZoomInfoAPIError(response.status_code, response.text)

            data = response.json()
            self.access_token = data.get("jwt")

            # Token typically valid for 1 hour
            expires_in = data.get("expiresIn", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            logger.info(f"Authentication successful. Token expires in {expires_in}s")

        except requests.RequestException as e:
            logger.error(f"Authentication connection error: {e}")
            raise ZoomInfoAuthError(f"Connection error: {str(e)}")

    def _request(
        self,
        method: str,
        endpoint: str,
        max_retries: int = 3,
        **kwargs,
    ) -> dict:
        """Make authenticated API request with retry logic."""
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        # Log request details
        request_body = kwargs.get("json", {})
        logger.info(f"API Request: {method} {endpoint}")
        if request_body:
            # Log key parameters without sensitive data
            log_body = {k: v for k, v in request_body.items() if k not in ["jwt", "password"]}
            logger.debug(f"Request body: {json.dumps(log_body, indent=2)}")

        last_error = None
        for attempt in range(max_retries):
            try:
                logger.debug(f"Attempt {attempt + 1}/{max_retries}")
                response = self._session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=60,
                    **kwargs,
                )

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited on {endpoint}. Retry after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise ZoomInfoRateLimitError(retry_after)

                # Handle auth errors
                if response.status_code == 401:
                    logger.warning(f"Auth error on {endpoint}, refreshing token (attempt {attempt + 1}/{max_retries})")
                    # Token might be expired, try to refresh
                    self._authenticate()
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    continue

                # Handle server errors with retry
                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code} on {endpoint} (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        # Exponential backoff
                        time.sleep(2**attempt)
                        continue
                    raise ZoomInfoAPIError(response.status_code, response.text)

                # Handle client errors
                if response.status_code >= 400:
                    logger.error(f"Client error {response.status_code} on {endpoint}: {response.text[:200]}")
                    raise ZoomInfoAPIError(response.status_code, response.text)

                # Success
                try:
                    result = response.json()
                except ValueError as json_err:
                    logger.error(f"Invalid JSON response from {endpoint}: {json_err}")
                    raise ZoomInfoAPIError(response.status_code, f"Invalid JSON response: {str(json_err)}")
                total_results = result.get("totalResults", len(result.get("data", [])))
                logger.info(f"API Response: {endpoint} -> HTTP {response.status_code}, {total_results} results")
                return result

            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Connection error on {endpoint}: {e} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise ZoomInfoAPIError(0, f"Connection error: {str(e)}")

        raise ZoomInfoAPIError(0, f"Max retries exceeded: {str(last_error)}")

    def search_intent(self, params: IntentQueryParams) -> dict:
        """
        Query Intent API for companies showing intent signals.

        Returns dict with 'data' (list of leads) and 'pagination' info.
        """
        logger.info(f"Intent Search: topics={params.topics}, page={params.page}")

        # Apply ICP filters if not specified
        employee_min = params.employee_min or get_employee_minimum()
        employee_max = get_employee_maximum()
        sic_codes = params.sic_codes or get_sic_codes()

        request_body = {
            "intentTopicList": params.topics,
            "companyEmployeeCount": {"min": employee_min, "max": employee_max},
            "sicCodeList": sic_codes,
            "rpp": params.page_size,
            "page": params.page,
        }

        # Add signal strength filter if specified
        if params.signal_strengths:
            request_body["intentSignalStrengthList"] = params.signal_strengths

        response = self._request("POST", "/intent/search", json=request_body)

        result = {
            "data": response.get("data", []),
            "pagination": {
                "totalResults": response.get("totalResults", 0),
                "pageSize": params.page_size,
                "currentPage": params.page,
                "totalPages": (response.get("totalResults", 0) + params.page_size - 1) // params.page_size,
            },
        }
        logger.info(f"Intent Search complete: {len(result['data'])} results on page {params.page}, {result['pagination']['totalResults']} total")
        return result

    def search_companies(self, params: GeoQueryParams) -> dict:
        """
        Query Company Search API for companies by location.

        Returns dict with 'data' (list of leads) and 'pagination' info.
        """
        logger.info(f"Company Search: {len(params.zip_codes)} ZIP(s), radius={params.radius_miles}mi, page={params.page}")

        # Apply ICP filters if not specified
        employee_min = params.employee_min or get_employee_minimum()
        employee_max = get_employee_maximum()
        sic_codes = params.sic_codes or get_sic_codes()

        request_body = {
            "locationSearchType": "radius",
            "zipCodeRadiusList": [
                {"zipCode": zip_code, "radius": params.radius_miles}
                for zip_code in params.zip_codes
            ],
            "companyEmployeeCount": {"min": employee_min, "max": employee_max},
            "sicCodeList": sic_codes,
            "rpp": params.page_size,
            "page": params.page,
        }

        response = self._request("POST", "/search/company", json=request_body)

        result = {
            "data": response.get("data", []),
            "pagination": {
                "totalResults": response.get("totalResults", 0),
                "pageSize": params.page_size,
                "currentPage": params.page,
                "totalPages": (response.get("totalResults", 0) + params.page_size - 1) // params.page_size,
            },
        }
        logger.info(f"Company Search complete: {len(result['data'])} results on page {params.page}, {result['pagination']['totalResults']} total")
        return result

    def search_intent_all_pages(
        self,
        params: IntentQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Fetch all pages of Intent API results.

        Args:
            params: Query parameters (not modified)
            max_pages: Maximum pages to fetch (safety limit)
            progress_callback: Optional callback(current_page, total_pages)

        Returns list of all leads across pages.
        """
        logger.info(f"Intent Search (all pages): topics={params.topics}, max_pages={max_pages}")
        all_leads = []
        current_page = 1

        while current_page <= max_pages:
            params.page = current_page
            result = self.search_intent(params)
            all_leads.extend(result["data"])

            if progress_callback:
                progress_callback(current_page, result["pagination"]["totalPages"])

            if current_page >= result["pagination"]["totalPages"]:
                break

            current_page += 1

        logger.info(f"Intent Search (all pages) complete: {len(all_leads)} total leads from {current_page} pages")
        return all_leads

    def search_companies_all_pages(
        self,
        params: GeoQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Fetch all pages of Company Search results.

        Args:
            params: Query parameters (not modified)
            max_pages: Maximum pages to fetch (safety limit)
            progress_callback: Optional callback(current_page, total_pages)

        Returns list of all leads across pages.
        """
        logger.info(f"Company Search (all pages): {len(params.zip_codes)} ZIP(s), max_pages={max_pages}")
        all_leads = []
        current_page = 1

        while current_page <= max_pages:
            params.page = current_page
            result = self.search_companies(params)
            all_leads.extend(result["data"])

            if progress_callback:
                progress_callback(current_page, result["pagination"]["totalPages"])

            if current_page >= result["pagination"]["totalPages"]:
                break

            current_page += 1

        logger.info(f"Company Search (all pages) complete: {len(all_leads)} total leads from {current_page} pages")
        return all_leads

    def search_contacts(self, params: ContactQueryParams) -> dict:
        """
        Query Contact Search API for contacts by location.

        Uses locationSearchType to filter contacts where both the contact's
        office AND company HQ match the location criteria.

        Returns dict with 'data' (list of contacts) and 'pagination' info.
        """
        logger.info(
            f"Contact Search: {len(params.zip_codes)} ZIP(s), radius={params.radius_miles}mi, "
            f"states={params.states}, page={params.page}"
        )
        logger.info(
            f"  Filters: accuracy>={params.contact_accuracy_score_min}, "
            f"mgmt_levels={params.management_levels}, exclude_exported={params.exclude_org_exported}"
        )

        # Apply ICP filters if not specified
        employee_min = params.employee_min or get_employee_minimum()
        # employee_max: None = use config, 0 = no max limit, other = use that value
        if params.employee_max is None:
            employee_max = get_employee_maximum()
        elif params.employee_max == 0:
            employee_max = None  # No max limit
        else:
            employee_max = params.employee_max
        sic_codes = params.sic_codes or get_sic_codes()

        # Build request body with correct ZoomInfo API field names
        # Based on official docs + API error feedback: fields expect comma-separated strings

        # ZoomInfo API limits zipCode to 500 characters (~80 ZIP codes max)
        zip_str = ",".join(params.zip_codes) if params.zip_codes else None
        if zip_str and len(zip_str) > 500:
            # Truncate to fit within limit (keep first ~80 ZIPs)
            max_zips = 80
            truncated_zips = params.zip_codes[:max_zips]
            zip_str = ",".join(truncated_zips)
            logger.warning(f"ZIP code list truncated from {len(params.zip_codes)} to {max_zips} (API 500 char limit)")

        request_body = {
            # Location filters - state satisfies locationSearchType dependency
            "state": ",".join(params.states) if params.states else None,
            "zipCode": zip_str,
            "locationSearchType": params.location_type,  # PersonAndHQ, PersonOrHQ, Person, HQ
        }
        # Remove None values
        request_body = {k: v for k, v in request_body.items() if v is not None}

        # Pagination goes in query params (per API docs)
        query_params = {
            "page[size]": params.page_size,
            "page[number]": params.page,
            "sort": params.sort_by,
        }

        # Add ZIP radius if searching with radius (not manual ZIP list)
        if params.radius_miles and params.radius_miles > 0:
            request_body["zipCodeRadiusMiles"] = params.radius_miles

        # Employee count filter - separate min/max fields (API expects strings)
        if employee_min:
            request_body["employeeRangeMin"] = str(employee_min)
        if employee_max:
            request_body["employeeRangeMax"] = str(employee_max)

        # Industry filter - SIC codes (comma-separated string)
        if sic_codes:
            request_body["sicCodes"] = ",".join(sic_codes)

        # Contact quality filters (API expects strings for numeric values)
        if params.contact_accuracy_score_min:
            request_body["contactAccuracyScoreMin"] = str(params.contact_accuracy_score_min)
        if params.exclude_partial_profiles:
            request_body["excludePartialProfiles"] = params.exclude_partial_profiles
        if params.company_past_or_present:
            request_body["companyPastOrPresent"] = params.company_past_or_present
        if params.required_fields:
            request_body["requiredFields"] = ",".join(params.required_fields)

        # Management level filter (comma-separated string)
        if params.management_levels:
            request_body["managementLevel"] = ",".join(params.management_levels)

        # Job titles filter (comma-separated string)
        if params.job_titles:
            request_body["jobTitle"] = ",".join(params.job_titles)

        response = self._request("POST", "/search/contact", json=request_body, params=query_params)

        result = {
            "data": response.get("data", []),
            "pagination": {
                "totalResults": response.get("totalResults", 0),
                "pageSize": params.page_size,
                "currentPage": params.page,
                "totalPages": (response.get("totalResults", 0) + params.page_size - 1) // params.page_size,
            },
        }
        logger.info(f"Contact Search complete: {len(result['data'])} results on page {params.page}, {result['pagination']['totalResults']} total")
        return result

    def search_contacts_all_pages(
        self,
        params: ContactQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Fetch all pages of Contact Search results.

        ZoomInfo API limits ZIP codes to 500 chars (~75 ZIPs). When more ZIPs are
        provided, we split into batches and combine results with deduplication.

        Args:
            params: Query parameters (not modified)
            max_pages: Maximum pages to fetch per batch (safety limit)
            progress_callback: Optional callback(current_page, total_pages)

        Returns list of all contacts across pages and batches (deduplicated by id).
        """
        # ZoomInfo API limits zipCode to ~500 chars. Split into batches if needed.
        MAX_ZIPS_PER_BATCH = 75
        zip_codes = params.zip_codes or []

        if len(zip_codes) > MAX_ZIPS_PER_BATCH:
            # Split into batches and search each
            logger.info(f"Contact Search (all pages): {len(zip_codes)} ZIPs exceeds {MAX_ZIPS_PER_BATCH}, splitting into batches")
            all_contacts_by_id = {}  # Dedupe across batches

            for batch_start in range(0, len(zip_codes), MAX_ZIPS_PER_BATCH):
                batch_zips = zip_codes[batch_start:batch_start + MAX_ZIPS_PER_BATCH]
                batch_num = (batch_start // MAX_ZIPS_PER_BATCH) + 1
                total_batches = (len(zip_codes) + MAX_ZIPS_PER_BATCH - 1) // MAX_ZIPS_PER_BATCH

                logger.info(f"Contact Search: Batch {batch_num}/{total_batches} with {len(batch_zips)} ZIPs")

                # Create params copy with batch ZIPs
                from dataclasses import replace
                batch_params = replace(params, zip_codes=batch_zips)

                batch_contacts = self._search_contacts_single_batch(batch_params, max_pages, progress_callback)

                # Dedupe by contact id
                for contact in batch_contacts:
                    contact_id = contact.get("id") or contact.get("personId")
                    if contact_id and contact_id not in all_contacts_by_id:
                        all_contacts_by_id[contact_id] = contact

            all_contacts = list(all_contacts_by_id.values())
            logger.info(f"Contact Search (all pages) complete: {len(all_contacts)} unique contacts from {total_batches} batches")
            return all_contacts
        else:
            # Single batch - use normal flow
            return self._search_contacts_single_batch(params, max_pages, progress_callback)

    def _search_contacts_single_batch(
        self,
        params: ContactQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Fetch all pages from a single ZIP batch.

        Internal method called by search_contacts_all_pages.
        """
        logger.info(f"Contact Search (batch): {len(params.zip_codes)} ZIP(s), states={params.states}, max_pages={max_pages}")
        all_contacts = []
        current_page = 1
        actual_page_size = None  # Track what ZoomInfo actually returns per page

        while current_page <= max_pages:
            params.page = current_page
            result = self.search_contacts(params)
            page_results = result["data"]
            results_count = len(page_results)

            all_contacts.extend(page_results)

            if progress_callback:
                progress_callback(current_page, result["pagination"]["totalPages"])

            # Track actual page size from first page (ZoomInfo may cap at 25)
            if actual_page_size is None and results_count > 0:
                actual_page_size = results_count
                logger.info(f"Contact Search: Detected actual page size: {actual_page_size}")

            # Stop if we got 0 results or fewer than the actual page size
            if results_count == 0:
                logger.info(f"Contact Search: Page {current_page} returned 0 results, end of results")
                break

            if actual_page_size and results_count < actual_page_size:
                logger.info(f"Contact Search: Page {current_page} returned {results_count} < {actual_page_size}, end of results")
                break

            # If we got a full page, there might be more - continue to next page
            current_page += 1

        logger.info(f"Contact Search (batch) complete: {len(all_contacts)} contacts from {current_page} pages")
        return all_contacts

    def search_contacts_one_per_company(
        self,
        params: ContactQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Fetch contacts and deduplicate to 1 per company.

        Since results are sorted by contactAccuracyScore desc, keeps the
        highest-scored contact for each company.

        Args:
            params: Query parameters (should have sort_by="contactAccuracyScore")
            max_pages: Maximum pages to fetch
            progress_callback: Optional callback(current_page, total_pages)

        Returns list of contacts, one per company (highest accuracy score).
        """
        logger.info("Contact Search (one per company): fetching and deduplicating...")
        all_contacts = self.search_contacts_all_pages(
            params, max_pages, progress_callback
        )

        # Deduplicate by company - keep first occurrence (highest score due to sorting)
        seen_companies: set[str] = set()
        unique_contacts = []

        for contact in all_contacts:
            company_id = contact.get("companyId") or contact.get("company", {}).get("id")
            if company_id and company_id not in seen_companies:
                seen_companies.add(company_id)
                unique_contacts.append(contact)

        logger.info(f"Contact Search (one per company) complete: {len(unique_contacts)} unique companies from {len(all_contacts)} total contacts")
        return unique_contacts

    def enrich_contacts(self, params: ContactEnrichParams) -> dict:
        """
        Enrich contacts by personId to get full contact data.

        This endpoint USES CREDITS - 1 credit per new contact enriched.
        Contacts enriched within the last 12 months are free to re-enrich.

        Args:
            params: Enrich parameters with person_ids and optional output_fields

        Returns:
            Dict with 'data' (list of enriched contacts) and 'success'/'error' info
        """
        logger.info(f"Contact Enrich: {len(params.person_ids)} contacts (USES CREDITS)")
        output_fields = params.output_fields or DEFAULT_ENRICH_OUTPUT_FIELDS

        request_body = {
            "matchPersonInput": [
                {"personId": str(pid)} for pid in params.person_ids
            ],
            "outputFields": output_fields,  # Keep as array - API requires array format
        }
        logger.debug(f"Enrich request body: {request_body}")

        response = self._request("POST", "/enrich/contact", json=request_body)

        # Debug: log full response structure
        logger.info(f"Enrich raw response keys: {list(response.keys())}")
        raw_data = response.get("data", [])
        logger.info(f"Enrich response data type: {type(raw_data)}")

        # Normalize to list of contacts
        # ZoomInfo enrich response structure:
        # - raw_data is a list of {input, data, matchStatus} objects
        # - Each item's "data" field contains a list with the actual contact
        contacts = []

        if isinstance(raw_data, list):
            logger.info(f"Enrich response: list of {len(raw_data)} items")
            for item in raw_data:
                if isinstance(item, dict):
                    # Extract contact from item["data"][0] structure
                    if "data" in item and isinstance(item["data"], list) and item["data"]:
                        contact = item["data"][0]
                        contacts.append(contact)
                        logger.debug(f"Extracted contact: {contact.get('firstName', '')} {contact.get('lastName', '')}")
                    elif "firstName" in item or "lastName" in item:
                        # Direct contact object (no nesting)
                        contacts.append(item)
                else:
                    logger.warning(f"Unexpected item type in enrich response: {type(item)}")
        elif isinstance(raw_data, dict):
            logger.info(f"Enrich response dict keys: {list(raw_data.keys())}")
            # ZoomInfo enrich response: data is a dict with {outputFields, result, requiredFields}
            # Contacts are in data["result"]
            if "result" in raw_data:
                result_data = raw_data.get("result", [])
                logger.info(f"Enrich response: result contains {len(result_data) if isinstance(result_data, list) else 'non-list'}")
                if isinstance(result_data, list):
                    for item in result_data:
                        if isinstance(item, dict):
                            # Each result item has {input, data, matchStatus}
                            # The actual contact is in item["data"][0]
                            if "data" in item and isinstance(item["data"], list) and item["data"]:
                                contact = item["data"][0]
                                contacts.append(contact)
                                logger.debug(f"Extracted contact from result: {contact.get('firstName', '')} {contact.get('lastName', '')}")
                            elif "firstName" in item or "lastName" in item:
                                # Direct contact (no nesting)
                                contacts.append(item)
                elif isinstance(result_data, dict):
                    if "data" in result_data and isinstance(result_data["data"], list) and result_data["data"]:
                        contacts.append(result_data["data"][0])
                    else:
                        contacts.append(result_data)
            elif "data" in raw_data and isinstance(raw_data["data"], list) and raw_data["data"]:
                contacts = [raw_data["data"][0]]
            elif "firstName" in raw_data or "lastName" in raw_data:
                contacts = [raw_data]
        else:
            logger.warning(f"Unexpected enrich response data type: {type(raw_data)}")

        result = {
            "data": contacts,
            "success": response.get("success", []),
            "noMatch": response.get("noMatch", []),
        }
        logger.info(f"Contact Enrich complete: {len(contacts)} contacts extracted, {len(result['noMatch'])} no match")
        return result

    def enrich_contacts_batch(
        self,
        person_ids: list[str],
        output_fields: list[str] | None = None,
        batch_size: int = 25,
        progress_callback=None,
    ) -> list[dict]:
        """
        Enrich contacts in batches (ZoomInfo allows up to 25 per request).

        Args:
            person_ids: List of personId values to enrich
            output_fields: Fields to return (None = all available)
            batch_size: Number of contacts per API call (max 25)
            progress_callback: Optional callback(enriched_count, total_count)

        Returns:
            List of enriched contact dicts
        """
        total = len(person_ids)
        num_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Contact Enrich Batch: {total} contacts in {num_batches} batches (USES CREDITS)")

        all_enriched = []

        for i in range(0, total, batch_size):
            batch_num = (i // batch_size) + 1
            batch_ids = person_ids[i:i + batch_size]
            logger.info(f"  Enriching batch {batch_num}/{num_batches} ({len(batch_ids)} contacts)")

            params = ContactEnrichParams(
                person_ids=batch_ids,
                output_fields=output_fields,
            )
            result = self.enrich_contacts(params)
            all_enriched.extend(result.get("data", []))

            if progress_callback:
                progress_callback(len(all_enriched), total)

        logger.info(f"Contact Enrich Batch complete: {len(all_enriched)} contacts enriched from {total} requested")
        return all_enriched

    def estimate_credits(self, total_results: int) -> int:
        """Estimate credits for a query (1 credit per record)."""
        return total_results

    def get_usage(self) -> dict:
        """
        Get current API usage and limits.

        Returns dict with credit usage, limits, and rate information.
        This is useful for displaying in dashboards and budget tracking.

        Returns:
            Dict with usage data including credits used, limits, etc.
        """
        logger.info("Fetching API usage data...")
        response = self._request("GET", "/lookup/usage")
        logger.info(f"Usage data retrieved: {json.dumps(response, indent=2)[:500]}")
        return response

    def get_lookup_fields(self, field_type: str = "search") -> dict:
        """
        Get available fields for search or enrich operations.

        Args:
            field_type: "search" for search input fields, "enrich" for output fields

        Returns:
            Dict with available field definitions
        """
        endpoint = f"/lookup/{field_type}fields"
        logger.info(f"Fetching {field_type} fields metadata...")
        response = self._request("GET", endpoint)
        logger.info(f"Retrieved {len(response.get('data', []))} {field_type} fields")
        return response

    def get_query_hash(self, params: IntentQueryParams | GeoQueryParams | ContactQueryParams) -> str:
        """Generate cache key hash for query parameters."""
        if isinstance(params, IntentQueryParams):
            key_data = {
                "type": "intent",
                "topics": sorted(params.topics),
                "strengths": sorted(params.signal_strengths or []),
                "employee_min": params.employee_min,
                "sic_codes": sorted(params.sic_codes or []),
            }
        elif isinstance(params, ContactQueryParams):
            key_data = {
                "type": "contact",
                "zip_codes": sorted(params.zip_codes),
                "radius": params.radius_miles,
                "states": sorted(params.states),
                "location_type": params.location_type,
                "employee_min": params.employee_min,
                "sic_codes": sorted(params.sic_codes or []),
                "company_past_or_present": params.company_past_or_present,
                "exclude_partial_profiles": params.exclude_partial_profiles,
                "required_fields": sorted(params.required_fields or []),
                "required_fields_operator": params.required_fields_operator,
                "contact_accuracy_score_min": params.contact_accuracy_score_min,
                "exclude_org_exported": params.exclude_org_exported,
                "management_levels": sorted(params.management_levels or []),
                "job_titles": sorted(params.job_titles or []),
            }
        else:
            key_data = {
                "type": "geography",
                "zip_codes": sorted(params.zip_codes),
                "radius": params.radius_miles,
                "employee_min": params.employee_min,
                "sic_codes": sorted(params.sic_codes or []),
            }

        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]


@st.cache_resource
def get_zoominfo_client() -> ZoomInfoClient:
    """Get cached ZoomInfo client instance from Streamlit secrets."""
    return ZoomInfoClient(
        client_id=st.secrets["ZOOMINFO_CLIENT_ID"],
        client_secret=st.secrets["ZOOMINFO_CLIENT_SECRET"],
    )
