"""Writing an outbound message down.

Extracted out of the pipeline because there are now two senders -- the bot and
an agent -- and they must not be able to disagree about what a failed send
looks like in a thread.

The FailedJob row is deliberately *not* written here. The pipeline records a
failure against its inbound event; the API records one against the connection.
That difference belongs to the caller, and pretending otherwise would give this
function a connection_id parameter it has no use for.
"""

from datetime import datetime, timezone

from app.dispatch.dispatcher import DispatchOutcome
from app.models.conversation import Conversation
from app.models.message import DeliveryStatus, Direction, Message, SenderType


def record_outbound(
    db,
    conversation: Conversation,
    text: str | None,
    attachments: list[dict],
    outcome: DispatchOutcome,
    sender_type: SenderType,
    sender_user_id: int | None = None,
) -> Message:
    """Add the message row for one dispatch, and move the conversation's clock.

    Returns the added row without flushing: the caller owns the transaction and
    decides when -- and whether -- it lands.
    """
    delivered = [result for result in outcome.sent if result.ok]
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.OUTBOUND,
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        text=text,
        attachments=attachments,
        # The first delivered chunk's id. A long reply is several provider
        # messages and only one column holds an id; the first is the one a
        # human would quote back.
        provider_message_id=delivered[0].provider_message_id if delivered else None,
        delivery_status=(
            DeliveryStatus.FAILED if outcome.permanent_failure else DeliveryStatus.SENT
        ),
        error=outcome.permanent_failure,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.add(conversation)
    return message
