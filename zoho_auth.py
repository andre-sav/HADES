"""
Zoho OAuth 2.0 Authentication Module
- Token refresh with caching
- Streamlit secrets compatible
"""

import httpx
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

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

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ZohoAuth:
    """Zoho OAuth token management with caching."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_url: str = "https://accounts.zoho.com",
        api_domain: str = "https://www.zohoapis.com"
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.accounts_url = accounts_url
        self.api_domain = api_domain

        # Token cache
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    @classmethod
    def from_streamlit_secrets(cls, secrets) -> "ZohoAuth":
        """Initialize from Streamlit secrets.

        Usage:
            import streamlit as st
            auth = ZohoAuth.from_streamlit_secrets(st.secrets)
        """
        return cls(
            client_id=secrets["ZOHO_CLIENT_ID"],
            client_secret=secrets["ZOHO_CLIENT_SECRET"],
            refresh_token=secrets["ZOHO_REFRESH_TOKEN"],
            accounts_url=secrets.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com"),
            api_domain=secrets.get("ZOHO_API_DOMAIN", "https://www.zohoapis.com"),
        )

    @classmethod
    def from_env(cls) -> "ZohoAuth":
        """Initialize from environment variables."""
        import os
        return cls(
            client_id=os.environ["ZOHO_CLIENT_ID"],
            client_secret=os.environ["ZOHO_CLIENT_SECRET"],
            refresh_token=os.environ["ZOHO_REFRESH_TOKEN"],
            accounts_url=os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com"),
            api_domain=os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.com"),
        )

    async def _refresh_access_token(self) -> str:
        """Refresh the OAuth access token using the refresh token."""
        logger.info("Refreshing Zoho access token...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.accounts_url}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                }
            )
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            # Token expires in 1 hour; refresh 5 min early
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=55)

            logger.info("Zoho access token refreshed successfully")
            return self._access_token

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if (
            self._access_token is None
            or self._token_expires_at is None
            or datetime.now(timezone.utc) >= self._token_expires_at
        ):
            return await self._refresh_access_token()
        return self._access_token

    def is_token_valid(self) -> bool:
        """Check if current token is valid (not expired)."""
        if self._access_token is None or self._token_expires_at is None:
            return False
        return datetime.now(timezone.utc) < self._token_expires_at
