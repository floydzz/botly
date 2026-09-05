"""Create the tenancy rows one Telegram bot needs, and optionally register its
webhook.

There is no admin API yet -- the seller inbox is build-order step 4 and the
frontend is step 7 -- so this script is how a bot gets into the database until
one of those lands. It is written to be run more than once: names are looked up
before they are created, and re-running with the same bot updates the token in
place rather than colliding with the uniqueness constraint on
(provider, external_ref).

The token is never a literal in this file and must never become one. It is a
per-tenant credential that belongs in channel_connections.credentials_encrypted,
encrypted with CREDENTIALS_ENCRYPTION_KEY -- so this script takes it as an
argument and hands it straight to set_credentials().

    .venv/bin/python scripts/seed_telegram.py --token 123456:ABC...
    .venv/bin/python scripts/seed_telegram.py --token 123456:ABC... \
        --webhook-url https://your-tunnel.ngrok.io

With --webhook-url it also calls setWebhook and flips the connection to active.
Without it the rows are created and the bot stays deaf until you register a
webhook later -- which is the right default, because the URL usually does not
exist yet when the row does.
"""

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path

# Running a file inside scripts/ puts scripts/ on sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.channels.registry import build_adapter  # noqa: E402
from app.channels.telegram.api import HttpTelegramApi  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.bot import Bot  # noqa: E402
from app.models.channel_connection import (  # noqa: E402
    ChannelConnection,
    ChannelConnectionStatus,
)
from app.models.merchant import Merchant  # noqa: E402
from app.models.shop import Shop  # noqa: E402

PROVIDER = "telegram"


async def _get_or_create(db, model, defaults=None, **lookup):
    """Fetch a row by the given columns, creating it if it is not there.

    Not an upsert: existing rows are left exactly as they are. Re-running this
    script must not quietly rename someone's shop.
    """
    statement = select(model)
    for column, value in lookup.items():
        statement = statement.where(getattr(model, column) == value)
    row = (await db.execute(statement)).scalar_one_or_none()
    if row is not None:
        return row, False

    row = model(**lookup, **(defaults or {}))
    db.add(row)
    await db.flush()
    return row, True


async def seed(
    token: str,
    webhook_url: str | None,
    merchant_name: str,
    shop_name: str,
    bot_name: str,
) -> int:
    api = HttpTelegramApi()

    # getMe first, before anything is written. It proves the token is real and
    # it is where the bot's username comes from -- inventing an external_ref
    # would make the row unmatchable against the bot it describes.
    me = await api.call(token, "getMe", {})
    if not me.ok:
        raise SystemExit(f"getMe failed: {me.description}")
    username = me.result["username"]
    print(f"token belongs to @{username} ({me.result.get('first_name', '')})")

    async with AsyncSessionLocal() as db:
        merchant, _ = await _get_or_create(db, Merchant, name=merchant_name)
        shop, _ = await _get_or_create(
            db,
            Shop,
            defaults={"platform": "standalone"},
            merchant_id=merchant.id,
            name=shop_name,
        )
        bot, _ = await _get_or_create(db, Bot, shop_id=shop.id, name=bot_name)

        connection = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.provider == PROVIDER,
                    ChannelConnection.external_ref == username,
                )
            )
        ).scalar_one_or_none()

        if connection is None:
            connection = ChannelConnection(
                bot_id=bot.id, provider=PROVIDER, external_ref=username
            )
            # Telegram does not sign its deliveries. It echoes back whatever
            # secret was given to setWebhook, in X-Telegram-Bot-Api-Secret-Token,
            # and comparing that constant-time is the whole authenticity check --
            # so this value is as sensitive as the token itself.
            secret_token = secrets.token_urlsafe(32)
            created = True
        else:
            # Keep the existing secret: rotating it here would silently
            # invalidate a webhook already registered with Telegram, and every
            # delivery would start coming back 403.
            secret_token = connection.get_credentials()["secret_token"]
            created = False

        connection.set_credentials({"bot_token": token, "secret_token": secret_token})
        db.add(connection)
        await db.flush()

        if webhook_url:
            path = f"/webhooks/{PROVIDER}/{connection.id}"
            full_url = webhook_url.rstrip("/") + path
            if not full_url.startswith("https://"):
                raise SystemExit(
                    f"Telegram only accepts an https webhook: {full_url!r}"
                )

            adapter = build_adapter(connection, webhook_url=full_url)
            await adapter.connect(connection)

            # connect() deliberately does not raise on a Bot API failure, so
            # ask Telegram what it actually thinks rather than assuming.
            info = await api.call(token, "getWebhookInfo", {})
            registered = (info.result or {}).get("url") if info.ok else None
            if registered != full_url:
                raise SystemExit(
                    f"setWebhook did not take. Telegram reports url="
                    f"{registered!r}, last error="
                    f"{(info.result or {}).get('last_error_message')!r}"
                )

            connection.status = ChannelConnectionStatus.ACTIVE
            db.add(connection)
            print(f"webhook registered: {full_url}")

        await db.commit()
        connection_id = connection.id

    print(
        f"\n{'created' if created else 'updated'} channel_connection id={connection_id}"
        f"\n  merchant : {merchant_name}"
        f"\n  shop     : {shop_name}"
        f"\n  bot      : {bot_name} (@{username})"
        f"\n  status   : {connection.status.value}"
    )
    if not webhook_url:
        print(
            f"\nNo webhook registered. When a tunnel is up, re-run with:"
            f"\n  --webhook-url https://<host>"
            f"\nTelegram will then deliver to https://<host>/webhooks/"
            f"{PROVIDER}/{connection_id}"
        )
    return connection_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help="BotFather token. Defaults to $TELEGRAM_BOT_TOKEN.",
    )
    parser.add_argument(
        "--webhook-url",
        help=(
            "Public https origin, e.g. https://abc.ngrok.io. The connection "
            "path is appended. Omit to create the rows without registering."
        ),
    )
    parser.add_argument("--merchant", default="Warung Budi")
    parser.add_argument("--shop", default="Budi Store")
    parser.add_argument("--bot", default="Budi Bot")
    args = parser.parse_args()

    if not args.token:
        parser.error("--token is required (or set TELEGRAM_BOT_TOKEN)")

    asyncio.run(
        seed(args.token, args.webhook_url, args.merchant, args.shop, args.bot)
    )


if __name__ == "__main__":
    main()
