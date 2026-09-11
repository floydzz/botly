"""Create the one local account needed to enter the app after ``docker compose up``.

This is intentionally a development convenience, not a registration system. The
seed is idempotent and refuses to run outside the development environment.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.channels.fake.adapter import FakeAdapter
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.conversation import Conversation, HandoffState
from app.models.merchant import Merchant
from app.models.message import Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User


async def seed_development_user() -> None:
    if settings.ENVIRONMENT.strip().lower() != "development":
        return

    email = os.getenv("BOTLY_DEMO_EMAIL", "demo@botly.dev").strip().lower()
    password = os.getenv("BOTLY_DEMO_PASSWORD", "botly-demo")
    name = os.getenv("BOTLY_DEMO_NAME", "Demo Operator").strip()
    merchant_name = os.getenv("BOTLY_DEMO_MERCHANT", "Botly Demo Store").strip()

    if not email or not password or not name or not merchant_name:
        raise RuntimeError("BOTLY_DEMO_* values cannot be blank")

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        merchant = (
            await db.execute(select(Merchant).where(Merchant.name == merchant_name))
        ).scalar_one_or_none()
        if merchant is None:
            merchant = Merchant(name=merchant_name)
            db.add(merchant)
            await db.flush()

        if existing is None:
            existing = User(
                merchant_id=merchant.id,
                email=email,
                password_hash=hash_password(password),
                name=name,
            )
            db.add(existing)
            await db.flush()

        shop = (
            await db.execute(
                select(Shop).where(
                    Shop.merchant_id == merchant.id,
                    Shop.name == "Rasa Home Store",
                )
            )
        ).scalar_one_or_none()
        if shop is None:
            shop = Shop(
                merchant_id=merchant.id,
                name="Rasa Home Store",
                platform="standalone",
            )
            db.add(shop)
            await db.flush()

        bot = (
            await db.execute(
                select(Bot).where(Bot.shop_id == shop.id, Bot.name == "Order assistant")
            )
        ).scalar_one_or_none()
        if bot is None:
            bot = Bot(shop_id=shop.id, name="Order assistant")
            db.add(bot)
            await db.flush()

        connection = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.provider == FakeAdapter.provider,
                    ChannelConnection.external_ref == "demo-inbox",
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            connection = ChannelConnection(
                bot_id=bot.id,
                provider=FakeAdapter.provider,
                external_ref="demo-inbox",
                status=ChannelConnectionStatus.ACTIVE,
            )
            connection.set_credentials({})
            db.add(connection)
            await db.flush()

        now = datetime.now(timezone.utc)
        demos = [
            {
                "thread": "demo-siti",
                "name": "Siti Rahman",
                "state": HandoffState.PENDING_HUMAN,
                "reason": "the customer raised money or a refund",
                "minutes": 7,
                "messages": [
                    (SenderType.CUSTOMER, "Hi, my parcel arrived damaged."),
                    (SenderType.BOT, "I can help check the delivery details. Could you share your order number?"),
                    (SenderType.CUSTOMER, "It is MY-10482. I need a refund, please."),
                ],
            },
            {
                "thread": "demo-farah",
                "name": "Farah Nordin",
                "state": HandoffState.BOT,
                "reason": None,
                "minutes": 23,
                "messages": [
                    (SenderType.CUSTOMER, "Do you deliver to Johor Bahru?"),
                    (SenderType.BOT, "Yes. Standard delivery to Johor Bahru takes two to four working days."),
                ],
            },
            {
                "thread": "demo-wei-jian",
                "name": "Wei Jian Lim",
                "state": HandoffState.RESOLVED,
                "reason": None,
                "minutes": 95,
                "messages": [
                    (SenderType.CUSTOMER, "Can I change the delivery address?"),
                    (SenderType.AGENT, "Yes, I have updated it before dispatch."),
                    (SenderType.CUSTOMER, "Perfect, thank you."),
                ],
            },
        ]
        for demo in demos:
            conversation = (
                await db.execute(
                    select(Conversation).where(
                        Conversation.channel_connection_id == connection.id,
                        Conversation.external_thread_id == demo["thread"],
                    )
                )
            ).scalar_one_or_none()
            if conversation is not None:
                continue
            activity_at = now - timedelta(minutes=demo["minutes"])
            conversation = Conversation(
                merchant_id=merchant.id,
                bot_id=bot.id,
                channel_connection_id=connection.id,
                external_thread_id=demo["thread"],
                customer_ref=demo["thread"],
                customer_name=demo["name"],
                handoff_state=demo["state"],
                escalation_reason=demo["reason"],
                last_inbound_at=activity_at,
                last_message_at=activity_at,
                agent_last_read_at=(activity_at if demo["state"] is HandoffState.RESOLVED else None),
            )
            db.add(conversation)
            await db.flush()
            start = activity_at - timedelta(minutes=len(demo["messages"]) * 2)
            for index, (sender_type, text) in enumerate(demo["messages"]):
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        merchant_id=merchant.id,
                        direction=(
                            Direction.INBOUND
                            if sender_type is SenderType.CUSTOMER
                            else Direction.OUTBOUND
                        ),
                        sender_type=sender_type,
                        sender_user_id=(existing.id if sender_type is SenderType.AGENT else None),
                        text=text,
                        created_at=start + timedelta(minutes=index * 2),
                    )
                )
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_development_user())
