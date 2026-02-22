# JWT Encryption at Rest — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Encrypt the ZoomInfo JWT at rest in Turso DB using Fernet symmetric encryption with a split-secret model (key in st.secrets, ciphertext in DB).

**Architecture:** Add a `_get_fernet()` helper that returns a `Fernet` instance from `ZOOMINFO_TOKEN_KEY` secret (or `None` if unavailable). Modify `_persist_token()` to encrypt before writing and `_load_persisted_token()` to decrypt with TTL enforcement. All failures gracefully fall back to re-authentication.

**Tech Stack:** `cryptography` (Fernet/AES-128-CBC + HMAC-SHA256), Streamlit secrets, Turso/libsql

**Design doc:** `docs/plans/2026-02-22-jwt-encryption-design.md`

---

### Task 1: Add `cryptography` dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add the dependency**

Add `cryptography>=41.0` to `requirements.txt` after `rapidfuzz`:

```
rapidfuzz>=3.0
cryptography>=41.0
```

**Step 2: Install it**

Run: `pip install cryptography>=41.0`

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add cryptography for JWT encryption at rest"
```

---

### Task 2: Write failing tests for `_get_fernet()`

**Files:**
- Modify: `tests/test_zoominfo_client.py` (add new test class after `TestTokenPersistenceAndThreadSafety` at line ~1406)

**Step 1: Write the failing tests**

Add this class at the end of `tests/test_zoominfo_client.py`:

```python
class TestJWTEncryption:
    """Tests for Fernet encryption of persisted JWT tokens."""

    @pytest.fixture
    def fernet_key(self):
        """A valid Fernet key for testing."""
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()

    @pytest.fixture
    def client(self):
        return ZoomInfoClient(client_id="test-id", client_secret="test-secret")

    @pytest.fixture
    def mock_session(self, client):
        mock = MagicMock()
        client._session = mock
        return mock

    def test_get_fernet_returns_instance_when_key_available(self, client, fernet_key):
        """_get_fernet() returns Fernet instance when ZOOMINFO_TOKEN_KEY is set."""
        with patch.dict("os.environ", {}, clear=False):
            with patch("zoominfo_client.st") as mock_st:
                mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": fernet_key}
                f = client._get_fernet()
                assert f is not None

    def test_get_fernet_returns_none_when_key_missing(self, client):
        """_get_fernet() returns None when ZOOMINFO_TOKEN_KEY is not in secrets."""
        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {}
            f = client._get_fernet()
            assert f is None

    def test_get_fernet_returns_none_when_key_invalid(self, client):
        """_get_fernet() returns None when ZOOMINFO_TOKEN_KEY is not a valid Fernet key."""
        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": "not-a-valid-key"}
            f = client._get_fernet()
            assert f is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoominfo_client.py::TestJWTEncryption -v`
Expected: FAIL — `AttributeError: 'ZoomInfoClient' object has no attribute '_get_fernet'`

---

### Task 3: Implement `_get_fernet()`

**Files:**
- Modify: `zoominfo_client.py:260` (insert new method before `_persist_token`)

**Step 1: Add the `_get_fernet` method**

Insert this method at line 260 (between `_load_persisted_token` and `_persist_token`). Actually — insert it right before `_load_persisted_token` (before line 241) since both load and persist will call it:

```python
    def _get_fernet(self):
        """Return Fernet instance from ZOOMINFO_TOKEN_KEY secret, or None if unavailable."""
        try:
            from cryptography.fernet import Fernet
            key = st.secrets.get("ZOOMINFO_TOKEN_KEY")
            if not key:
                return None
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            return None
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoominfo_client.py::TestJWTEncryption -v`
Expected: 3 passed

**Step 3: Commit**

```bash
git add zoominfo_client.py tests/test_zoominfo_client.py
git commit -m "feat: add _get_fernet() for JWT encryption at rest"
```

---

### Task 4: Write failing tests for encrypted persist/load round-trip

**Files:**
- Modify: `tests/test_zoominfo_client.py` (add to `TestJWTEncryption` class)

**Step 1: Write the failing tests**

Add these methods to the `TestJWTEncryption` class:

```python
    def test_persist_token_encrypts_when_fernet_available(self, client, fernet_key):
        """_persist_token() should write encrypted data, not plaintext JSON."""
        from cryptography.fernet import Fernet
        import json

        mock_store = MagicMock()
        client._token_store = mock_store
        client.access_token = "secret-jwt-token"
        client.token_expires_at = datetime.now() + timedelta(hours=1)

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": fernet_key}
            client._persist_token()

        # Verify something was written
        mock_store.execute_write.assert_called_once()
        call_args = mock_store.execute_write.call_args
        written_value = call_args[0][1][1]  # second positional arg, second tuple element

        # The written value should NOT be parseable as the original JSON
        # (it's encrypted, so it should be a Fernet token starting with "gAAAAA")
        assert written_value.startswith("gAAAAA"), f"Expected Fernet token, got: {written_value[:50]}"

        # But it should be decryptable back to the original data
        f = Fernet(fernet_key.encode())
        decrypted = json.loads(f.decrypt(written_value.encode()))
        assert decrypted["jwt"] == "secret-jwt-token"

    def test_load_persisted_token_decrypts_round_trip(self, client, fernet_key):
        """Encrypt → persist → load should recover the original token."""
        from cryptography.fernet import Fernet
        import json

        original_jwt = "round-trip-jwt-token"
        expires_at = datetime.now() + timedelta(hours=1)

        # Encrypt the token as _persist_token would
        f = Fernet(fernet_key.encode())
        plaintext = json.dumps({
            "jwt": original_jwt,
            "expires_at": expires_at.isoformat(),
        })
        encrypted = f.encrypt(plaintext.encode()).decode()

        mock_store = MagicMock()
        mock_store.execute.return_value = [(encrypted,)]
        client._token_store = mock_store

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": fernet_key}
            client._load_persisted_token()

        assert client.access_token == original_jwt

    def test_load_persisted_token_rejects_tampered_ciphertext(self, client, fernet_key):
        """Tampered ciphertext should fail decryption — token stays None."""
        mock_store = MagicMock()
        mock_store.execute.return_value = [("gAAAAABcorrupted-data-here!!!",)]
        client._token_store = mock_store

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": fernet_key}
            client._load_persisted_token()

        assert client.access_token is None

    def test_load_persisted_token_rejects_expired_fernet_ttl(self, client, fernet_key):
        """Fernet TTL enforcement should reject tokens encrypted >1 hour ago."""
        from cryptography.fernet import Fernet
        import json

        f = Fernet(fernet_key.encode())
        plaintext = json.dumps({
            "jwt": "old-jwt",
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        })
        encrypted = f.encrypt(plaintext.encode()).decode()

        mock_store = MagicMock()
        mock_store.execute.return_value = [(encrypted,)]
        client._token_store = mock_store

        # Patch Fernet.decrypt to simulate TTL expiry
        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": fernet_key}
            with patch("cryptography.fernet.Fernet.decrypt", side_effect=Exception("TTL expired")):
                client._load_persisted_token()

        assert client.access_token is None

    def test_persist_skips_when_no_fernet_key(self, client):
        """Without ZOOMINFO_TOKEN_KEY, _persist_token should skip (not write plaintext)."""
        mock_store = MagicMock()
        client._token_store = mock_store
        client.access_token = "secret-jwt"
        client.token_expires_at = datetime.now() + timedelta(hours=1)

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {}
            client._persist_token()

        mock_store.execute_write.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoominfo_client.py::TestJWTEncryption -v`
Expected: New tests FAIL (persist still writes plaintext, load doesn't decrypt)

---

### Task 5: Implement encrypted `_persist_token()` and `_load_persisted_token()`

**Files:**
- Modify: `zoominfo_client.py:241-275` (rewrite both methods)

**Step 1: Replace `_load_persisted_token`**

Replace lines 241-258 with:

```python
    def _load_persisted_token(self) -> None:
        """Load and decrypt cached token from database."""
        try:
            rows = self._token_store.execute(
                "SELECT value FROM sync_metadata WHERE key = ?",
                ("zoominfo_token",),
            )
            if not rows:
                return

            stored_value = rows[0][0]
            fernet = self._get_fernet()

            if fernet:
                # Decrypt with 1-hour TTL enforcement
                decrypted = fernet.decrypt(stored_value.encode(), ttl=3600)
                data = json.loads(decrypted.decode())
            else:
                # No encryption key — cannot read encrypted data, skip
                logger.debug("No ZOOMINFO_TOKEN_KEY — cannot decrypt persisted token")
                return

            token = data.get("jwt")
            expires_at_str = data.get("expires_at")
            if token and expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() < expires_at - timedelta(minutes=5):
                    self.access_token = token
                    self.token_expires_at = expires_at
        except Exception as e:
            logger.debug(f"Could not load persisted token: {e}")
