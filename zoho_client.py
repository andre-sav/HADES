"""
Zoho CRM API Client
- Paginated record fetching
- Rate limit handling with exponential backoff
- Filtering by criteria
"""

import httpx
import asyncio
import logging
from typing import Optional, List, Dict, Any

from zoho_auth import ZohoAuth, MAX_RETRIES, BASE_DELAY_SECONDS, MAX_DELAY_SECONDS, RETRYABLE_STATUS_CODES

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


class ZohoAPIError(Exception):
    """Zoho API error with status code."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class ZohoClient:
    """Zoho CRM API client with pagination and retry logic."""

    def __init__(self, auth: ZohoAuth):
        self.auth = auth

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Make authenticated request with retry/backoff."""
        token = await self.auth.get_access_token()
        url = f"{self.auth.api_domain}/crm/v8/{endpoint}"

        # Log request details
        logger.info(f"Zoho API Request: {method} {endpoint}")
        if params:
            # Log params without sensitive data
            safe_params = {k: v for k, v in params.items() if k not in ["access_token"]}
            logger.info(f"  Params: {safe_params}")

        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                logger.info(f"  Retry attempt {attempt + 1}/{MAX_RETRIES + 1}")

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers={"Authorization": f"Zoho-oauthtoken {token}"},
                        params=params,
                        json=json_body,
                        timeout=30.0
                    )

                    # Handle rate limiting
                    if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                        delay = min(BASE_DELAY_SECONDS * (2 ** attempt), MAX_DELAY_SECONDS)
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = min(float(retry_after), MAX_DELAY_SECONDS)
                            except ValueError:
                                pass
                        logger.warning(f"  Rate limit {response.status_code} on {endpoint}, retrying in {delay:.1f}s")
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()

                    if not response.content:
                        logger.info(f"Zoho API Response: {endpoint} -> HTTP {response.status_code}, empty response")
                        return {"data": [], "info": {"count": 0}}

                    result = response.json()
                    record_count = len(result.get("data", []))
                    more_records = result.get("info", {}).get("more_records", False)
                    logger.info(f"Zoho API Response: {endpoint} -> HTTP {response.status_code}, {record_count} records, more={more_records}")
                    return result

                except httpx.TimeoutException:
                    if attempt < MAX_RETRIES:
                        delay = BASE_DELAY_SECONDS * (2 ** attempt)
                        logger.warning(f"  Timeout on {endpoint}, retrying in {delay:.1f}s")
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"  Request timeout after {MAX_RETRIES + 1} attempts")
                    raise ZohoAPIError("Request timeout after retries")
                except httpx.HTTPStatusError as e:
                    logger.error(f"  HTTP error {e.response.status_code}: {e.response.text[:200]}")
                    raise ZohoAPIError(
                        f"API error: {e.response.status_code} - {e.response.text[:200]}",
                        status_code=e.response.status_code
                    )

        raise ZohoAPIError("Max retries exceeded")

    async def get_records(
        self,
        module: str,
        fields: Optional[List[str]] = None,
        criteria: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch records from a module.

        Args:
            module: Module name (e.g., "Accounts", "Contacts")
            fields: List of field API names to return
            criteria: Search criteria (for filtered queries)
            page: Page number (1-indexed) - only used for first 2000 records
            per_page: Records per page (max 200)
            page_token: Token for paginating beyond 2000 records (from previous response)
        """
        params = {"per_page": per_page}

        # Use page_token for pagination beyond 2000 records, otherwise use page
        if page_token:
            params["page_token"] = page_token
        else:
            params["page"] = page

        if fields:
            params["fields"] = ",".join(fields)

        if criteria:
            # Use search endpoint for criteria-based queries
            return await self._request(
                "GET",
                f"{module}/search",
                params={"criteria": criteria, **params}
            )

        return await self._request("GET", module, params=params)

    async def fetch_all_records(
        self,
        module: str,
        fields: Optional[List[str]] = None,
        criteria: Optional[str] = None,
        max_pages: int = 500,
        max_records: int = 100000,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all records from a module with pagination.

        Uses page_token for pagination beyond 2000 records (Zoho API limit).

        Args:
            module: Module name
            fields: Fields to fetch
            criteria: Filter criteria
            max_pages: Safety limit on pages (500 pages = 100k records)
            max_records: Hard cap on total records (Zoho limit is 100k with page_token)

        Returns:
            List of all matching records
        """
        logger.info(f"Zoho Fetch All: module={module}, criteria={criteria[:50] if criteria else None}...")
        all_records = []
        page = 1
        page_token = None

        while page <= max_pages and len(all_records) < max_records:
            result = await self.get_records(
                module=module,
                fields=fields,
                criteria=criteria,
                page=page if page_token is None else 1,  # page ignored when using page_token
                per_page=200,
                page_token=page_token,
            )

            records = result.get("data", [])
            if not records:
                logger.info(f"  Page {page}: no records, stopping")
                break

            all_records.extend(records)
            logger.info(f"  Page {page}: +{len(records)} records, total={len(all_records)}")

            # Check for more pages
            info = result.get("info", {})
            if not info.get("more_records", False):
                logger.info(f"  No more pages available")
                break

            # Use page_token for subsequent requests (required for >2000 records)
            page_token = info.get("next_page_token")
            if not page_token:
                logger.info(f"  No next_page_token, stopping")
                break

            page += 1
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)

        logger.info(f"Zoho Fetch All complete: {len(all_records)} total records from {page} pages")
        return all_records

    async def coql_query(self, query: str) -> Dict[str, Any]:
        """
        Execute a COQL query.

        Args:
            query: COQL query string (e.g., "select id, Name from Accounts where ...")
        """
        return await self._request(
            "POST",
            "coql",
            json_body={"select_query": query}
        )

    async def coql_query_all(
        self,
        base_query: str,
        max_records: int = 50000,
    ) -> List[Dict[str, Any]]:
        """
        Execute COQL query with pagination.

        Args:
            base_query: Query WITHOUT limit/offset (added automatically)
            max_records: Safety limit
        """
        all_records = []
        offset = 0
        batch_size = 200

        while len(all_records) < max_records:
            query = f"{base_query} limit {batch_size} offset {offset}"
            result = await self.coql_query(query)

            data = result.get("data", [])
            if not data:
                break

            all_records.extend(data)

            if not result.get("info", {}).get("more_records", False):
                break

            offset += batch_size
            await asyncio.sleep(0.1)

        return all_records
