"""
Semantic intent classifier for SpendGuard API.

Used ONLY when action_type is missing or "unknown".
Maps reason_text to a canonical action_type using cosine similarity
against anchor embeddings for each action type.

Canonical action types: refund, credit, discount, spend.

Examples:
- "make the customer whole"  → refund
- "courtesy adjustment"      → credit
- "loyalty pricing"          → discount
- "approve vendor invoice"   → spend

IMPORTANT: Semantics classify. Rules decide.
This service NEVER overrides a rule engine decision.
It only resolves an ambiguous action_type before the rule engine runs.

# TODO: Loop 5
"""
