"""Avvio del bot CHECK-iO Lead Finder."""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from psycopg_pool import PoolTimeout
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application, ApplicationBuilder

from app.ai.client import ClaudeJSON
from app.bot import handlers, leads
from app.config import Config, ConfigError
from app.db.postgres import PostgresRepository, create_pool
from app.domain.models import LeadFinder
from app.integrations.google_places import PlacesClient
from app.services.analysis import AnalysisService
from app.services.control import ControlService
from app.services.linking import LinkingService
from app.services.messages import MessageService
from app.services.pasted import PastedListingService
from app.services.radar import RadarService
from app.services.rounds import RoundService
from app.services.settings_watch import SettingsWatcher

log = logging.getLogger("checkio")

MEMBER_COMMANDS = [
    BotCommand("io", "Chi sono, ruolo e turni"),
    BotCommand("stato", "Giri attivi o in pausa"),
    BotCommand("cerca", "Fai partire un giro adesso"),
    BotCommand("analizza", "Analizza un annuncio: link + testo incollato"),
    BotCommand("annulla", "Annulla una modifica in corso"),
    BotCommand("aiuto", "Elenco dei comandi"),
]
OWNER_COMMANDS = MEMBER_COMMANDS + [
    BotCommand("verifica", "Controlla le chiavi, senza spendere"),
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


class StartupError(RuntimeError):
    """Problema di configurazione che impedisce l'avvio."""


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


def build_lead_services(app: Application, config: Config, repo: PostgresRepository) -> dict:
    """Ricerca, analisi e messaggi: si accendono solo con le chiavi nelle variabili del server."""
    http = httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=3)
    places = PlacesClient(config.google_maps_api_key, http) if config.google_maps_api_key else None
    analysis = messages = anthropic_client = None
    if config.anthropic_api_key:
        from anthropic import AsyncAnthropic

        anthropic_client = AsyncAnthropic(api_key=config.anthropic_api_key)
        ai = ClaudeJSON(
            repo, anthropic_client, model=config.claude_model, effort=config.claude_effort, eur_per_usd=config.eur_per_usd
        )
        analysis = AnalysisService(repo, ai)
        messages = MessageService(repo, ai)
    rounds = RoundService(
        repo,
        RadarService(repo),
        leads.TelegramNotifier(app.bot, repo),
        analysis=analysis,
        messages=messages,
        places=places,
        http=http,
        search_price_usd_per_1000=config.google_search_usd_per_1000,
        eur_per_usd=config.eur_per_usd,
        timezone=config.timezone,
    )
    log.info(
        "Ricerca Google: %s · prezzo: %s · analisi AI: %s (%s)",
        "attiva" if places else "spenta (manca GOOGLE_MAPS_API_KEY)",
        "impostato" if config.google_search_usd_per_1000 else "mancante (GOOGLE_TEXT_SEARCH_USD_PER_1000)",
        "attiva" if analysis else "spenta (manca ANTHROPIC_API_KEY)",
        config.claude_model,
    )
    pasted = None
    if analysis is not None:
        pasted = PastedListingService(
            repo, places, analysis.ai, search_price_usd_per_1000=config.google_search_usd_per_1000,
            eur_per_usd=config.eur_per_usd,
        )
    return {
        "http": http, "anthropic": anthropic_client, "analysis": analysis, "messages": messages, "rounds": rounds,
        "pasted": pasted,
    }


def build_application(config: Config) -> Application:
    pool = create_pool(config.database_url)

    async def on_startup(app: Application) -> None:
        try:
            await pool.open(wait=True, timeout=30)
        except PoolTimeout as exc:
            raise StartupError(
                "Impossibile collegarsi al database. Controlla DATABASE_URL: deve essere la stringa "
                "'Session pooler' di Supabase, con la password del database al posto di [YOUR-PASSWORD]."
            ) from exc
        repo = PostgresRepository(pool)
        watcher = SettingsWatcher(repo)
        await watcher.load()
        services = build_lead_services(app, config, repo)
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
            config=config,
            **services,
        )
        await app.bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
        for member in await repo.list_members():
            if member.is_active and member.is_linked:
                await set_member_commands(app, member)
        app.job_queue.run_repeating(
            handlers.watch_settings, interval=config.settings_poll_seconds, first=config.settings_poll_seconds
        )
        app.job_queue.run_repeating(leads.tick, interval=30, first=10)
        app.create_task(leads.startup_key_check(app), name="verifica-chiavi")
        app.create_task(leads.startup_details_test(app), name="prova-recensioni")
        if await repo.count_linked_owners() == 0:
            log.warning("Nessun titolare collegato: usa /collega con OWNER_SETUP_CODE.")
        log.info("Bot avviato (@%s).", app.bot.username)

    async def on_shutdown(app: Application) -> None:
        for name in ("http", "anthropic"):
            client = app.bot_data.get(name)
            if client is not None:
                await client.aclose() if name == "http" else await client.close()
        await pool.close()

    app = ApplicationBuilder().token(config.telegram_token).post_init(on_startup).post_shutdown(on_shutdown).build()
    handlers.register(app)
    return app


def main() -> None:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        setup_logging("INFO")
        log.error("Configurazione non valida: %s (Railway → Variables)", exc)
        raise SystemExit(1) from None
    setup_logging(config.log_level)
    log.info("Avvio del bot…")
    try:
        app = build_application(config)
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except InvalidToken:
        log.error("TELEGRAM_BOT_TOKEN non valido: copia di nuovo il token da @BotFather (Railway → Variables).")
        raise SystemExit(1) from None
    except StartupError as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
