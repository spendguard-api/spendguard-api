# SpendGuard MCP Server

MCP (Model Context Protocol) wrapper for the SpendGuard API. Lets AI agents like Claude check financial actions, create policies, and inspect violations through natural conversation.

## 5 Tools

| Tool | What it does |
|---|---|
| `check_financial_action` | Check if a refund/credit/discount/payment is allowed |
| `create_policy` | Create or update a financial authorization policy |
| `get_policy` | Retrieve a policy and its rules |
| `simulate_actions` | Test actions against a policy (no side effects) |
| `list_violations` | View blocked/escalated action audit log |

## Setup for Claude Desktop

1. Open Claude Desktop settings → Edit Config (or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS)

2. Add the SpendGuard server to your config:

```json
{
  "mcpServers": {
    "spendguard": {
      "command": "/path/to/your/.venv/bin/python",
      "args": ["/path/to/mcp/server.py"],
      "env": {
        "SPENDGUARD_API_URL": "https://spendguard-api-production.up.railway.app",
        "SPENDGUARD_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

3. Restart Claude Desktop

4. You should see SpendGuard tools available in the tools menu

## Setup for Claude Code

Add to your Claude Code MCP settings (`.claude/settings.json` or project settings):

```json
{
  "mcpServers": {
    "spendguard": {
      "command": "/path/to/your/.venv/bin/python",
      "args": ["/path/to/mcp/server.py"],
      "env": {
        "SPENDGUARD_API_URL": "https://spendguard-api-production.up.railway.app",
        "SPENDGUARD_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## Example Conversation

> **You:** "Can our support agent refund $350 to customer_7821? The order is 12 days old."
>
> **Claude:** *uses check_financial_action* → "The refund requires human approval — $350 exceeds the $200 auto-approve threshold. The order is within the 30-day window, so it's eligible once approved."

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SPENDGUARD_API_URL` | Yes | Your SpendGuard API URL |
| `SPENDGUARD_API_KEY` | Yes* | Your API key (*not needed for simulate demo mode) |

## Running Manually (for testing)

```bash
SPENDGUARD_API_URL=https://spendguard-api-production.up.railway.app \
SPENDGUARD_API_KEY=your-key \
python mcp/server.py
```

The server communicates over stdio (stdin/stdout) per the MCP protocol.