```

**Step 2: Replace `_persist_token`**

Replace lines 260-275 with:

```python
    def _persist_token(self) -> None:
        """Encrypt and save current token to database."""
        if not self._token_store or not self.access_token:
            return

        fernet = self._get_fernet()
        if not fernet:
            logger.warning("No ZOOMINFO_TOKEN_KEY — skipping token persistence (would be plaintext)")
            return

        try:
            plaintext = json.dumps({
                "jwt": self.access_token,
                "expires_at": self.token_expires_at.isoformat(),
            })
            encrypted = fernet.encrypt(plaintext.encode()).decode()
            self._token_store.execute_write(
                "INSERT INTO sync_metadata (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                ("zoominfo_token", encrypted),
            )
        except Exception as e:
            logger.debug(f"Could not persist token: {e}")
```

**Step 3: Run new encryption tests**

Run: `python -m pytest tests/test_zoominfo_client.py::TestJWTEncryption -v`
Expected: All 8 tests PASS

**Step 4: Run existing token persistence tests**

Run: `python -m pytest tests/test_zoominfo_client.py::TestTokenPersistenceAndThreadSafety -v`
Expected: These will need updating in Task 6 (they write plaintext mock data that the new code can't decrypt)

**Step 5: Commit**

```bash
git add zoominfo_client.py
git commit -m "feat: encrypt JWT at rest with Fernet split-secret"
```

---

### Task 6: Update existing token persistence tests

**Files:**
- Modify: `tests/test_zoominfo_client.py:1352-1399` (update `TestTokenPersistenceAndThreadSafety`)

The two existing tests (`test_get_token_expired_checks_db_before_reauth` and `test_get_token_expired_reauths_when_db_also_expired`) currently mock `sync_metadata` with plaintext JSON. They need to use encrypted data instead.

**Step 1: Update `test_get_token_expired_checks_db_before_reauth` (line 1352)**

Replace the test body with:

```python
    def test_get_token_expired_checks_db_before_reauth(self, client, mock_session):
        """When in-memory token is expired, should try DB before re-authenticating."""
        from datetime import datetime, timedelta
        from cryptography.fernet import Fernet
        import json

        client.access_token = "expired-token"
        client.token_expires_at = datetime.now() - timedelta(minutes=10)

        # Create encrypted token data (as _persist_token would)
        key = Fernet.generate_key()
        f = Fernet(key)
        valid_token_data = f.encrypt(json.dumps({
            "jwt": "persisted-token",
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        }).encode()).decode()

        mock_store = MagicMock()
        mock_store.execute.return_value = [(valid_token_data,)]
        client._token_store = mock_store

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": key.decode()}
            token = client._get_token()

        assert token == "persisted-token"
        mock_store.execute.assert_called_once()
        mock_session.post.assert_not_called()
