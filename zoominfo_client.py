"""
ZoomInfo API client with OAuth authentication, rate limiting, and error handling.
"""

import logging
import time
import hashlib
import json
from dataclasses import dataclass, replace
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

    def __init__(self, retry_after: int = 60, detail: str = ""):
        self.retry_after = retry_after
        if retry_after >= 60:
            wait_display = f"{retry_after // 60} minute{'s' if retry_after >= 120 else ''}"
        else:
            wait_display = f"{retry_after} seconds"
        msg = f"Rate limit reached. Try again in {wait_display}."
        if detail:
            msg = f"{detail} {msg}"
        super().__init__(
            message=f"Rate limit exceeded. Retry after {retry_after} seconds. {detail}".strip(),
            user_message=msg,
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
    """Parameters for Intent API query (v2 - JSON:API format)."""

    topics: list[str]
    signal_strengths: list[str] | None = None  # High, Medium, Low (maps to signalScoreMin)
    signal_score_min: int | None = None  # 60-100 (overrides signal_strengths if set)
    signal_score_max: int | None = None  # 60-100
    audience_strength_min: str | None = None  # A, B, C, D, E
    audience_strength_max: str | None = None  # A, B, C, D, E
    signal_start_date: str | None = None  # YYYY-MM-DD
    signal_end_date: str | None = None  # YYYY-MM-DD
    employee_min: int | None = None  # Not used by new API, kept for backward compat
    sic_codes: list[str] | None = None  # Not used by new API, kept for backward compat
    page_size: int = 25
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

    zip_codes: list[str] | None = None
    radius_miles: int = 0
    states: list[str] | None = None  # State codes (e.g., ["CA", "TX"])
    company_ids: list[str] | None = None  # Search by company IDs (Intent workflow)
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

    # Minimum seconds between API requests (proactive rate limiting)
    MIN_REQUEST_INTERVAL = 0.5

    def __init__(self, client_id: str, client_secret: str, token_store=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None
        self._session = requests.Session()
        self._last_request_time: float = 0.0
        self._token_store = token_store  # TursoDatabase instance for token persistence
        self.last_exchange: dict | None = None  # Captures last API request/response for debugging
        self._last_auth_response: dict | None = None  # Captures auth error details for debugging

    def _get_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        if self.access_token and self.token_expires_at:
            # Refresh 5 minutes before expiry
            if datetime.now() < self.token_expires_at - timedelta(minutes=5):
                return self.access_token

        # Try loading persisted token from DB before hitting the auth endpoint
        if not self.access_token and self._token_store:
            self._load_persisted_token()
            if self.access_token and self.token_expires_at:
                if datetime.now() < self.token_expires_at - timedelta(minutes=5):
                    logger.info("Using persisted ZoomInfo token from database")
                    return self.access_token

        self._authenticate()
        return self.access_token

    def _load_persisted_token(self) -> None:
        """Load cached token from database."""
        try:
            rows = self._token_store.execute(
                "SELECT value FROM sync_metadata WHERE key = ?",
                ("zoominfo_token",),
            )
            if rows:
                import json
                data = json.loads(rows[0][0])
                token = data.get("jwt")
                expires_at_str = data.get("expires_at")
                if token and expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.now() < expires_at - timedelta(minutes=5):
                        self.access_token = token
                        self.token_expires_at = expires_at
        except Exception as e:
            logger.debug(f"Could not load persisted token: {e}")

    def _persist_token(self) -> None:
        """Save current token to database."""
        if not self._token_store or not self.access_token:
            return
        try:
            import json
            data = json.dumps({
                "jwt": self.access_token,
                "expires_at": self.token_expires_at.isoformat(),
            })
            self._token_store.execute_write(
                "INSERT INTO sync_metadata (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                ("zoominfo_token", data),
            )
        except Exception as e:
            logger.debug(f"Could not persist token: {e}")

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

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Authentication rate limited. Retry-After: {retry_after}s")
                raise ZoomInfoRateLimitError(retry_after, "Authentication endpoint rate limited.")

            if response.status_code == 401:
                logger.error("Authentication failed: Invalid credentials")
                raise ZoomInfoAuthError("Invalid credentials")

            if response.status_code != 200:
                logger.error(f"Authentication failed: HTTP {response.status_code}")
                raise ZoomInfoAPIError(response.status_code, response.text)

            data = response.json()
            self.access_token = data.get("jwt")

            if not self.access_token:
                # Log full response for debugging
                logger.error(f"Auth response missing JWT. Status: {response.status_code}, Keys: {list(data.keys())}, Body: {str(data)[:500]}")
                self._last_auth_response = data
                raise ZoomInfoAuthError(
                    f"Auth succeeded (HTTP {response.status_code}) but no JWT in response. "
                    f"Response keys: {list(data.keys())}"
                )

            # Token typically valid for 1 hour
            expires_in = data.get("expiresIn", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            logger.info(f"Authentication successful. Token expires in {expires_in}s")

            # Persist token to survive restarts
            self._persist_token()

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
        """Make authenticated API request with retry logic and proactive rate limiting."""
        # Proactive rate limiting: ensure minimum gap between requests
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            wait = self.MIN_REQUEST_INTERVAL - elapsed
            logger.debug(f"Rate limiter: waiting {wait:.2f}s before {endpoint}")
            time.sleep(wait)

        url = f"{self.BASE_URL}{endpoint}"
        request_body = kwargs.get("json", {})

        # Initialize exchange tracking BEFORE any calls that can throw
        self.last_exchange = {
            "request": {
                "method": method,
                "url": url,
                "body": request_body or None,
                "query_params": kwargs.get("params"),
            },
            "response": None,
            "error": None,
            "attempts": 0,
        }

        try:
            token = self._get_token()
        except Exception as auth_err:
            self.last_exchange["error"] = f"Authentication failed: {auth_err}"
            # Capture auth response if available
            auth_resp = getattr(self, "_last_auth_response", None)
            if auth_resp:
                self.last_exchange["auth_response"] = auth_resp
            raise

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Log request details
        logger.info(f"API Request: {method} {endpoint}")
        if request_body:
            log_body = {k: v for k, v in request_body.items() if k not in ["jwt", "password"]}
            logger.debug(f"Request body: {json.dumps(log_body, indent=2)}")

        last_error = None

        for attempt in range(max_retries):
            self.last_exchange["attempts"] = attempt + 1
            try:
                logger.debug(f"Attempt {attempt + 1}/{max_retries}")
                response = self._session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=60,
                    **kwargs,
                )
                self._last_request_time = time.time()

                # Capture response for debugging
                try:
                    resp_body = response.json()
                except Exception:
                    resp_body = response.text[:2000] if response.text else None
                self.last_exchange["response"] = {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": resp_body,
                }

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    # Parse response body for detail
                    detail = ""
                    try:
                        body = response.json()
                        detail = body.get("error", body.get("message", response.text[:200]))
                    except Exception:
                        detail = response.text[:200] if response.text else ""
                    logger.warning(
                        f"Rate limited on {endpoint}. Retry-After: {retry_after}s, "
                        f"detail: {detail} (attempt {attempt + 1}/{max_retries})"
                    )
                    # Don't retry if Retry-After is very long (quota-level limit)
                    max_wait = 120  # 2 minutes max per retry
                    if retry_after > max_wait:
                        logger.error(f"Retry-After {retry_after}s exceeds max wait {max_wait}s — not retrying")
                        raise ZoomInfoRateLimitError(retry_after, detail)
                    if attempt < max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise ZoomInfoRateLimitError(retry_after, detail)

                # Handle auth errors
                if response.status_code == 401:
                    logger.warning(f"Auth error on {endpoint}, refreshing token (attempt {attempt + 1}/{max_retries})")
                    try:
                        self._authenticate()
                        headers["Authorization"] = f"Bearer {self.access_token}"
                    except Exception as auth_err:
                        self.last_exchange["error"] = f"Re-authentication failed: {auth_err}"
                        raise
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
                self.last_exchange["error"] = f"Connection error: {str(e)}"
                logger.warning(f"Connection error on {endpoint}: {e} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise ZoomInfoAPIError(0, f"Connection error: {str(e)}")

        self.last_exchange["error"] = f"Max retries exceeded: {str(last_error)}"
        raise ZoomInfoAPIError(0, f"Max retries exceeded: {str(last_error)}")

    def search_intent(self, params: IntentQueryParams) -> dict:
        """
        Query Intent API for companies showing intent signals.

        Uses the legacy Enterprise API endpoint at /search/intent
        (works with JWT from /authenticate).

        Returns dict with 'data' (list of leads) and 'pagination' info.
        """
        logger.info(f"Intent Search: topics={params.topics}, page={params.page}")

        # Build legacy request body
        request_body = {
            "topics": params.topics,
            "rpp": params.page_size,
            "page": params.page,
        }

        # Signal strength: use explicit score if set, otherwise map from categorical
        if params.signal_score_min is not None:
            request_body["signalScoreMin"] = params.signal_score_min
        elif params.signal_strengths:
            strength_to_score = {"High": 90, "Medium": 75, "Low": 60}
            min_score = min(strength_to_score.get(s, 60) for s in params.signal_strengths)
            request_body["signalScoreMin"] = min_score

        if params.signal_score_max is not None:
            request_body["signalScoreMax"] = params.signal_score_max
        if params.audience_strength_min:
            request_body["audienceStrengthMin"] = params.audience_strength_min
        if params.audience_strength_max:
            request_body["audienceStrengthMax"] = params.audience_strength_max
        if params.signal_start_date:
            request_body["signalStartDate"] = params.signal_start_date
        if params.signal_end_date:
            request_body["signalEndDate"] = params.signal_end_date

        # ICP filters supported by legacy endpoint (comma-separated strings)
        if params.employee_min:
            request_body["employeeRangeMin"] = str(params.employee_min)
        if params.sic_codes:
            request_body["sicCodes"] = ",".join(params.sic_codes)

        response = self._request("POST", "/search/intent", json=request_body)

        # Legacy response: data is a flat list of intent records
        raw_data = response.get("data", [])
        if raw_data:
            logger.info(f"Intent API raw keys (first item): {list(raw_data[0].keys())}")
        normalized = []
        for item in raw_data:
            # Legacy fields are already in the expected format
            signal_strength = item.get("intentStrength") or item.get("signalStrength", "")
            signal_score = item.get("signalScore") or 0

            # If no categorical strength, derive from score
            if not signal_strength and signal_score:
                if signal_score >= 90:
                    signal_strength = "High"
                elif signal_score >= 75:
                    signal_strength = "Medium"
                else:
                    signal_strength = "Low"

            # Company info may be nested under "company" object or flat
            company_obj = item.get("company", {})
            company_id = (
                item.get("companyId")
                or company_obj.get("id")
                or item.get("id", "")
            )
            company_name = (
                item.get("companyName")
                or company_obj.get("name")
                or item.get("name", "")
            )
            company_website = (
                item.get("companyWebsite")
                or company_obj.get("website")
                or item.get("website", "")
            )

            normalized.append({
                "companyId": company_id,
                "companyName": company_name,
                "companyWebsite": company_website,
                "intentStrength": signal_strength,
                "intentTopic": item.get("intentTopic") or item.get("topic", ""),
                "intentDate": item.get("intentDate") or item.get("signalDate", ""),
                "sicCode": item.get("sicCode") or company_obj.get("sicCode", ""),
                "city": item.get("city") or company_obj.get("city", ""),
                "state": item.get("state") or company_obj.get("state", ""),
                "employees": item.get("employees") or item.get("employeeCount") or company_obj.get("employeeCount", ""),
                "signalScore": signal_score,
                "audienceStrength": item.get("audienceStrength", ""),
                "category": item.get("category", ""),
                "spikesInDateRange": item.get("spikesInDateRange", 0),
                "hasOtherTopicConsumption": item.get("hasOtherTopicConsumption", company_obj.get("hasOtherTopicConsumption", False)),
                "recommendedContacts": item.get("recommendedContacts", []),
            })

        total = response.get("totalResults", len(normalized))

        result = {
            "data": normalized,
            "pagination": {
                "totalResults": total,
                "pageSize": params.page_size,
                "currentPage": params.page,
                "totalPages": (total + params.page_size - 1) // params.page_size if total > 0 else 1,
            },
            "_raw_keys": list(raw_data[0].keys()) if raw_data else [],
            "_raw_sample": raw_data[0] if raw_data else {},
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
        raw_keys = []
        raw_sample = {}
        params = replace(params)  # Local copy to avoid mutating caller's params

        while current_page <= max_pages:
            params.page = current_page
            result = self.search_intent(params)
            all_leads.extend(result["data"])

            # Capture raw API keys from first page for debugging
            if current_page == 1:
                raw_keys = result.get("_raw_keys", [])
                raw_sample = result.get("_raw_sample", {})

            if progress_callback:
                progress_callback(current_page, result["pagination"]["totalPages"])

            if current_page >= result["pagination"]["totalPages"]:
                break

            current_page += 1

        logger.info(f"Intent Search (all pages) complete: {len(all_leads)} total leads from {current_page} pages")
        # Attach debug info to help diagnose field mapping issues
        self._last_intent_raw_keys = raw_keys
        self._last_intent_raw_sample = raw_sample
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
        params = replace(params)  # Local copy to avoid mutating caller's params

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
        Query Contact Search API for contacts by location or company IDs.

        When company_ids is provided, searches by companyId (Intent workflow).
        Otherwise uses location filters (ZIP, state, radius).

        Returns dict with 'data' (list of contacts) and 'pagination' info.
        """
        # Determine search mode
        is_company_search = bool(params.company_ids)

        if is_company_search:
            logger.info(
                f"Contact Search (by company): {len(params.company_ids)} company ID(s), page={params.page}"
            )
        else:
            zip_count = len(params.zip_codes) if params.zip_codes else 0
            logger.info(
                f"Contact Search: {zip_count} ZIP(s), radius={params.radius_miles}mi, "
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

        if is_company_search:
            # Company ID search - no location filters
            # ZoomInfo companyId field: comma-separated string, 500 char limit
            company_id_str = ",".join(params.company_ids)
            request_body = {
                "companyId": company_id_str,
            }
        else:
            # Location-based search
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

            # Add ZIP radius if searching with radius (not manual ZIP list)
            if params.radius_miles and params.radius_miles > 0:
                request_body["zipCodeRadiusMiles"] = params.radius_miles

        # Pagination goes in query params (per API docs)
        query_params = {
            "page[size]": params.page_size,
            "page[number]": params.page,
            "sort": params.sort_by,
        }

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
        # Company ID search: batch by company IDs instead of ZIPs
        if params.company_ids:
            return self._search_contacts_by_company_batched(params, max_pages, progress_callback)

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
        if params.company_ids:
            logger.info(f"Contact Search (batch): {len(params.company_ids)} company ID(s), max_pages={max_pages}")
        else:
            zip_count = len(params.zip_codes) if params.zip_codes else 0
            logger.info(f"Contact Search (batch): {zip_count} ZIP(s), states={params.states}, max_pages={max_pages}")
        all_contacts = []
        seen_person_ids = set()
        dupes_removed = 0
        current_page = 1
        actual_page_size = None  # Track what ZoomInfo actually returns per page
        params = replace(params)  # Local copy to avoid mutating caller's params

        while current_page <= max_pages:
            params.page = current_page
            result = self.search_contacts(params)
            page_results = result["data"]
            results_count = len(page_results)

            for contact in page_results:
                pid = contact.get("personId") or contact.get("id")
                if pid and pid in seen_person_ids:
                    dupes_removed += 1
                    continue
                if pid:
                    seen_person_ids.add(pid)
                all_contacts.append(contact)

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

        logger.info(f"Contact Search (batch) complete: {len(all_contacts)} unique contacts ({dupes_removed} duplicates removed) from {current_page} pages")
        return all_contacts

    def _search_contacts_by_company_batched(
        self,
        params: ContactQueryParams,
        max_pages: int = 10,
        progress_callback=None,
    ) -> list[dict]:
        """
        Search contacts by company IDs with batching for the 500-char API limit.

        Splits company IDs into batches of ~40 (each ID ~10 chars + comma),
        searches each batch, and deduplicates results.
        """
        MAX_COMPANY_IDS_PER_BATCH = 40
        company_ids = params.company_ids or []

        if len(company_ids) <= MAX_COMPANY_IDS_PER_BATCH:
            return self._search_contacts_single_batch(params, max_pages, progress_callback)

        logger.info(f"Contact Search (by company): {len(company_ids)} IDs exceeds {MAX_COMPANY_IDS_PER_BATCH}, splitting into batches")
        all_contacts_by_id = {}

        for batch_start in range(0, len(company_ids), MAX_COMPANY_IDS_PER_BATCH):
            batch_ids = company_ids[batch_start:batch_start + MAX_COMPANY_IDS_PER_BATCH]
            batch_num = (batch_start // MAX_COMPANY_IDS_PER_BATCH) + 1
            total_batches = (len(company_ids) + MAX_COMPANY_IDS_PER_BATCH - 1) // MAX_COMPANY_IDS_PER_BATCH

            logger.info(f"Contact Search: Company batch {batch_num}/{total_batches} with {len(batch_ids)} IDs")

            batch_params = replace(params, company_ids=batch_ids)

            batch_contacts = self._search_contacts_single_batch(batch_params, max_pages, progress_callback)

            for contact in batch_contacts:
                contact_id = contact.get("id") or contact.get("personId")
                if contact_id and contact_id not in all_contacts_by_id:
                    all_contacts_by_id[contact_id] = contact

        all_contacts = list(all_contacts_by_id.values())
        logger.info(f"Contact Search (by company) complete: {len(all_contacts)} unique contacts from {total_batches} batches")
        return all_contacts

    def search_contacts_by_company(
        self,
        company_ids: list[str],
        management_levels: list[str] | None = None,
        accuracy_min: int = 95,
        required_fields: list[str] | None = None,
        max_pages: int = 5,
        progress_callback=None,
    ) -> list[dict]:
        """
        Search contacts at specific companies (convenience method for Intent workflow).

        Wraps ContactQueryParams creation + search_contacts_one_per_company().

        Args:
            company_ids: List of ZoomInfo company IDs
            management_levels: Filter by management level
            accuracy_min: Minimum accuracy score
            required_fields: Required phone/email fields
            max_pages: Max pages per batch
            progress_callback: Optional progress callback

        Returns:
            List of contacts, one per company (highest accuracy score).
        """
        logger.info(f"Contact Search by Company: {len(company_ids)} companies")
        params = ContactQueryParams(
            company_ids=company_ids,
            management_levels=management_levels or ["Manager"],
            contact_accuracy_score_min=accuracy_min,
            required_fields=required_fields,
        )
        return self.search_contacts_one_per_company(params, max_pages, progress_callback)

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
                "zip_codes": sorted(params.zip_codes or []),
                "radius": params.radius_miles,
                "states": sorted(params.states or []),
                "company_ids": sorted(params.company_ids or []),
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
    from turso_db import get_database
    try:
        token_store = get_database()
    except Exception:
        token_store = None
    return ZoomInfoClient(
        client_id=st.secrets["ZOOMINFO_CLIENT_ID"],
        client_secret=st.secrets["ZOOMINFO_CLIENT_SECRET"],
        token_store=token_store,
    )
