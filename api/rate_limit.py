"""
Rate limiting middleware for SpendGuard API.

Applies per-IP rate limiting for unauthenticated requests (10 RPM)
and per-API-key rate limiting for authenticated requests (100 RPM default,
configurable via api_keys.rate_limit_rpm).

Returns 429 with Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining,
and X-RateLimit-Reset headers on breach.

# TODO: Loop 6
"""