```

**Step 2: Update `test_get_token_expired_reauths_when_db_also_expired` (line 1374)**

Replace the test body with:

```python
    def test_get_token_expired_reauths_when_db_also_expired(self, client, mock_session):
        """When both in-memory and DB tokens are expired, should re-authenticate."""
        from datetime import datetime, timedelta
        from cryptography.fernet import Fernet
        import json

        client.access_token = "expired-token"
        client.token_expires_at = datetime.now() - timedelta(minutes=10)

        # Create encrypted but app-level-expired token
        key = Fernet.generate_key()
        f = Fernet(key)
        expired_token_data = f.encrypt(json.dumps({
            "jwt": "also-expired",
            "expires_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        }).encode()).decode()

        mock_store = MagicMock()
        mock_store.execute.return_value = [(expired_token_data,)]
        client._token_store = mock_store

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jwt": "fresh-token", "expiresIn": 3600}
        mock_session.post.return_value = mock_response

        with patch("zoominfo_client.st") as mock_st:
            mock_st.secrets = {"ZOOMINFO_TOKEN_KEY": key.decode()}
            token = client._get_token()

        assert token == "fresh-token"
        mock_store.execute.assert_called_once()
        mock_session.post.assert_called_once()
```

**Step 3: Run all token tests**

Run: `python -m pytest tests/test_zoominfo_client.py::TestTokenPersistenceAndThreadSafety tests/test_zoominfo_client.py::TestJWTEncryption -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_zoominfo_client.py
git commit -m "test: update token persistence tests for Fernet encryption"
```

---

### Task 7: Run full test suite and verify

**Files:** None (verification only)

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 590+ tests passed (582 existing + 8 new encryption tests)

**Step 2: Verify no plaintext token paths remain**

Run: `grep -n 'json.dumps.*jwt.*access_token\|"jwt":.*self.access_token' zoominfo_client.py`
Expected: Only the encrypted path inside `_persist_token` (the `plaintext = json.dumps(...)` line that feeds into `fernet.encrypt`).

**Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: JWT encryption cleanup"
```

---

### Task 8: Document the new secret

**Files:**
- Modify: `CLAUDE.md` (add `ZOOMINFO_TOKEN_KEY` to the secrets section)

**Step 1: Add to secrets list**

In the "Secrets required" section of `CLAUDE.md`, add after `APP_PASSWORD`:

```toml
ZOOMINFO_TOKEN_KEY = "..."          # Fernet key for encrypting JWT at rest (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add ZOOMINFO_TOKEN_KEY to secrets list"
```
