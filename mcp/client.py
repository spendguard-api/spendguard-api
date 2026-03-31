"""
HTTP client wrapper for calling the SpendGuard API.

Used by the MCP server to make authenticated requests.
Handles errors gracefully and returns parsed JSON.

Environment variables:
- SPENDGUARD_API_URL (or SPENDGUARD_BASE_URL) — API base URL
- SPENDGUARD_API_KEY — API key for authenticated endpoints
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


class SpendGuardClient:
    """HTTP client for the SpendGuard API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("SPENDGUARD_API_URL")
            or os.getenv("SPENDGUARD_BASE_URL")
            or "https://spendguard-api-production.up.railway.app"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("SPENDGUARD_API_KEY", "")
        self.timeout = timeout

    def _headers(self, require_auth: bool = True) -> dict[str, str]:
        """Build request headers."""
        headers = {"Content-Type": "application/json"}
        if require_auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def post(
        self,
        path: str,
        json_body: dict[str, Any],
        require_auth: bool = True,
    ) -> dict[str, Any]:
        """Make a POST request to the SpendGuard API."""
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers=self._headers(require_auth),
                json=json_body,
            )
        return self._parse_response(resp)

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        require_auth: bool = True,
    ) -> dict[str, Any]:
        """Make a GET request to the SpendGuard API."""
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                url,
                headers=self._headers(require_auth),
                params=params,
            )
        return self._parse_response(resp)

    def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        """Parse the API response, handling errors gracefully."""
        try:
            data = resp.json()
        except Exception:
            return {
                "error": {
                    "code": "parse_error",
                    "message": f"Failed to parse response (HTTP {resp.status_code})",
                }
            }

        if resp.status_code >= 400:
            # Unwrap FastAPI's detail wrapper if present
            if isinstance(data, dict) and "detail" in data:
                data = data["detail"]
            if isinstance(data, dict):
                data["_status_code"] = resp.status_code

        return data
