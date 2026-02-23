"""
Tests for Zoho integration modules: zoho_auth, zoho_client, zoho_sync.

Run with: pytest tests/test_zoho.py -v
"""

import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta, timezone

# Mock streamlit before importing
sys.modules["streamlit"] = MagicMock()


# =============================================================================
# ZOHO AUTH TESTS
# =============================================================================

class TestZohoAuth:
    """Tests for ZohoAuth token management."""

    def _make_auth(self, **overrides):
        from zoho_auth import ZohoAuth
        defaults = {
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "refresh_token": "test-refresh",
        }
        return ZohoAuth(**{**defaults, **overrides})

    def test_init_defaults(self):
        auth = self._make_auth()
        assert auth.client_id == "test-client-id"
        assert auth.accounts_url == "https://accounts.zoho.com"
        assert auth.api_domain == "https://www.zohoapis.com"
        assert auth._access_token is None
        assert auth._token_expires_at is None

    def test_init_custom_urls(self):
        auth = self._make_auth(
            accounts_url="https://accounts.zoho.eu",
            api_domain="https://www.zohoapis.eu",
        )
        assert auth.accounts_url == "https://accounts.zoho.eu"
        assert auth.api_domain == "https://www.zohoapis.eu"

    def test_from_streamlit_secrets(self):
        from zoho_auth import ZohoAuth
        mock_secrets = {
            "ZOHO_CLIENT_ID": "sid",
            "ZOHO_CLIENT_SECRET": "ssecret",
            "ZOHO_REFRESH_TOKEN": "srefresh",
        }
        mock_secrets_obj = MagicMock()
        mock_secrets_obj.__getitem__ = lambda self, k: mock_secrets[k]
        mock_secrets_obj.get = lambda k, d=None: mock_secrets.get(k, d)

        auth = ZohoAuth.from_streamlit_secrets(mock_secrets_obj)
        assert auth.client_id == "sid"
        assert auth.client_secret == "ssecret"
        assert auth.refresh_token == "srefresh"

    def test_is_token_valid_no_token(self):
        auth = self._make_auth()
        assert auth.is_token_valid() is False

    def test_is_token_valid_expired(self):
        auth = self._make_auth()
        auth._access_token = "expired-token"
        auth._token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert auth.is_token_valid() is False

    def test_is_token_valid_fresh(self):
        auth = self._make_auth()
        auth._access_token = "fresh-token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        assert auth.is_token_valid() is True

    @pytest.mark.asyncio
    async def test_refresh_access_token(self):
        import httpx
        auth = self._make_auth()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new-token"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            token = await auth._refresh_access_token()

        assert token == "new-token"
        assert auth._access_token == "new-token"
        assert auth._token_expires_at is not None

    @pytest.mark.asyncio
    async def test_get_access_token_returns_cached(self):
        auth = self._make_auth()
        auth._access_token = "cached-token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        token = await auth.get_access_token()
        assert token == "cached-token"

    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_when_expired(self):
        auth = self._make_auth()
        auth._access_token = "old-token"
        auth._token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "refreshed-token"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            token = await auth.get_access_token()

        assert token == "refreshed-token"


# =============================================================================
# ZOHO CLIENT TESTS
# =============================================================================

