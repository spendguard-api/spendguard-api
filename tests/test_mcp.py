"""
Tests for the SpendGuard MCP server.

Covers:
- All 5 tools are registered with correct names
- Each tool has valid schema (name, description, inputSchema)
- Each tool calls the correct API endpoint (mocked _api_request)
- Error responses are parsed gracefully
- Unknown tool name returns error

Uses mocked _api_request — no live API calls.

Run with: .venv/bin/python -m pytest tests/test_mcp.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from unittest.mock import AsyncMock, patch

import pytest

# Load the MCP server module dynamically and register it in sys.modules
# so patch() can find it.
_spec = importlib.util.spec_from_file_location("spendguard_mcp_server", "mcp/server.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["spendguard_mcp_server"] = _mod
_spec.loader.exec_module(_mod)

server = _mod.server
TOOLS = _mod.TOOLS
call_tool = _mod.call_tool
_handle_check = _mod._handle_check
_handle_create_policy = _mod._handle_create_policy
_handle_get_policy = _mod._handle_get_policy
_handle_simulate = _mod._handle_simulate
_handle_list_violations = _mod._handle_list_violations

EXPECTED_TOOL_NAMES = [
    "check_financial_action",
    "create_policy",
    "get_policy",
    "simulate_actions",
    "list_violations",
]


# ============================================================
# Section 1 — Tool Registration
# ============================================================

class TestToolRegistration:
    """Verify all 5 tools are registered correctly."""

    def test_exactly_5_tools_registered(self):
        assert len(TOOLS) == 5

    def test_tool_names_match_spec(self):
        names = [t.name for t in TOOLS]
        for expected in EXPECTED_TOOL_NAMES:
            assert expected in names, f"Missing tool: {expected}"

    def test_each_tool_has_description(self):
        for tool in TOOLS:
            assert tool.description, f"Tool {tool.name} has no description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"

    def test_each_tool_has_input_schema(self):
        for tool in TOOLS:
            assert tool.inputSchema, f"Tool {tool.name} has no inputSchema"
            assert tool.inputSchema.get("type") == "object"
            assert "properties" in tool.inputSchema

    def test_check_tool_has_required_fields(self):
        check_tool = next(t for t in TOOLS if t.name == "check_financial_action")
        required = check_tool.inputSchema.get("required", [])
        for field in ["agent_id", "policy_id", "amount", "currency", "counterparty"]:
            assert field in required, f"check_financial_action missing required field: {field}"

    def test_create_policy_has_required_fields(self):
        tool = next(t for t in TOOLS if t.name == "create_policy")
        required = tool.inputSchema.get("required", [])
        assert "name" in required
        assert "rules" in required

    def test_get_policy_has_required_fields(self):
        tool = next(t for t in TOOLS if t.name == "get_policy")
        required = tool.inputSchema.get("required", [])
        assert "policy_id" in required

    def test_simulate_has_required_fields(self):
        tool = next(t for t in TOOLS if t.name == "simulate_actions")
        required = tool.inputSchema.get("required", [])
        assert "policy_id" in required
        assert "actions" in required

    def test_server_name(self):
        assert server.name == "spendguard"


# ============================================================
# Section 2 — Tool Handlers (mocked _api_request)
# ============================================================

class TestCheckTool:
    """check_financial_action calls POST /v1/checks correctly."""

    @pytest.mark.asyncio
    async def test_returns_allow(self):
        mock_api = AsyncMock(return_value={
            "check_id": "chk_test", "decision": "allow", "confidence": "high",
            "policy_version": 1, "latency_ms": 10, "timestamp": "2026-03-31T00:00:00Z",
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_check({
                "agent_id": "test-agent", "policy_id": "test_policy",
                "action_type": "refund", "amount": 50.0, "currency": "USD",
                "counterparty": "cust_001",
            })
            assert result["decision"] == "allow"
            mock_api.assert_called_once()
            args = mock_api.call_args
            assert args[0][0] == "POST"
            assert args[0][1] == "/v1/checks"

    @pytest.mark.asyncio
    async def test_includes_optional_fields(self):
        mock_api = AsyncMock(return_value={"decision": "block"})
        with patch.object(_mod, "_api_request", mock_api):
            await _handle_check({
                "agent_id": "agent", "policy_id": "pol",
                "amount": 100.0, "currency": "USD", "counterparty": "cust",
                "reason_text": "make the customer whole",
                "payment_method": "card",
                "metadata": {"days_since_purchase": 5},
            })
            body = mock_api.call_args.kwargs.get("json_body", {})
            assert body["reason_text"] == "make the customer whole"
            assert body["payment_method"] == "card"
            assert body["metadata"]["days_since_purchase"] == 5

    @pytest.mark.asyncio
    async def test_returns_block(self):
        mock_api = AsyncMock(return_value={
            "decision": "block", "violated_rule_id": "r1",
            "reason_code": "max_amount_exceeded",
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_check({
                "agent_id": "a", "policy_id": "p", "action_type": "refund",
                "amount": 600.0, "currency": "USD", "counterparty": "c",
            })
            assert result["decision"] == "block"
            assert result["violated_rule_id"] == "r1"


class TestCreatePolicyTool:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self):
        mock_api = AsyncMock(return_value={"policy_id": "test_pol", "name": "Test", "version": 1})
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_create_policy({
                "name": "Test Policy",
                "rules": [{"rule_id": "r1", "rule_type": "max_amount", "parameters": {"limit": 500}}],
            })
            assert result["policy_id"] == "test_pol"
            assert mock_api.call_args[0][0] == "POST"
            assert mock_api.call_args[0][1] == "/v1/policies"


class TestGetPolicyTool:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self):
        mock_api = AsyncMock(return_value={"policy_id": "my_pol", "version": 1, "rules": []})
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_get_policy({"policy_id": "my_pol"})
            assert result["policy_id"] == "my_pol"
            assert "/v1/policies/my_pol" in mock_api.call_args[0][1]

    @pytest.mark.asyncio
    async def test_passes_version_param(self):
        mock_api = AsyncMock(return_value={"policy_id": "pol", "version": 2})
        with patch.object(_mod, "_api_request", mock_api):
            await _handle_get_policy({"policy_id": "pol", "version": 2})
            params = mock_api.call_args.kwargs.get("params", {})
            assert params.get("version") == 2


class TestSimulateTool:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self):
        mock_api = AsyncMock(return_value={
            "mode": "demo", "results": [],
            "summary": {"total": 0, "allowed": 0, "blocked": 0, "escalated": 0},
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_simulate({
                "policy_id": "test_pol",
                "actions": [{"agent_id": "a1", "policy_id": "test_pol",
                             "action_type": "refund", "amount": 50, "currency": "USD",
                             "counterparty": "c1"}],
            })
            assert result["mode"] == "demo"
            assert mock_api.call_args[0][1] == "/v1/simulate"


class TestListViolationsTool:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self):
        mock_api = AsyncMock(return_value={
            "data": [], "pagination": {"next_cursor": None, "has_more": False, "total_count": 0},
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_list_violations({"decision": "block", "limit": 10})
            assert "data" in result
            assert mock_api.call_args[0][1] == "/v1/violations"
            params = mock_api.call_args.kwargs.get("params", {})
            assert params["decision"] == "block"
            assert params["limit"] == 10


# ============================================================
# Section 3 — Error Handling
# ============================================================

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_401_error_parsed(self):
        mock_api = AsyncMock(return_value={
            "error": {"code": "unauthorized", "message": "Invalid API key."},
            "_status_code": 401,
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_check({
                "agent_id": "a", "policy_id": "p",
                "amount": 50, "currency": "USD", "counterparty": "c",
            })
            assert result["_status_code"] == 401
            assert result["error"]["code"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_404_error_parsed(self):
        mock_api = AsyncMock(return_value={
            "error": {"code": "policy_not_found", "message": "No policy found."},
            "_status_code": 404,
        })
        with patch.object(_mod, "_api_request", mock_api):
            result = await _handle_get_policy({"policy_id": "nonexistent"})
            assert result["_status_code"] == 404

    @pytest.mark.asyncio
    async def test_exception_handled_gracefully(self):
        mock_api = AsyncMock(side_effect=Exception("Connection timeout"))
        with patch.object(_mod, "_api_request", mock_api):
            results = await call_tool("check_financial_action", {
                "agent_id": "a", "policy_id": "p",
                "amount": 50, "currency": "USD", "counterparty": "c",
            })
            text = results[0].text
            assert "Connection timeout" in text

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        results = await call_tool("nonexistent_tool", {})
        assert len(results) == 1
        assert "Unknown tool" in results[0].text
