"""
API key validation middleware for SpendGuard API.

Reads the X-API-Key header, hashes the key using SHA-256,
looks up the hash in the api_keys table via Supabase,
and rejects requests with missing or inactive keys.

# TODO: Loop 6
"""
