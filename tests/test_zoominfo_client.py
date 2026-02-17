"""
Tests for ZoomInfo API client.

Run with: pytest tests/test_zoominfo_client.py -v
"""

import sys
from unittest.mock import MagicMock, patch, Mock

import pytest

# Mock streamlit before importing
sys.modules["streamlit"] = MagicMock()

from zoominfo_client import (
    ZoomInfoClient,
    ZoomInfoAuthError,
    ZoomInfoRateLimitError,
    ZoomInfoAPIError,
    IntentQueryParams,
    GeoQueryParams,
    ContactQueryParams,
    ContactEnrichParams,
)


class TestZoomInfoClient:
    """Tests for ZoomInfoClient class."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return ZoomInfoClient(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    @pytest.fixture
    def mock_session(self, client):
        """Mock the requests session."""
        mock = MagicMock()
        client._session = mock
        return mock

    def test_init(self, client):
        """Test client initialization."""
        assert client.client_id == "test-client-id"
        assert client.client_secret == "test-client-secret"
        assert client.access_token is None

    def test_authenticate_success(self, client, mock_session):
        """Test successful authentication."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jwt": "test-token-12345",
            "expiresIn": 3600,
        }
        mock_session.post.return_value = mock_response

        client._authenticate()

        assert client.access_token == "test-token-12345"
        assert client.token_expires_at is not None
        mock_session.post.assert_called_once()

    def test_authenticate_invalid_credentials(self, client, mock_session):
        """Test authentication with invalid credentials."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_session.post.return_value = mock_response

        with pytest.raises(ZoomInfoAuthError):
            client._authenticate()

    def test_authenticate_server_error(self, client, mock_session):
        """Test authentication with server error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.post.return_value = mock_response

        with pytest.raises(ZoomInfoAPIError) as exc_info:
            client._authenticate()

        assert exc_info.value.status_code == 500

    def test_get_token_cached(self, client):
        """Test token caching."""
        from datetime import datetime, timedelta

        client.access_token = "cached-token"
        client.token_expires_at = datetime.now() + timedelta(hours=1)

        token = client._get_token()

        assert token == "cached-token"

    def test_get_token_expired(self, client, mock_session):
        """Test token refresh when expired."""
        from datetime import datetime, timedelta

        client.access_token = "old-token"
        client.token_expires_at = datetime.now() - timedelta(minutes=1)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jwt": "new-token",
            "expiresIn": 3600,
        }
        mock_session.post.return_value = mock_response

        token = client._get_token()

        assert token == "new-token"

    def test_request_success(self, client, mock_session):
        """Test successful API request."""
        # Mock auth
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {"jwt": "token", "expiresIn": 3600}

        # Mock API request
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = {"data": [{"id": 1}]}

        mock_session.post.return_value = auth_response
        mock_session.request.return_value = api_response

        result = client._request("POST", "/test")

        assert result == {"data": [{"id": 1}]}

    def test_request_rate_limit(self, client, mock_session):
        """Test rate limit handling."""
        # Mock auth
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {"jwt": "token", "expiresIn": 3600}
        mock_session.post.return_value = auth_response

        # Mock rate limited response
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "30"}

        mock_session.request.return_value = rate_limit_response

        with pytest.raises(ZoomInfoRateLimitError) as exc_info:
            client._request("POST", "/test", max_retries=1)

        assert exc_info.value.retry_after == 30

    def test_request_server_error_retry(self, client, mock_session):
        """Test server error with retry."""
        # Mock auth
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {"jwt": "token", "expiresIn": 3600}
        mock_session.post.return_value = auth_response

        # Mock server error then success
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Server Error"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"data": []}

        mock_session.request.side_effect = [error_response, success_response]

        result = client._request("POST", "/test", max_retries=2)

        assert result == {"data": []}
        assert mock_session.request.call_count == 2


