"""Conservative post-manager fact guard for merchant-specific answers."""

from app.runtime.brain import DraftReply


BUSINESS_TERMS = (
    "price", "cost", "stock", "available", "delivery", "shipping", "order",
    "refund", "return", "policy", "warranty", "discount", "promotion", "hours",
    "address", "product", "service", "booking", "appointment",
)


def audit(draft: DraftReply, *, customer_text: str, knowledge_context: str) -> DraftReply:
    """Block a business-specific response when the manager found no evidence.

    The response model is already instructed to cite only supplied evidence.
    This independent guard covers a provider ignoring that instruction. General
    conversational questions remain answerable without merchant documents.
    """
    if draft.escalate or knowledge_context:
        return draft
    lowered = customer_text.lower()
    if any(term in lowered for term in BUSINESS_TERMS):
        return DraftReply(escalate=True, reason="no approved knowledge supports this business-specific answer")
    return draft