class TestZohoClient:
    """Tests for ZohoClient API methods."""

    def _make_client(self):
        from zoho_client import ZohoClient
        mock_auth = AsyncMock()
        mock_auth.get_access_token = AsyncMock(return_value="test-token")
        mock_auth.api_domain = "https://www.zohoapis.com"
        client = ZohoClient(mock_auth)
        return client

    @pytest.mark.asyncio
    async def test_get_records_basic(self):
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"id": "1"}], "info": {"count": 1}}'
        mock_response.json.return_value = {"data": [{"id": "1"}], "info": {"count": 1}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.get_records("Accounts")

        assert result["data"] == [{"id": "1"}]
        mock_http.request.assert_called_once()
        call_kwargs = mock_http.request.call_args
        assert "Zoho-oauthtoken test-token" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_get_records_with_fields(self):
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [], "info": {"count": 0}}'
        mock_response.json.return_value = {"data": [], "info": {"count": 0}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.is_closed = False
        client._client = mock_http

        await client.get_records("Accounts", fields=["id", "Name", "Phone"])

        call_kwargs = mock_http.request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["fields"] == "id,Name,Phone"

    @pytest.mark.asyncio
    async def test_get_records_with_criteria_uses_search(self):
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [], "info": {}}'
        mock_response.json.return_value = {"data": [], "info": {}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.is_closed = False
        client._client = mock_http

        await client.get_records("Accounts", criteria="(Account_Type:equals:Customer)")

        call_kwargs = mock_http.request.call_args
        url = call_kwargs.kwargs.get("url") or call_kwargs[1].get("url")
        assert "search" in url

    @pytest.mark.asyncio
    async def test_get_records_empty_response(self):
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b''
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.get_records("Accounts")
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_close(self):
        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._client = mock_http

        await client.close()
        mock_http.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_coql_query(self):
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [{"id": "1", "Name": "Test"}]}'
        mock_response.json.return_value = {"data": [{"id": "1", "Name": "Test"}]}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.coql_query("select id, Name from Accounts")

        call_kwargs = mock_http.request.call_args
        method = call_kwargs.kwargs.get("method") or call_kwargs[1].get("method")
        assert method == "POST"
        json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert json_body["select_query"] == "select id, Name from Accounts"


# =============================================================================
# ZOHO SYNC TESTS
# =============================================================================

class TestZohoSyncHelpers:
    """Tests for zoho_sync helper functions."""

    def test_parse_zip_standard(self):
        from zoho_sync import parse_zip
        assert parse_zip("Dallas, TX, 75201") == "75201"

    def test_parse_zip_with_plus4(self):
        from zoho_sync import parse_zip
        assert parse_zip("Dallas, TX, 75201-1234") == "75201"

    def test_parse_zip_none(self):
        from zoho_sync import parse_zip
        assert parse_zip(None) is None

    def test_parse_zip_empty(self):
        from zoho_sync import parse_zip
        assert parse_zip("") is None

    def test_parse_zip_no_match(self):
        from zoho_sync import parse_zip
        assert parse_zip("No zip here") is None

    def test_map_zoho_to_hades_full(self):
        from zoho_sync import map_zoho_to_hades
        record = {
            "id": "zoho-123",
            "Account_Name": "Test Operator",
            "Ref_Company_Name": "Test Vending LLC",
            "Phone": "(555) 123-4567",
            "email": "test@example.com",
            "Shipping_Code": "75201",
            "City_State_Zip": "Dallas, TX, 75201",
            "Domain_URL": "testvending.com",
        }
        result = map_zoho_to_hades(record)

        assert result["zoho_id"] == "zoho-123"
        assert result["operator_name"] == "Test Operator"
        assert result["vending_business_name"] == "Test Vending LLC"
        assert result["operator_phone"] == "(555) 123-4567"
        assert result["operator_email"] == "test@example.com"
        assert result["operator_zip"] == "75201"
        assert result["operator_website"] == "testvending.com"
        assert result["synced_at"] is not None

    def test_map_zoho_to_hades_zip_fallback(self):
        """When Shipping_Code is empty, parse from City_State_Zip."""
        from zoho_sync import map_zoho_to_hades
        record = {
            "id": "zoho-456",
            "Account_Name": "Fallback Op",
            "Shipping_Code": None,
            "City_State_Zip": "Austin, TX, 78701",
        }
        result = map_zoho_to_hades(record)
        assert result["operator_zip"] == "78701"

    def test_map_zoho_to_hades_minimal(self):
        """Minimal record with only required fields."""
        from zoho_sync import map_zoho_to_hades
        record = {"id": "zoho-789", "Account_Name": "Minimal Op"}
        result = map_zoho_to_hades(record)
        assert result["zoho_id"] == "zoho-789"
        assert result["operator_name"] == "Minimal Op"
        assert result["operator_zip"] is None
        assert result["operator_phone"] is None


