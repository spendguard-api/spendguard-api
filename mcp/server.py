"""
SpendGuard MCP Server.

Exposes SpendGuard API as MCP tools so AI agents (Claude, etc.) can
check financial actions, create policies, and inspect violations
through natural conversation.

5 tools:
- check_financial_action  → POST /v1/checks
- create_policy           → POST /v1/policies
- get_policy              → GET /v1/policies/{id}
- simulate_actions        → POST /v1/simulate
- list_violations         → GET /v1/violations

The MCP server is a thin proxy — all business logic lives in the API.

Usage:
  SPENDGUARD_API_URL=https://spendguard-api-production.up.railway.app \
  SPENDGUARD_API_KEY=sg_live_mike_prod_001 \
  python mcp/server.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("spendguard-mcp")

# ============================================================
# Configuration — reads from environment
# ============================================================

API_URL = os.getenv("SPENDGUARD_API_URL", "https://spendguard-api-production.up.railway.app")
API_KEY = os.getenv("SPENDGUARD_API_KEY", "")

server = Server("spendguard")


# ============================================================
# HTTP helper
# ============================================================

async def _api_request(
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
    require_auth: bool = True,
) -> dict:
    """Make an HTTP request to the SpendGuard API."""
    url = f"{API_URL.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if require_auth and API_KEY:
        headers["X-API-Key"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=json_body)
        else:
            raise ValueError(f"Unsupported method: {method}")

    # Parse response
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text, "status_code": resp.status_code}

    # If error, include status code for clarity
    if resp.status_code >= 400:
        if isinstance(data, dict) and "detail" in data:
            data = data["detail"]
        data["_status_code"] = resp.status_code

    return data


# ============================================================
# Tool definitions
# ============================================================

TOOLS = [
    Tool(
        name="check_financial_action",
        description=(
            "Check whether a planned financial action (refund, credit, discount, or vendor payment) "
            "is allowed by policy. Returns 'allow' (proceed), 'block' (do not proceed), or "
            "'escalate' (route to human review). Call this BEFORE executing any financial action. "
            "Every decision is logged to an immutable audit trail."
        ),
        inputSchema={
            "type": "object",
            "required": ["agent_id", "policy_id", "amount", "currency", "counterparty"],
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Your agent identifier (e.g. 'support-agent-v2')",
                },
                "policy_id": {
                    "type": "string",
                    "description": "Which policy to check against (e.g. 'support_refund_policy')",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["refund", "credit", "discount", "spend"],
                    "description": "Type of financial action. If omitted, provide reason_text and the classifier will resolve it.",
                },
                "amount": {
                    "type": "number",
                    "description": "Dollar amount of the action",
                },
                "currency": {
                    "type": "string",
                    "description": "3-letter ISO currency code (e.g. 'USD')",
                },
                "counterparty": {
                    "type": "string",
                    "description": "Customer or vendor ID",
                },
                "reason_text": {
                    "type": "string",
                    "description": "Why this action is being taken. Required if action_type is omitted.",
                },
                "payment_method": {
                    "type": "string",
                    "description": "Payment method: card, ach, wire, crypto, etc.",
                },
                "metadata": {
                    "type": "object",
                    "description": "Extra context: days_since_purchase, discount_percent, country, customer_lifetime_value, etc.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Unique key to safely retry without double-logging.",
                },
            },
        },
    ),
    Tool(
        name="create_policy",
        description=(
            "Create a new financial authorization policy with rules that control what actions are "
            "allowed, blocked, or escalated. If the policy_id already exists, creates a new version. "
            "Previous versions are preserved. Use this to set up guardrails before agents start "
            "making financial decisions."
        ),
        inputSchema={
            "type": "object",
            "required": ["name", "rules"],
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "Optional policy ID. If provided and exists, creates a new version.",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the policy",
                },
                "description": {
                    "type": "string",
                    "description": "What this policy is for",
                },
                "rules": {
                    "type": "array",
                    "description": (
                        "Array of rule objects. Each rule has: rule_id, rule_type, description, parameters. "
                        "Rule types: max_amount, refund_age_limit, blocked_categories, vendor_allowlist, "
                        "blocked_payment_rails, discount_cap, geography_block, time_restriction, "
                        "duplicate_guard, escalate_if."
                    ),
                    "items": {
                        "type": "object",
                        "required": ["rule_id", "rule_type"],
                        "properties": {
                            "rule_id": {"type": "string"},
                            "rule_type": {"type": "string"},
                            "description": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                    },
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional key-value metadata",
                },
            },
        },
    ),
    Tool(
        name="get_policy",
        description=(
            "Retrieve a financial authorization policy and its rules by ID. "
            "Returns the latest version by default. Use this to inspect what rules "
            "are currently active before running checks or making changes."
        ),
        inputSchema={
            "type": "object",
            "required": ["policy_id"],
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The policy ID to retrieve",
                },
                "version": {
                    "type": "integer",
                    "description": "Specific version number. Omit for latest.",
                },
            },
        },
    ),
    Tool(
        name="simulate_actions",
        description=(
            "Test one or more financial actions against a policy with NO side effects. "
            "Nothing is written to the audit log. Use this to preview how a policy would "
            "respond before going live, or to test policy changes safely. "
            "Returns individual results for each action plus a summary."
        ),
        inputSchema={
            "type": "object",
            "required": ["policy_id", "actions"],
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "Policy to simulate against",
                },
                "actions": {
                    "type": "array",
                    "description": "Array of action objects to simulate (same format as check_financial_action params). Max 10 in demo mode, 100 authenticated.",
                    "items": {
                        "type": "object",
                        "required": ["agent_id", "policy_id", "amount", "currency", "counterparty"],
                        "properties": {
                            "agent_id": {"type": "string"},
                            "policy_id": {"type": "string"},
                            "action_type": {"type": "string", "enum": ["refund", "credit", "discount", "spend"]},
                            "amount": {"type": "number"},
                            "currency": {"type": "string"},
                            "counterparty": {"type": "string"},
                            "reason_text": {"type": "string"},
                            "payment_method": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    },
                },
            },
        },
    ),
    Tool(
        name="list_violations",
        description=(
            "View the audit log of blocked and escalated financial actions. "
            "Use this to review what actions were denied or flagged for human review. "
            "Supports filtering by agent, action type, decision, and date range."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Filter by agent ID",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["refund", "credit", "discount", "spend"],
                    "description": "Filter by action type",
                },
                "decision": {
                    "type": "string",
                    "enum": ["block", "escalate"],
                    "description": "Filter by decision type",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results (default 20, max 100)",
                },
            },
        },
    ),
]


# ============================================================
# Tool handlers
# ============================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all available SpendGuard tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route tool calls to the appropriate API endpoint."""
    try:
        if name == "check_financial_action":
            result = await _handle_check(arguments)
        elif name == "create_policy":
            result = await _handle_create_policy(arguments)
        elif name == "get_policy":
            result = await _handle_get_policy(arguments)
        elif name == "simulate_actions":
            result = await _handle_simulate(arguments)
        elif name == "list_violations":
            result = await _handle_list_violations(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as e:
        logger.error("Tool call failed — tool=%s error=%s", name, e)
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _handle_check(args: dict) -> dict:
    """Handle check_financial_action tool call."""
    body = {
        "agent_id": args["agent_id"],
        "policy_id": args["policy_id"],
        "amount": args["amount"],
        "currency": args["currency"],
        "counterparty": args["counterparty"],
    }
    # Optional fields
    for key in ["action_type", "reason_text", "payment_method", "metadata", "idempotency_key"]:
        if key in args and args[key] is not None:
            body[key] = args[key]

    return await _api_request("POST", "/v1/checks", json_body=body)


async def _handle_create_policy(args: dict) -> dict:
    """Handle create_policy tool call."""
    body = {
        "name": args["name"],
        "rules": args["rules"],
    }
    for key in ["policy_id", "description", "metadata"]:
        if key in args and args[key] is not None:
            body[key] = args[key]

    return await _api_request("POST", "/v1/policies", json_body=body)


async def _handle_get_policy(args: dict) -> dict:
    """Handle get_policy tool call."""
    policy_id = args["policy_id"]
    params = {}
    if "version" in args and args["version"] is not None:
        params["version"] = args["version"]

    return await _api_request("GET", f"/v1/policies/{policy_id}", params=params)


async def _handle_simulate(args: dict) -> dict:
    """Handle simulate_actions tool call."""
    body = {
        "policy_id": args["policy_id"],
        "actions": args["actions"],
    }
    # Simulate can work without auth (demo mode)
    has_auth = bool(API_KEY)
    return await _api_request("POST", "/v1/simulate", json_body=body, require_auth=has_auth)


async def _handle_list_violations(args: dict) -> dict:
    """Handle list_violations tool call."""
    params = {}
    for key in ["agent_id", "action_type", "decision", "limit"]:
        if key in args and args[key] is not None:
            params[key] = args[key]

    return await _api_request("GET", "/v1/violations", params=params)


# ============================================================
# Main entry point
# ============================================================

async def main() -> None:
    """Run the SpendGuard MCP server over stdio."""
    if not API_KEY:
        logger.warning(
            "SPENDGUARD_API_KEY not set — authenticated tools (checks, policies, violations) "
            "will fail. Set SPENDGUARD_API_KEY environment variable."
        )
    logger.info("SpendGuard MCP server starting — API URL: %s", API_URL)
    logger.info("Tools available: %s", ", ".join(t.name for t in TOOLS))

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
