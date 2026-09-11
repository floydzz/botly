"""Operator CLI. Merchant sessions cannot set provider prices or mint credits."""

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.llm.billing import BillingError, settle, top_up
from app.llm.providers import Completion, TokenUsage
from app.models.billing import LlmModel, LlmUsage
from app.models.merchant import Merchant
from app.models.inbound_event import InboundEvent, InboundEventStatus


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Literal["openai", "gemini", "anthropic", "qwen"]
    model_code: str = Field(min_length=1, max_length=191, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = False
    input_usd_per_million: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    output_usd_per_million: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    cached_usd_per_million: Decimal = Field(ge=0, max_digits=20, decimal_places=10)
    cache_write_usd_per_million: Decimal = Field(ge=0, max_digits=20, decimal_places=10)
    multiplier: Decimal = Field(ge=1, le=100, decimal_places=6)
    max_input_tokens: int = Field(default=8192, ge=1024, le=1_000_000)
    max_output_tokens: int = Field(default=1024, ge=128, le=100_000)


async def run(args):
    async with AsyncSessionLocal() as db:
        if args.action == "models":
            configs = [ModelConfig.model_validate(value) for value in json.loads(Path(args.file).read_text())]
            for config in configs:
                row = (await db.execute(select(LlmModel).where(LlmModel.provider == config.provider, LlmModel.model_code == config.model_code).with_for_update())).scalar_one_or_none()
                if row is None:
                    row = LlmModel(**config.model_dump())
                else:
                    for key, value in config.model_dump().items():
                        setattr(row, key, value)
                db.add(row)
                await db.flush()
                print(f"model {row.id}: {row.provider}/{row.model_code}, enabled={row.enabled}")
        elif args.action == "top-up":
            if await db.get(Merchant, args.merchant_id) is None:
                raise BillingError("merchant not found")
            entry = await top_up(db, args.merchant_id, Decimal(args.credits), args.reference, args.note)
            print(f"top-up entry {entry.id}: {entry.amount} credits")
        elif args.action == "pending":
            rows = (await db.execute(select(LlmUsage).where(LlmUsage.status.in_(["reserved", "uncertain"])).order_by(LlmUsage.id).limit(100))).scalars()
            for row in rows:
                print(f"usage={row.id} merchant={row.merchant_id} event={row.inbound_event_id} status={row.status} held={row.reserved_credits} request={row.provider_request_id} error={row.error}")
            events = (await db.execute(select(InboundEvent).where(InboundEvent.status == InboundEventStatus.PROCESSING).order_by(InboundEvent.updated_at).limit(100))).scalars()
            for event in events:
                print(f"processing event={event.id} connection={event.connection_id} updated={event.updated_at.isoformat()} (may still be running)")
        else:
            row = await db.get(LlmUsage, args.usage_id)
            if row is None or row.status not in {"reserved", "uncertain"}:
                raise BillingError("usage is not awaiting reconciliation")
            result = None
            if args.usage_json:
                usage = TokenUsage.model_validate_json(Path(args.usage_json).read_text())
                result = Completion(row.response_text or "", usage, usage.model_dump(), row.provider_request_id)
            settled = await settle(db, row.id, result=result, error=f"operator reconciliation: {args.note}", allow_overage=True)
            if settled.status == "uncertain":
                raise BillingError("actual charge exceeds hold; investigate pricing/limits before reconciliation")
            print(f"usage {row.id}: {settled.status}")
        await db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    models = sub.add_parser("models", help="import/update model catalog from JSON; existing prices are snapshotted per call")
    models.add_argument("file")
    funding = sub.add_parser("top-up", help="record a verified payment or explicitly authorized grant")
    funding.add_argument("merchant_id", type=int)
    funding.add_argument("credits")
    funding.add_argument("--reference", required=True)
    funding.add_argument("--note", required=True)
    sub.add_parser("pending", help="list usage holds needing investigation")
    reconcile = sub.add_parser("reconcile", help="only after checking provider billing and stopping any active worker for this usage")
    reconcile.add_argument("usage_id", type=int)
    mode = reconcile.add_mutually_exclusive_group(required=True)
    mode.add_argument("--no-charge", action="store_true")
    mode.add_argument("--usage-json", help="JSON containing verified input_tokens, output_tokens and cache counts")
    reconcile.add_argument("--note", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
