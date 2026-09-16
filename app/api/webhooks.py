"""HTTP transport for inbound channel webhooks."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.ingress.queue import InboundQueue
from app.ingress.receiver import CentralReceiver, ReceiveError

router = APIRouter(tags=["webhooks"])

def get_inbound_queue() -> InboundQueue:
    from app.worker.queue import CeleryInboundQueue

    return CeleryInboundQueue()


@router.post("/webhooks/{provider}/{connection_id}")
async def receive_webhook(
    provider: str,
    connection_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    queue: InboundQueue = Depends(get_inbound_queue),
) -> Response:
    raw_body = await request.body()
    try:
        await CentralReceiver(queue).receive(
            provider=provider,
            connection_id=connection_id,
            headers=request.headers,
            raw_body=raw_body,
            db=db,
        )
    except ReceiveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return Response(status_code=200)