class TestZohoSyncMetadata:
    """Tests for sync metadata functions."""

    def test_get_last_sync_time_none(self):
        from zoho_sync import get_last_sync_time
        mock_db = MagicMock()
        mock_db.get_sync_value.return_value = None

        result = get_last_sync_time(mock_db)
        assert result is None

    def test_get_last_sync_time_exists(self):
        from zoho_sync import get_last_sync_time
        mock_db = MagicMock()
        mock_db.get_sync_value.return_value = "2026-01-15T10:00:00"

        result = get_last_sync_time(mock_db)
        assert result == "2026-01-15T10:00:00"

    def test_set_last_sync_time(self):
        from zoho_sync import set_last_sync_time
        mock_db = MagicMock()

        set_last_sync_time(mock_db, "2026-02-01T12:00:00")

        mock_db.set_sync_value.assert_called_once()
        call_args = mock_db.set_sync_value.call_args
        assert "2026-02-01T12:00:00" in str(call_args)


class TestZohoSyncOperators:
    """Tests for sync_operators orchestration."""

    @pytest.mark.asyncio
    async def test_sync_no_records(self):
        """Sync with no Zoho records returns zeros."""
        from zoho_sync import sync_operators

        mock_db = MagicMock()
        mock_db.execute.return_value = []
        mock_db.connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.connection.execute.return_value = mock_cursor

        mock_auth = MagicMock()

        with patch("zoho_sync.ZohoClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value = mock_client

            with patch("zoho_sync.fetch_owner_operators", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = []

                result = await sync_operators(mock_db, mock_auth, force_full=True)

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["total_zoho"] == 0
        assert result["sync_type"] == "full"

    @pytest.mark.asyncio
    async def test_sync_creates_new_operators(self):
        """Sync creates operators that don't exist locally."""
        from zoho_sync import sync_operators

        mock_db = MagicMock()
        # get_last_sync_time returns None (force full)
        mock_db.execute.side_effect = [
            [],      # ensure_sync_metadata: no rows
            [],      # get_last_sync_time: no rows
            [],      # all_operators query: empty
        ]
        mock_db.connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.connection.execute.return_value = mock_cursor

        mock_auth = MagicMock()

        zoho_records = [
            {"id": "z1", "Account_Name": "New Operator", "Phone": "555-1111",
             "email": "new@test.com", "Shipping_Code": "10001"},
        ]

        with patch("zoho_sync.ZohoClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value = mock_client

            with patch("zoho_sync.fetch_owner_operators", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = zoho_records

                result = await sync_operators(mock_db, mock_auth, force_full=True)

        assert result["created"] == 1
        assert result["total_zoho"] == 1
        # Verify execute_many was called for batch insert
        mock_db.execute_many.assert_called()


class TestZohoConstants:
    """Test Zoho module constants."""

    def test_zoho_fields_defined(self):
        from zoho_sync import ZOHO_FIELDS
        assert "id" in ZOHO_FIELDS
        assert "Account_Name" in ZOHO_FIELDS
        assert "Modified_Time" in ZOHO_FIELDS
        assert len(ZOHO_FIELDS) >= 10

    def test_retry_constants(self):
        from zoho_auth import MAX_RETRIES, BASE_DELAY_SECONDS, MAX_DELAY_SECONDS
        assert MAX_RETRIES >= 1
        assert BASE_DELAY_SECONDS > 0
        assert MAX_DELAY_SECONDS > BASE_DELAY_SECONDS

    def test_zoho_api_error(self):
        from errors import ZohoAPIError
        err = ZohoAPIError("test error", status_code=429)
        assert str(err) == "test error"
        assert err.status_code == 429
