"""Avvio del bot CHECK-iO Lead Finder."""

from __future__ import annotations

import logging
from datetime import timedelta

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder

from app.bot import handlers
from app.config import Config
from app.db.postgres import PostgresRepository, create_pool
from app.domain.models import LeadFinder
from app.services.control import ControlService
from app.services.linking import LinkingService
from app.services.settings_watch import SettingsWatcher

log = logging.getLogger("checkio")

MEMBER_COMMANDS = [
    BotCommand("io", "Chi sono, ruolo e turni"),
    BotCommand("stato", "Giri attivi o in pausa"),
    BotCommand("aiuto", "Elenco dei comandi"),
]
OWNER_COMMANDS = MEMBER_COMMANDS + [
    BotCommand("codice", "Collega una persona: /codice Nome"),
    BotCommand("team", "Le persone del team"),
    BotCommand("pausa", "Metti in pausa i giri"),
    BotCommand("riprendi", "Riavvia i giri"),
    BotCommand("modalita", "telefonate / messaggi / misto"),
    BotCommand("impostazioni", "Impostazioni attuali"),
]
PUBLIC_COMMANDS = [
    BotCommand("start", "Inizia"),
    BotCommand("collega", "Collega il tuo Telegram: /collega CODICE"),
]


def setup_logging(level: str) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)
    # httpx registra gli indirizzi delle richieste, che contengono il token del bot: mai nei log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def set_member_commands(app: Application, member: LeadFinder) -> None:
    if not member.telegram_chat_id:
        return
    commands = OWNER_COMMANDS if member.is_owner else MEMBER_COMMANDS
    try:
        await app.bot.set_my_commands(commands, scope=BotCommandScopeChat(member.telegram_chat_id))
    except TelegramError as exc:
        log.warning("Menu comandi non aggiornato per %s: %s", member.id, exc.__class__.__name__)


def build_application(config: Config) -> Application:
    pool = create_pool(config.database_url)

    async def on_startup(app: Application) -> None:
        await pool.open(wait=True, timeout=30)
        repo = PostgresRepository(pool)
        watcher = SettingsWatcher(repo)
        await watcher.load()
        app.bot_data.update(
            repo=repo,
            timezone=config.timezone,
            watcher=watcher,
            control=ControlService(repo),
            linking=LinkingService(
                repo,
                owner_setup_code=config.owner_setup_code,
                code_ttl=timedelta(minutes=config.link_code_ttl_minutes),
            ),
            on_member_linked=set_member_commands,
        )
        await app.bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
        for member in await repo.list_members():
            if member.is_active and member.is_linked:
                await set_member_commands(app, member)
        app.job_queue.run_repeating(
            handlers.watch_settings, interval=config.settings_poll_seconds, first=config.settings_poll_seconds
        )
        if await repo.count_linked_owners() == 0:
            log.warning("Nessun titolare collegato: usa /collega con OWNER_SETUP_CODE.")
        log.info("Bot avviato (@%s).", app.bot.username)

    async def on_shutdown(app: Application) -> None:
        await pool.close()

    app = ApplicationBuilder().token(config.telegram_token).post_init(on_startup).post_shutdown(on_shutdown).build()
    handlers.register(app)
    return app


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    app = build_application(config)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
