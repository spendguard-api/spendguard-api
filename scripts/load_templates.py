"""
SpendGuard — Load policy templates into production.

Loads all 4 launch policy templates via POST /v1/policies.
Each template is a complete, valid policy with rules.

Usage:
  python scripts/load_templates.py --base-url https://spendguardapi.com --api-key sg_live_your_key
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

TEMPLATES = [
    {
        "policy_id": "support_refund_policy",
        "name": "AI Support Refund Policy",
        "description": "Standard guardrails for AI agents handling customer refund requests. Prevents oversized refunds, late refunds, and unauthorized payment methods.",
        "rules": [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Refunds may not exceed $500 per transaction without escalation",
                "parameters": {"limit": 500, "currency": "USD"},
            },
            {
                "rule_id": "r2",
                "rule_type": "refund_age_limit",
                "description": "Refunds must be requested within 30 days of the original purchase",
                "parameters": {"max_days": 30},
            },
            {
                "rule_id": "r3",
                "rule_type": "blocked_payment_rails",
                "description": "Refunds may only be issued to the original payment method (card or ACH). No wire transfers or crypto.",
                "parameters": {"rails": ["wire", "crypto", "check", "cash"]},
            },
            {
                "rule_id": "r4",
                "rule_type": "escalate_if",
                "description": "Refunds above $200 require human review before processing",
                "parameters": {"amount_above": 200, "action_types": ["refund"]},
            },
            {
                "rule_id": "r5",
                "rule_type": "duplicate_guard",
                "description": "Block duplicate refund submissions within 10 minutes",
                "parameters": {"window_minutes": 10},
            },
            {
                "rule_id": "r6",
                "rule_type": "time_restriction",
                "description": "Automated refunds only processed during business hours (Mon-Fri, 8am-8pm UTC)",
                "parameters": {
                    "allowed_days": ["mon", "tue", "wed", "thu", "fri"],
                    "allowed_hours_utc": "08:00-20:00",
                },
            },
        ],
        "metadata": {
            "template": True,
            "template_id": "support_refund_policy",
            "version_notes": "Starter template for AI support refund agents.",
        },
    },
    {
        "policy_id": "saas_discount_policy",
        "name": "SaaS Discount Policy",
        "description": "Guardrails for AI agents applying discounts or pricing adjustments. Caps discount depth and escalates unusual pricing decisions.",
        "rules": [
            {
                "rule_id": "r1",
                "rule_type": "discount_cap",
                "description": "Maximum automated discount is 20%. Deeper discounts require human approval.",
                "parameters": {"max_percent": 20},
            },
            {
                "rule_id": "r2",
                "rule_type": "escalate_if",
                "description": "Discounts on deals above $10,000 ACV require sales manager approval",
                "parameters": {"amount_above": 10000, "action_types": ["discount"]},
            },
            {
                "rule_id": "r3",
                "rule_type": "blocked_categories",
                "description": "No automated discounts on enterprise or government contracts",
                "parameters": {"categories": ["enterprise_contract", "government_contract"]},
            },
            {
                "rule_id": "r4",
                "rule_type": "duplicate_guard",
                "description": "Block duplicate discount submissions within 30 minutes",
                "parameters": {"window_minutes": 30},
            },
            {
                "rule_id": "r5",
                "rule_type": "max_amount",
                "description": "Maximum discount value (not percentage) is $5,000 per transaction",
                "parameters": {"limit": 5000, "currency": "USD"},
            },
        ],
        "metadata": {
            "template": True,
            "template_id": "saas_discount_policy",
            "version_notes": "Starter template for SaaS pricing agents.",
        },
    },
    {
        "policy_id": "vendor_spend_policy",
        "name": "Vendor Spend Policy",
        "description": "Guardrails for AI procurement agents making vendor payments. Enforces approved vendor list, spend limits, and payment method controls.",
        "rules": [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Automated vendor payments may not exceed $10,000 per transaction",
                "parameters": {"limit": 10000, "currency": "USD"},
            },
            {
                "rule_id": "r2",
                "rule_type": "escalate_if",
                "description": "Payments above $2,500 require finance team approval",
                "parameters": {"amount_above": 2500, "action_types": ["spend"]},
            },
            {
                "rule_id": "r3",
                "rule_type": "blocked_payment_rails",
                "description": "No wire transfers or crypto payments without manual approval",
                "parameters": {"rails": ["wire", "crypto"]},
            },
            {
                "rule_id": "r4",
                "rule_type": "geography_block",
                "description": "Block payments to high-risk jurisdictions",
                "parameters": {"blocked_countries": ["RU", "KP", "IR", "BY", "CU", "SY"]},
            },
            {
                "rule_id": "r5",
                "rule_type": "duplicate_guard",
                "description": "Block duplicate vendor payment submissions within 60 minutes",
                "parameters": {"window_minutes": 60},
            },
            {
                "rule_id": "r6",
                "rule_type": "time_restriction",
                "description": "Automated payments only processed on business days (Mon-Fri, 9am-5pm UTC)",
                "parameters": {
                    "allowed_days": ["mon", "tue", "wed", "thu", "fri"],
                    "allowed_hours_utc": "09:00-17:00",
                },
            },
            {
                "rule_id": "r7",
                "rule_type": "escalate_if",
                "description": "Spend above $5,000 requires CFO approval",
                "parameters": {"amount_above": 5000, "action_types": ["spend"]},
            },
        ],
        "metadata": {
            "template": True,
            "template_id": "vendor_spend_policy",
            "version_notes": "Starter template for AI procurement agents.",
        },
    },
    {
        "policy_id": "expense_reimbursement_policy",
        "name": "Expense Reimbursement Policy",
        "description": "Guardrails for AI agents processing employee expense reimbursements. Enforces per-transaction limits, category rules, and escalation for high-value claims.",
        "rules": [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Individual expense claims may not exceed $500 without manager approval",
                "parameters": {"limit": 500, "currency": "USD"},
            },
            {
                "rule_id": "r2",
                "rule_type": "escalate_if",
                "description": "Claims above $250 require manager approval",
                "parameters": {"amount_above": 250, "action_types": ["spend"]},
            },
            {
                "rule_id": "r3",
                "rule_type": "blocked_categories",
                "description": "Personal expenses, alcohol, and entertainment above policy limit are blocked",
                "parameters": {
                    "categories": [
                        "personal",
                        "alcohol_over_policy",
                        "entertainment_over_policy",
                        "gambling",
                        "luxury_goods",
                    ]
                },
            },
            {
                "rule_id": "r4",
                "rule_type": "blocked_payment_rails",
                "description": "Reimbursements only via direct deposit (ACH) or corporate card. No wire, check, or crypto.",
                "parameters": {"rails": ["wire", "crypto", "cash"]},
            },
            {
                "rule_id": "r5",
                "rule_type": "duplicate_guard",
                "description": "Block duplicate expense submissions within 24 hours",
                "parameters": {"window_minutes": 1440},
            },
            {
                "rule_id": "r6",
                "rule_type": "refund_age_limit",
                "description": "Expense claims must be submitted within 60 days of the expense date",
                "parameters": {"max_days": 60},
            },
        ],
        "metadata": {
            "template": True,
            "template_id": "expense_reimbursement_policy",
            "version_notes": "Starter template for expense reimbursement agents.",
        },
    },
]


def load_templates(base_url: str, api_key: str, dry_run: bool = False) -> None:
    """Load all 4 policy templates into SpendGuard."""
    url = f"{base_url.rstrip('/')}/v1/policies"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }

    results = {"success": 0, "failed": 0, "skipped": 0}

    for template in TEMPLATES:
        policy_id = template["policy_id"]
        name = template["name"]

        if dry_run:
            print(f"[DRY RUN] Would load: {policy_id} — {name}")
            results["skipped"] += 1
            continue

        try:
            resp = requests.post(url, headers=headers, json=template, timeout=30)

            if resp.status_code == 201:
                data = resp.json()
                version = data.get("version", "?")
                print(f"[OK] {policy_id} — {name} (version {version})")
                results["success"] += 1
            else:
                error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                print(f"[FAIL] {policy_id} — HTTP {resp.status_code}: {error}")
                results["failed"] += 1

        except requests.RequestException as e:
            print(f"[FAIL] {policy_id} — Connection error: {e}")
            results["failed"] += 1

    print()
    print(f"Done: {results['success']} loaded, {results['failed']} failed, {results['skipped']} skipped")

    if results["failed"] > 0:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load SpendGuard policy templates into production")
    parser.add_argument("--base-url", required=True, help="API base URL (e.g., https://spendguardapi.com)")
    parser.add_argument("--api-key", required=True, help="SpendGuard API key")
    parser.add_argument("--dry-run", action="store_true", help="Print templates without loading")
    args = parser.parse_args()

    print(f"Loading 4 policy templates into: {args.base_url}")
    print()
    load_templates(args.base_url, args.api_key, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