class TestIntentSearch:
    """Tests for Intent API search."""

    @pytest.fixture
    def client(self):
        """Create client with mocked request."""
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_search_intent(self, client):
        """Test intent search with legacy response format."""
        mock_response = {
            "data": [
                {
                    "companyId": "123",
                    "companyName": "Test Co",
                    "companyWebsite": "testco.com",
                    "intentTopic": "Vending",
                    "intentStrength": "High",
                    "signalScore": 92,
                    "audienceStrength": "A",
                    "intentDate": "2026-02-01T00:00:00",
                }
            ],
            "totalResults": 1,
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = IntentQueryParams(topics=["Vending"])
            result = client.search_intent(params)

        assert len(result["data"]) == 1
        lead = result["data"][0]
        assert lead["companyName"] == "Test Co"
        assert lead["companyId"] == "123"
        assert lead["intentStrength"] == "High"
        assert lead["signalScore"] == 92
        assert lead["intentTopic"] == "Vending"
        assert lead["intentDate"] == "2026-02-01T00:00:00"
        assert result["pagination"]["totalResults"] == 1

    def test_search_intent_nested_company(self, client):
        """Test intent search with nested company object (current API format)."""
        mock_response = {
            "data": [
                {
                    "company": {
                        "id": "abc123",
                        "name": "Nested Co",
                        "website": "nested.com",
                        "hasOtherTopicConsumption": True,
                    },
                    "topic": "Vending Machines",
                    "signalScore": 88,
                    "audienceStrength": "B",
                    "signalDate": "2026-02-01",
                    "recommendedContacts": [{"id": 1, "firstName": "Jane"}],
                }
            ],
            "totalResults": 1,
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = IntentQueryParams(topics=["Vending Machines"])
            result = client.search_intent(params)

        lead = result["data"][0]
        assert lead["companyId"] == "abc123"
        assert lead["companyName"] == "Nested Co"
        assert lead["companyWebsite"] == "nested.com"
        assert lead["intentTopic"] == "Vending Machines"
        assert lead["signalScore"] == 88
        assert lead["hasOtherTopicConsumption"] is True
        assert len(lead["recommendedContacts"]) == 1

    def test_search_intent_null_fields_fallback(self, client):
        """Test that null legacy fields fall through to alternate field names."""
        mock_response = {
            "data": [
                {
                    "companyId": "hash123",
                    "companyName": None,  # null — should not block fallback
                    "intentDate": None,   # null — should fall through to signalDate
                    "intentTopic": "",    # empty — should fall through to topic
                    "signalDate": "2/1/2026 12:00 AM",
                    "topic": "Vending Machines",
                    "signalScore": 95,
                    "company": {"name": "Fallback Corp"},
                    "recommendedContacts": [],
                }
            ],
            "totalResults": 1,
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = IntentQueryParams(topics=["Vending Machines"])
            result = client.search_intent(params)

        lead = result["data"][0]
        assert lead["companyName"] == "Fallback Corp"
        assert lead["intentDate"] == "2/1/2026 12:00 AM"
        assert lead["intentTopic"] == "Vending Machines"

    def test_search_intent_request_format(self, client):
        """Test intent search sends legacy format to /search/intent."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = IntentQueryParams(topics=["Vending"])
            client.search_intent(params)

        call_args = mock_req.call_args
        # Verify legacy endpoint path
        assert call_args[0][1] == "/search/intent"
        # Verify flat request body (not JSON:API envelope)
        body = call_args[1]["json"]
        assert body["topics"] == ["Vending"]
        assert body["rpp"] == 25
        assert body["page"] == 1

    def test_search_intent_with_filters(self, client):
        """Test intent search maps signal_strengths to signalScoreMin."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = IntentQueryParams(
                topics=["Vending", "Breakroom"],
                signal_strengths=["High", "Medium"],
            )
            client.search_intent(params)

        body = mock_req.call_args[1]["json"]
        assert body["topics"] == ["Vending", "Breakroom"]
        # High=90, Medium=75 → min is 75
        assert body["signalScoreMin"] == 75

    def test_search_intent_signal_score_override(self, client):
        """Test explicit signal_score_min overrides signal_strengths."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = IntentQueryParams(
                topics=["Vending"],
                signal_strengths=["High"],  # Would map to 90
                signal_score_min=80,  # Explicit override
            )
            client.search_intent(params)

        body = mock_req.call_args[1]["json"]
        assert body["signalScoreMin"] == 80

    def test_search_intent_signal_strength_mapping(self, client):
        """Test signalScore to intentStrength normalization."""
        mock_response = {
            "data": [
                {"signalScore": 95, "intentTopic": "A", "companyId": "1", "companyName": "High"},
                {"signalScore": 80, "intentTopic": "B", "companyId": "2", "companyName": "Med"},
                {"signalScore": 65, "intentTopic": "C", "companyId": "3", "companyName": "Low"},
            ],
            "totalResults": 3,
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.search_intent(IntentQueryParams(topics=["Test"]))

        assert result["data"][0]["intentStrength"] == "High"
        assert result["data"][1]["intentStrength"] == "Medium"
        assert result["data"][2]["intentStrength"] == "Low"

    def test_search_intent_all_pages(self, client):
        """Test fetching all pages."""
        page1_response = {
            "data": [{"id": 1}, {"id": 2}],
            "totalResults": 4,
        }
        page2_response = {
            "data": [{"id": 3}, {"id": 4}],
            "totalResults": 4,
        }

        with patch.object(
            client, "search_intent", side_effect=[
                {"data": page1_response["data"], "pagination": {"totalResults": 4, "pageSize": 2, "currentPage": 1, "totalPages": 2}},
                {"data": page2_response["data"], "pagination": {"totalResults": 4, "pageSize": 2, "currentPage": 2, "totalPages": 2}},
            ]
        ):
            params = IntentQueryParams(topics=["Vending"], page_size=2)
            results = client.search_intent_all_pages(params)

        assert len(results) == 4


class TestCompanySearch:
    """Tests for Company Search API."""

    @pytest.fixture
    def client(self):
        """Create client with mocked request."""
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_search_companies(self, client):
        """Test company search by geography."""
        mock_response = {
            "data": [
                {"companyId": "456", "companyName": "Local Biz", "zip": "75201"}
            ],
            "totalResults": 1,
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = GeoQueryParams(zip_codes=["75201"], radius_miles=25)
            result = client.search_companies(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["companyName"] == "Local Biz"

    def test_search_companies_multi_zip(self, client):
        """Test company search with multiple zip codes."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = GeoQueryParams(
                zip_codes=["75201", "75202", "75203"],
                radius_miles=10,
            )
            client.search_companies(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert len(body["zipCodeRadiusList"]) == 3
        assert body["zipCodeRadiusList"][0]["zipCode"] == "75201"
        assert body["zipCodeRadiusList"][0]["radius"] == 10


class TestQueryHash:
    """Tests for query hash generation."""

    def test_intent_query_hash(self):
        """Test intent query hash is consistent."""
        client = ZoomInfoClient("id", "secret")

        params1 = IntentQueryParams(topics=["Vending"], signal_strengths=["High"])
        params2 = IntentQueryParams(topics=["Vending"], signal_strengths=["High"])

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 == hash2

    def test_intent_query_hash_different(self):
        """Test different params produce different hash."""
        client = ZoomInfoClient("id", "secret")

        params1 = IntentQueryParams(topics=["Vending"])
        params2 = IntentQueryParams(topics=["Breakroom"])

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 != hash2

    def test_geo_query_hash(self):
        """Test geo query hash is consistent."""
        client = ZoomInfoClient("id", "secret")

        params1 = GeoQueryParams(zip_codes=["75201"], radius_miles=25)
        params2 = GeoQueryParams(zip_codes=["75201"], radius_miles=25)

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 == hash2

    def test_geo_query_hash_order_independent(self):
        """Test zip code order doesn't affect hash."""
        client = ZoomInfoClient("id", "secret")

        params1 = GeoQueryParams(zip_codes=["75201", "75202"], radius_miles=25)
        params2 = GeoQueryParams(zip_codes=["75202", "75201"], radius_miles=25)

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 == hash2


class TestCreditEstimation:
    """Tests for credit estimation."""

    def test_estimate_credits(self):
        """Test credit estimation."""
        client = ZoomInfoClient("id", "secret")

        assert client.estimate_credits(100) == 100
        assert client.estimate_credits(0) == 0
        assert client.estimate_credits(500) == 500


class TestContactSearch:
    """Tests for Contact Search API."""

    @pytest.fixture
    def client(self):
        """Create client with mocked request."""
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_search_contacts(self, client):
        """Test basic contact search."""
        mock_response = {
            "data": [
                {
                    "personId": "123",
                    "firstName": "John",
                    "lastName": "Doe",
                    "companyId": "456",
                    "companyName": "Test Corp",
                    "contactAccuracyScore": 95,
                }
            ],
            "totalResults": 1,
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactQueryParams(zip_codes=["75201"], radius_miles=25, states=["TX"])
            result = client.search_contacts(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["firstName"] == "John"
        assert result["pagination"]["totalResults"] == 1

    def test_search_contacts_with_state_filter(self, client):
        """Test contact search with state filter."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX", "CA"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["state"] == "TX,CA"  # Comma-separated string
        assert body["locationSearchType"] == "PersonAndHQ"

    def test_search_contacts_sorting(self, client):
        """Test contact search with sorting parameters."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                sort_by="contactAccuracyScore",
                sort_order="desc",
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        # Sorting is now in query params, not body
        query_params = call_args[1]["params"]
        assert query_params["sort"] == "contactAccuracyScore"

    def test_search_contacts_location_type(self, client):
        """Test contact search with different location types."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                location_type="PersonAndHQ",
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["locationSearchType"] == "PersonAndHQ"

    def test_search_contacts_quality_filters(self, client):
        """Test contact search includes quality filters by default."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        # Verify default quality filters
        assert body["companyPastOrPresent"] == "present"
        assert body["excludePartialProfiles"] is True
        assert body["contactAccuracyScoreMin"] == "95"  # API expects string
        # required_fields is None by default (not included in request)
        assert "requiredFields" not in body

    def test_search_contacts_custom_quality_filters(self, client):
        """Test contact search with custom quality filter values."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                company_past_or_present="pastOrPresent",
                exclude_partial_profiles=False,
                required_fields=["email"],
                contact_accuracy_score_min=80,
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["companyPastOrPresent"] == "pastOrPresent"
        # When False, not included in request (falsy value skips the conditional)
        assert "excludePartialProfiles" not in body
        assert body["requiredFields"] == "email"  # Comma-separated string
        assert body["contactAccuracyScoreMin"] == "80"  # API expects string

    def test_search_contacts_no_required_fields(self, client):
        """Test contact search without requiredFields filter."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                required_fields=None,  # Disable this filter
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert "requiredFields" not in body

    def test_search_contacts_required_fields_or(self, client):
        """Test contact search with multiple required fields."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                required_fields=["mobilePhone", "directPhone", "phone"],
                required_fields_operator="or",
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["requiredFields"] == "mobilePhone,directPhone,phone"

    def test_search_contacts_required_fields_and(self, client):
        """Test contact search with multiple required fields."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                required_fields=["directPhone", "email"],
                required_fields_operator="and",
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["requiredFields"] == "directPhone,email"

    def test_search_contacts_required_fields_no_operator(self, client):
        """Test requiredFieldsOperator is NOT sent (API rejects it)."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                required_fields=["mobilePhone", "directPhone", "phone"],
                required_fields_operator="or",
            )
            client.search_contacts(params)

        body = mock_req.call_args[1]["json"]
        assert body["requiredFields"] == "mobilePhone,directPhone,phone"
        assert "requiredFieldsOperator" not in body

    def test_search_contacts_no_required_fields(self, client):
        """Test requiredFields not sent when no required fields specified."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                required_fields=None,
            )
            client.search_contacts(params)

        body = mock_req.call_args[1]["json"]
        assert "requiredFields" not in body
        assert "requiredFieldsOperator" not in body

    def test_search_contacts_management_level(self, client):
        """Test contact search with management level filter."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                management_levels=["Manager", "Director"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["managementLevel"] == "Manager,Director"

    def test_search_contacts_job_titles(self, client):
        """Test contact search with job titles filter."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                job_titles=["Facility Manager", "Operations Manager"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["jobTitle"] == "Facility Manager,Operations Manager"

    def test_search_contacts_exclude_org_exported(self, client):
        """Test contact search param exists but field not in API (not sent)."""
        # Note: excludeOrgExportedContacts is not a valid ZoomInfo API field
        # The param exists in ContactQueryParams but is not included in request
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        # This field is not in the official API, so we don't send it
        assert "excludeOrgExportedContacts" not in body

    def test_search_contacts_include_org_exported(self, client):
        """Test contact search can include org exported contacts."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
                exclude_org_exported=False,
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert "excludeOrgExportedContacts" not in body

    def test_search_contacts_one_per_company(self, client):
        """Test deduplication to one contact per company."""
        # Simulate contacts sorted by accuracy score (highest first)
        all_contacts = [
            {"personId": "1", "companyId": "A", "contactAccuracyScore": 95},
            {"personId": "2", "companyId": "A", "contactAccuracyScore": 85},  # Same company, lower score
            {"personId": "3", "companyId": "B", "contactAccuracyScore": 90},
            {"personId": "4", "companyId": "C", "contactAccuracyScore": 88},
            {"personId": "5", "companyId": "B", "contactAccuracyScore": 70},  # Same company, lower score
        ]

        with patch.object(
            client, "search_contacts_all_pages", return_value=all_contacts
        ):
            params = ContactQueryParams(zip_codes=["75201"], radius_miles=25, states=["TX"])
            results = client.search_contacts_one_per_company(params)

        # Should have 3 unique companies, keeping highest-scored contact each
        assert len(results) == 3
        company_ids = [c["companyId"] for c in results]
        assert set(company_ids) == {"A", "B", "C"}

        # Verify we kept the highest-scored contact for each company
        scores_by_company = {c["companyId"]: c["contactAccuracyScore"] for c in results}
        assert scores_by_company["A"] == 95
        assert scores_by_company["B"] == 90
        assert scores_by_company["C"] == 88

    def test_search_contacts_one_per_company_nested_company_id(self, client):
        """Test deduplication handles nested company.id structure."""
        all_contacts = [
            {"personId": "1", "company": {"id": "A"}, "contactAccuracyScore": 95},
            {"personId": "2", "company": {"id": "A"}, "contactAccuracyScore": 85},
            {"personId": "3", "company": {"id": "B"}, "contactAccuracyScore": 90},
        ]

        with patch.object(
            client, "search_contacts_all_pages", return_value=all_contacts
        ):
            params = ContactQueryParams(zip_codes=["75201"], radius_miles=25, states=["TX"])
            results = client.search_contacts_one_per_company(params)

        assert len(results) == 2

    def test_contact_query_hash(self):
        """Test contact query hash is consistent."""
        client = ZoomInfoClient("id", "secret")

        params1 = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["TX"],
        )
        params2 = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["TX"],
        )

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 == hash2

    def test_contact_query_hash_different(self):
        """Test different contact params produce different hash."""
        client = ZoomInfoClient("id", "secret")

        params1 = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["TX"],
        )
        params2 = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["CA"],
        )

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        assert hash1 != hash2


class TestUsageAPI:
    """Tests for Usage API methods."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return ZoomInfoClient(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    def test_get_usage(self, client):
        """Test fetching usage data."""
        mock_response = {
            "creditsUsed": 150,
            "creditsLimit": 1000,
            "recordsEnriched": 150,
            "recordsLimit": 2500,
            "requestsUsed": 500,
            "requestsLimit": 10000,
            "rateLimit": 25,
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            result = client.get_usage()

        mock_req.assert_called_once_with("GET", "/lookup/usage")
        assert result["creditsUsed"] == 150
        assert result["creditsLimit"] == 1000
        assert result["recordsEnriched"] == 150

    def test_get_lookup_fields_search(self, client):
        """Test fetching search field definitions."""
        mock_response = {
            "data": [
                {"name": "companyName", "type": "string"},
                {"name": "jobTitle", "type": "string"},
                {"name": "zipCode", "type": "string"},
            ]
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            result = client.get_lookup_fields("search")

        mock_req.assert_called_once_with("GET", "/lookup/searchfields")
        assert len(result["data"]) == 3

    def test_get_lookup_fields_enrich(self, client):
        """Test fetching enrich field definitions."""
        mock_response = {
            "data": [
                {"name": "firstName", "type": "string"},
                {"name": "lastName", "type": "string"},
                {"name": "email", "type": "string"},
                {"name": "directPhone", "type": "string"},
            ]
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            result = client.get_lookup_fields("enrich")

        mock_req.assert_called_once_with("GET", "/lookup/enrichfields")
        assert len(result["data"]) == 4


class TestContactEnrich:
    """Tests for Contact Enrich API - specifically testing response parsing."""

    @pytest.fixture
    def client(self):
        """Create client with mocked request."""
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_enrich_contacts_three_level_nesting(self, client):
        """Test parsing the real ZoomInfo 3-level nested response structure.

        Structure: response["data"]["result"][i]["data"][0] -> actual contact
        """
        mock_response = {
            "success": [{"personId": "123"}],
            "data": {
                "outputFields": ["firstName", "lastName", "email"],
                "result": [
                    {
                        "input": {"personId": "123"},
                        "data": [
                            {
                                "id": 123,
                                "firstName": "Robert",
                                "lastName": "Hinkle",
                                "email": "robert@example.com",
                                "phone": "(817) 555-1234",
                                "jobTitle": "General Manager",
                            }
                        ],
                        "matchStatus": "match",
                    }
                ],
                "requiredFields": [],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 1
        contact = result["data"][0]
        assert contact["firstName"] == "Robert"
        assert contact["lastName"] == "Hinkle"
        assert contact["email"] == "robert@example.com"
        assert contact["jobTitle"] == "General Manager"

    def test_enrich_contacts_multiple_contacts(self, client):
        """Test parsing multiple contacts from 3-level nested response."""
        mock_response = {
            "success": [{"personId": "123"}, {"personId": "456"}],
            "data": {
                "outputFields": ["firstName", "lastName"],
                "result": [
                    {
                        "input": {"personId": "123"},
                        "data": [{"id": 123, "firstName": "Alice", "lastName": "Smith"}],
                        "matchStatus": "match",
                    },
                    {
                        "input": {"personId": "456"},
                        "data": [{"id": 456, "firstName": "Bob", "lastName": "Jones"}],
                        "matchStatus": "match",
                    },
                ],
                "requiredFields": [],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123", "456"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 2
        assert result["data"][0]["firstName"] == "Alice"
        assert result["data"][1]["firstName"] == "Bob"

    def test_enrich_contacts_empty_result(self, client):
        """Test handling empty result array."""
        mock_response = {
            "success": [],
            "data": {
                "outputFields": ["firstName", "lastName"],
                "result": [],
                "requiredFields": [],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 0

    def test_enrich_contacts_no_match(self, client):
        """Test handling response with noMatch entries."""
        mock_response = {
            "success": [],
            "noMatch": [{"personId": "999"}],
            "data": {
                "outputFields": ["firstName", "lastName"],
                "result": [],
                "requiredFields": [],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["999"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 0
        assert len(result["noMatch"]) == 1

    def test_enrich_contacts_list_response(self, client):
        """Test parsing list-based response (alternative format).

        Structure: response["data"] is a list of {input, data, matchStatus}
        """
        mock_response = {
            "success": [{"personId": "123"}],
            "data": [
                {
                    "input": {"personId": "123"},
                    "data": [
                        {
                            "id": 123,
                            "firstName": "Jane",
                            "lastName": "Doe",
                            "email": "jane@example.com",
                        }
                    ],
                    "matchStatus": "match",
                }
            ],
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["firstName"] == "Jane"
        assert result["data"][0]["email"] == "jane@example.com"

    def test_enrich_contacts_direct_contact_in_list(self, client):
        """Test parsing when data is a list of direct contacts (no nesting)."""
        mock_response = {
            "success": [{"personId": "123"}],
            "data": [
                {
                    "id": 123,
                    "firstName": "Direct",
                    "lastName": "Contact",
                    "email": "direct@example.com",
                }
            ],
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["firstName"] == "Direct"

    def test_enrich_contacts_batch(self, client):
        """Test batch enrichment splits into multiple API calls."""
        mock_response = {
            "success": [{"personId": "1"}],
            "data": {
                "outputFields": ["firstName"],
                "result": [
                    {
                        "input": {"personId": "1"},
                        "data": [{"id": 1, "firstName": "Test"}],
                        "matchStatus": "match",
                    }
                ],
                "requiredFields": [],
            },
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            # Request 3 contacts with batch_size=2 should make 2 API calls
            result = client.enrich_contacts_batch(
                person_ids=["1", "2", "3"],
                batch_size=2,
            )

        assert mock_req.call_count == 2  # 2 batches: [1,2] and [3]
        assert len(result) == 2  # 1 contact per batch response = 2 total

    def test_enrich_contacts_request_body(self, client):
        """Test that enrich request body is correctly formatted."""
        mock_response = {
            "success": [],
            "data": {"outputFields": [], "result": [], "requiredFields": []},
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactEnrichParams(
                person_ids=["123", "456"],
                output_fields=["firstName", "lastName", "email"],
            )
            client.enrich_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]

        # Check matchPersonInput format
        assert "matchPersonInput" in body
        assert len(body["matchPersonInput"]) == 2
        assert body["matchPersonInput"][0] == {"personId": "123"}
        assert body["matchPersonInput"][1] == {"personId": "456"}

        # Check outputFields is an array (not comma-separated string)
        assert body["outputFields"] == ["firstName", "lastName", "email"]

    def test_enrich_contacts_dict_with_nested_data_no_result(self, client):
        """Test dict response with data.data but no result key."""
        mock_response = {
            "success": [{"personId": "123"}],
            "data": {
                "data": [
                    {"id": 123, "firstName": "Nested", "lastName": "Data"}
                ],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["firstName"] == "Nested"

    def test_enrich_contacts_dict_direct_contact(self, client):
        """Test dict response that is itself a contact (firstName at top level)."""
        mock_response = {
            "success": [{"personId": "123"}],
            "data": {
                "firstName": "TopLevel",
                "lastName": "Contact",
                "email": "top@example.com",
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = ContactEnrichParams(person_ids=["123"])
            result = client.enrich_contacts(params)

        assert len(result["data"]) == 1
        assert result["data"][0]["firstName"] == "TopLevel"


class TestContactSearchByCompanyId:
    """Tests for Contact Search by company ID (Intent workflow)."""

    @pytest.fixture
    def client(self):
        """Create client with mocked request."""
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_search_contacts_by_company_id(self, client):
        """Test contact search using companyId sends correct request body."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                company_ids=["111", "222", "333"],
                management_levels=["Manager"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]

        # Should have companyId, not location fields
        assert body["companyId"] == "111,222,333"
        assert "state" not in body
        assert "zipCode" not in body
        assert "locationSearchType" not in body
        assert "zipCodeRadiusMiles" not in body

    def test_search_contacts_by_company_id_with_quality_filters(self, client):
        """Test companyId search still applies quality filters."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                company_ids=["111"],
                management_levels=["Manager", "Director"],
                contact_accuracy_score_min=85,
                required_fields=["mobilePhone", "phone"],
                required_fields_operator="or",
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]

        assert body["companyId"] == "111"
        assert body["managementLevel"] == "Manager,Director"
        assert body["contactAccuracyScoreMin"] == "85"
        assert body["requiredFields"] == "mobilePhone,phone"
        assert body["companyPastOrPresent"] == "present"
        assert body["excludePartialProfiles"] is True

    def test_contact_query_hash_with_company_ids(self):
        """Test hash includes company_ids and is consistent."""
        client = ZoomInfoClient("id", "secret")

        params1 = ContactQueryParams(company_ids=["111", "222"])
        params2 = ContactQueryParams(company_ids=["222", "111"])  # Different order

        hash1 = client.get_query_hash(params1)
        hash2 = client.get_query_hash(params2)

        # Order shouldn't matter (sorted in hash)
        assert hash1 == hash2

    def test_contact_query_hash_company_vs_location(self):
        """Test company ID search produces different hash from location search."""
        client = ZoomInfoClient("id", "secret")

        params_company = ContactQueryParams(company_ids=["111"])
        params_location = ContactQueryParams(zip_codes=["75201"], states=["TX"])

        hash1 = client.get_query_hash(params_company)
        hash2 = client.get_query_hash(params_location)

        assert hash1 != hash2

    def test_search_contacts_by_company_convenience(self, client):
        """Test the search_contacts_by_company convenience method."""
        mock_contacts = [
            {"personId": "1", "companyId": "A", "contactAccuracyScore": 95},
            {"personId": "2", "companyId": "A", "contactAccuracyScore": 85},
            {"personId": "3", "companyId": "B", "contactAccuracyScore": 90},
        ]

        with patch.object(client, "search_contacts_all_pages", return_value=mock_contacts):
            results = client.search_contacts_by_company(
                company_ids=["A", "B"],
                management_levels=["Manager"],
                accuracy_min=85,
            )

        # Should deduplicate to 1 per company
        assert len(results) == 2

    def test_search_contacts_optional_fields(self, client):
        """Test ContactQueryParams works with all optional fields defaulted."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response):
            # Minimal params - just company_ids
            params = ContactQueryParams(company_ids=["111"])
            result = client.search_contacts(params)

        assert result["data"] == []

    def test_search_contacts_backward_compat(self, client):
        """Test existing callers with zip_codes still work."""
        mock_response = {"data": [], "totalResults": 0}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = ContactQueryParams(
                zip_codes=["75201"],
                radius_miles=25,
                states=["TX"],
            )
            client.search_contacts(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"]
        assert body["state"] == "TX"
        assert body["zipCode"] == "75201"
        assert "companyId" not in body

    def test_search_contacts_single_batch_deduplicates_by_person_id(self, client):
        """Pagination within a single batch should deduplicate by personId."""
        page1 = {
            "data": [
                {"personId": "p1", "firstName": "Alice"},
                {"personId": "p2", "firstName": "Bob"},
            ],
            "totalResults": 3,
            "pagination": {"totalPages": 2},
        }
        page2 = {
            "data": [
                {"personId": "p2", "firstName": "Bob"},  # duplicate
                {"personId": "p3", "firstName": "Carol"},
            ],
            "totalResults": 3,
            "pagination": {"totalPages": 2},
        }
        page3 = {
            "data": [],
            "totalResults": 3,
            "pagination": {"totalPages": 2},
        }

        with patch.object(client, "search_contacts", side_effect=[page1, page2, page3]):
            params = ContactQueryParams(company_ids=["111"])
            contacts = client._search_contacts_single_batch(params, max_pages=5)

        assert len(contacts) == 3
        person_ids = [c["personId"] for c in contacts]
        assert person_ids == ["p1", "p2", "p3"]



class TestTokenPersistenceAndThreadSafety:
    """Tests for token persistence fix and thread-safety."""

    @pytest.fixture
    def client(self):
        return ZoomInfoClient(client_id="test-id", client_secret="test-secret")

    @pytest.fixture
    def mock_session(self, client):
        mock = MagicMock()
        client._session = mock
        return mock

    def test_get_token_expired_checks_db_before_reauth(self, client, mock_session):
        """When in-memory token is expired, should try DB before re-authenticating."""
        from datetime import datetime, timedelta
        import json

        client.access_token = "expired-token"
        client.token_expires_at = datetime.now() - timedelta(minutes=10)

        mock_store = MagicMock()
        valid_token_data = json.dumps({
            "jwt": "persisted-token",
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        })
        mock_store.execute.return_value = [(valid_token_data,)]
        client._token_store = mock_store

        token = client._get_token()

        assert token == "persisted-token"
        mock_store.execute.assert_called_once()
        mock_session.post.assert_not_called()

    def test_get_token_expired_reauths_when_db_also_expired(self, client, mock_session):
        """When both in-memory and DB tokens are expired, should re-authenticate."""
        from datetime import datetime, timedelta
        import json

        client.access_token = "expired-token"
        client.token_expires_at = datetime.now() - timedelta(minutes=10)

        mock_store = MagicMock()
        expired_token_data = json.dumps({
            "jwt": "also-expired",
            "expires_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        })
        mock_store.execute.return_value = [(expired_token_data,)]
        client._token_store = mock_store

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jwt": "fresh-token", "expiresIn": 3600}
        mock_session.post.return_value = mock_response

        token = client._get_token()

        assert token == "fresh-token"
        mock_store.execute.assert_called_once()
        mock_session.post.assert_called_once()

    def test_client_has_threading_lock(self, client):
        """Client should have a threading lock for thread-safety."""
        import threading
        assert hasattr(client, "_lock")
        assert isinstance(client._lock, type(threading.Lock()))
