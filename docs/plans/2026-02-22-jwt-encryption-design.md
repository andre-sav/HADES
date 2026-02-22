# JWT Encryption at Rest — Design

**Date:** 2026-02-22
**Bead:** HADES-pt0 (item 7 of 7)
**Status:** Approved

## Problem

The ZoomInfo OAuth JWT is persisted as plaintext in the `sync_metadata` Turso table. Anyone with DB access can read the token and impersonate the ZoomInfo session until it expires (~1 hour).

## Decision

Encrypt the JWT at rest using Fernet symmetric encryption with a split-secret model:

- **Turso DB** stores the encrypted blob (ciphertext)
- **st.secrets** stores the decryption key (`ZOOMINFO_TOKEN_KEY`)
- Compromising either system alone reveals nothing

## Architecture

```
On authenticate:
  ZoomInfo API → JWT string
    → Fernet.encrypt(json(jwt + expires_at)) using ZOOMINFO_TOKEN_KEY
    → Store encrypted blob in sync_metadata

On cold start:
  sync_metadata → encrypted blob
    → Fernet.decrypt(blob, ttl=3600) using ZOOMINFO_TOKEN_KEY
    → JWT string → set in-memory
    → If TTL expired or key mismatch → re-authenticate (graceful fallback)
```

## Components

### New secret

`ZOOMINFO_TOKEN_KEY` — a 44-character base64-encoded Fernet key, stored in `.streamlit/secrets.toml`.

Generate with:
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### Changes to `zoominfo_client.py`

1. **`_get_fernet()`** — returns a `Fernet` instance from `ZOOMINFO_TOKEN_KEY`, or `None` if the key or library is unavailable.
2. **`_persist_token()`** — if Fernet available, encrypts the JSON payload before writing. If not, skips persistence (logs warning).
3. **`_load_persisted_token()`** — if Fernet available, decrypts with `ttl=3600`. On any failure (bad key, tampered, TTL expired), discards and falls through to re-auth.

### No schema changes

Same `sync_metadata` table, same `zoominfo_token` key. The value changes from plaintext JSON to an opaque Fernet token string.

### New dependency

`cryptography` — added to `requirements.txt`.

## Error handling

| Scenario | Behavior |
|---|---|
| `ZOOMINFO_TOKEN_KEY` missing from secrets | Persistence disabled, logs warning, auth on every cold start |
| `cryptography` not installed | Same as missing key |
| Decryption fails (bad key, tampered) | Discard cached token, re-authenticate |
| Fernet TTL expired (>1 hour) | Discard cached token, re-authenticate |
| DB write fails | Swallow error, log debug, continue (existing behavior) |

## Security properties

- **Turso DB leak alone** → encrypted blob, no key → useless
- **Casual DB browsing** → opaque ciphertext, not readable
- **Stale tokens** → Fernet TTL rejects decryption after 1 hour
- **Tampered ciphertext** → HMAC verification fails, decryption rejected

**Not defended:** Full secrets.toml + Turso leak together (attacker already has ZoomInfo client credentials at that point).

## Testing

1. Encrypt → persist → load → verify round-trip succeeds
2. Expired Fernet TTL → decryption rejected → triggers re-auth
3. Missing `ZOOMINFO_TOKEN_KEY` → persistence disabled gracefully
4. Corrupted/tampered ciphertext → decryption rejected → triggers re-auth
5. Existing tests for `_get_token` flow continue to pass
