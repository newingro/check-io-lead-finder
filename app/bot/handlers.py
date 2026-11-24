"""Comandi Telegram della fase 1."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from telegram import Update
from telegram.constants import ChatType
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.db.repository import Repository
from app.domain.models import MODES, ROLE_OWNER, ROLE_SALES, LeadFinder
from app.domain.settings_view import format_settings, format_state, zone_label
from app.domain.shifts import format_shifts
from app.services.control import ControlService
from app.services.linking import LinkingService, LinkOutcome
from app.services.settings_watch import SettingsWatcher

from . import leads, texts

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
MemberHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE, LeadFinder], Awaitable[None]]


def deps(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return context.application.bot_data


async def reply(update: Update, text: str) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, disable_web_page_preview=True)


async def current_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> LeadFinder | None:
    user = update.effective_user
    if user is None:
        return None
    repo: Repository = deps(context)["repo"]
    member = await repo.get_member_by_telegram(user.id)
    if member is not None and update.effective_chat is not None:
        chat_id = update.effective_chat.id
        if member.telegram_chat_id != chat_id or member.telegram_username != user.username:
            await repo.update_member_chat(member.id, chat_id, user.username)
    return member


def members_only(func: MemberHandler) -> Handler:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        member = await current_member(update, context)
        if member is None:
            await reply(update, texts.NOT_MEMBER)
            return
        if not member.is_active:
            await reply(update, texts.SUSPENDED)
            return
        await func(update, context, member)

    return wrapper


def owner_only(func: MemberHandler) -> Handler:
    @members_only
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
        if not member.is_owner:
            await reply(update, texts.OWNER_ONLY)
            return
        await func(update, context, member)

    return wrapper


async def notify_members(
    context: ContextTypes.DEFAULT_TYPE, text: str, *, exclude_member_id: str | None = None
) -> int:
    """Invia un avviso a tutte le persone attive collegate. Restituisce quante l'hanno ricevuto."""
    repo: Repository = deps(context)["repo"]
    sent = 0
    for member in await repo.list_members():
        if not (member.is_active and member.telegram_chat_id) or member.id == exclude_member_id:
            continue
        try:
            await context.bot.send_message(member.telegram_chat_id, text, disable_web_page_preview=True)
            sent += 1
        except Forbidden:
            log.warning("Avviso non consegnato: la persona %s ha bloccato il bot", member.id)
        except TelegramError as exc:
            log.warning("Avviso non consegnato a %s: %s", member.id, exc.__class__.__name__)
    return sent


# ── Comandi per tutti ────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = await current_member(update, context)
    if member is None:
        await reply(update, texts.NOT_MEMBER)
        return
    await reply(update, f"Ciao {member.name}! Sei collegato come {member.role}.\n\n" + help_text(member))


def help_text(member: LeadFinder) -> str:
    return texts.HELP_MEMBER + (texts.HELP_OWNER if member.is_owner else "")


@members_only
async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    await reply(update, help_text(member))


async def collega(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return
    if chat.type != ChatType.PRIVATE:
        await reply(update, "Per sicurezza il collegamento si fa solo in chat privata con il bot.")
        return
    if not context.args:
        await reply(update, texts.COLLEGA_USAGE)
        return
    linking: LinkingService = deps(context)["linking"]
    result = await linking.redeem(
        " ".join(context.args),
        telegram_user_id=user.id,
        chat_id=chat.id,
        username=user.username,
        display_name=user.first_name or "",
    )
    if result.outcome in (LinkOutcome.LINKED, LinkOutcome.OWNER_CREATED) and result.member is not None:
        member = result.member
        intro = "Sei il titolare di CHECK-iO Lead Finder. " if result.outcome is LinkOutcome.OWNER_CREATED else ""
        await reply(
            update,
            f"Fatto, {member.name}: il tuo Telegram è collegato. {intro}\nRuolo: {member.role}\n"
            f"Turni: {format_shifts(member.shifts)}\n\n" + help_text(member),
        )
        await on_member_linked(context, member)
        return
    await reply(update, texts.LINK_MESSAGES[result.outcome.value])


async def on_member_linked(context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    hook = deps(context).get("on_member_linked")
    if hook is not None:
        await hook(context.application, member)
    await notify_members(
        context, f"👋 {member.name} ha collegato il proprio Telegram ({member.role}).", exclude_member_id=member.id
    )


@members_only
async def io(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    tz = deps(context)["timezone"]
    since = member.linked_at.astimezone(tz).strftime("%d/%m/%Y") if member.linked_at else "—"
    await reply(
        update,
        f"👤 {member.name}\nRuolo: {member.role}\nTurni: {format_shifts(member.shifts)}\nCollegato dal: {since}",
    )


@members_only
async def stato(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    repo: Repository = deps(context)["repo"]
    state = await repo.get_state()
    settings = await repo.get_settings()
    zones = [zone_label(z) for z in settings.zones if z.get("attiva", True)]
    lines = [
        "📊 Stato del Lead Finder",
        format_state(state),
        f"• Zone attive: {', '.join(zones) if zones else 'nessuna (da impostare dal gestionale)'}",
        f"• Giri: {', '.join(settings.run_days)} alle {', '.join(settings.run_times)}",
        f"• Punteggio minimo: {settings.min_score}",
    ]
    await reply(update, "\n".join(lines))


# ── Comandi del titolare ─────────────────────────────────────
@owner_only
async def codice(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    args = list(context.args or [])
    role = ROLE_SALES
    if args and args[-1].casefold() in (ROLE_OWNER, ROLE_SALES):
        role = args.pop().casefold()
    name = " ".join(args).strip()
    if not name or len(name) > 80:
        await reply(update, texts.CODICE_USAGE)
        return
    linking: LinkingService = deps(context)["linking"]
    issued = await linking.issue_code(issuer=member, name=name, role=role)
    tz = deps(context)["timezone"]
    expires = issued.expires_at.astimezone(tz).strftime("%H:%M")
    bot_name = f"@{context.bot.username}" if context.bot.username else "il bot"
    notes = []
    if not issued.created and issued.member.role != role:
        notes.append(f"Nota: {issued.member.name} esiste già con ruolo {issued.member.role} (ruolo invariato).")
    if issued.was_linked:
        notes.append("Nota: è già collegato; il nuovo codice sostituirà il Telegram attuale.")
    await reply(
        update,
        f"Codice per {issued.member.name} ({issued.member.role}): {issued.code}\n"
        f"Valido fino alle {expires}, una sola volta.\n\n"
        f"Inoltra a {issued.member.name} queste istruzioni:\n"
        f"Apri {bot_name} su Telegram e scrivi:\n/collega {issued.code}"
        + ("\n\n" + "\n".join(notes) if notes else ""),
    )


@owner_only
async def team(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    repo: Repository = deps(context)["repo"]
    lines = ["👥 Team"]
    for person in await repo.list_members():
        status = "collegato" if person.is_linked else "in attesa di collegamento"
        if not person.is_active:
            status = "sospeso"
        lines.append(f"• {person.name} — {person.role}, {status}\n  Turni: {format_shifts(person.shifts)}")
    await reply(update, "\n".join(lines) if len(lines) > 1 else "Nessuna persona registrata.")


async def _set_paused(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder, paused: bool) -> None:
    control: ControlService = deps(context)["control"]
    watcher: SettingsWatcher = deps(context)["watcher"]
    state, changed = await control.set_paused(member, paused)
    watcher.acknowledge_state(state)
    if not changed:
        await reply(update, "I giri sono già in pausa." if paused else "I giri sono già attivi.")
        return
    action = "messo in pausa i giri ⏸" if paused else "riavviato i giri ▶️"
    await reply(update, f"Fatto: hai {action}.")
    await notify_members(context, f"🔔 {member.name} ha {action}.", exclude_member_id=member.id)


@owner_only
async def pausa(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    await _set_paused(update, context, member, True)


@owner_only
async def riprendi(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    await _set_paused(update, context, member, False)


@owner_only
async def modalita(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    args = context.args or []
    mode = args[0].casefold() if args else ""
    if mode not in MODES:
        await reply(update, texts.MODALITA_USAGE)
        return
    control: ControlService = deps(context)["control"]
    watcher: SettingsWatcher = deps(context)["watcher"]
    state, changed = await control.set_mode(member, mode)
    watcher.acknowledge_state(state)
    if not changed:
        await reply(update, f"La modalità è già: {mode}.")
        return
    await reply(update, f"Fatto: modalità impostata su {mode}.")
    await notify_members(context, f"🔔 {member.name} ha impostato la modalità: {mode}.", exclude_member_id=member.id)


@owner_only
async def impostazioni(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    repo: Repository = deps(context)["repo"]
    settings = await repo.get_settings()
    state = await repo.get_state()
    await reply(
        update,
        "⚙️ Impostazioni attuali\n"
        + format_state(state)
        + "\n"
        + format_settings(settings)
        + "\n\nSi modificano dal gestionale: il bot le rilegge da solo ogni pochi minuti.",
    )


# ── Messaggi non riconosciuti ────────────────────────────────
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = await current_member(update, context)
    await reply(update, texts.UNKNOWN_COMMAND if member else texts.NOT_MEMBER)


async def plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = await current_member(update, context)
    if member is not None and member.is_active and await leads.save_edit(update, context, member):
        return
    await reply(update, texts.ONLY_COMMANDS if member else texts.NOT_MEMBER)


cerca = owner_only(leads.cerca)
analizza = members_only(leads.analizza)
annulla = members_only(leads.annulla)
verifica = owner_only(leads.verifica)


async def card_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = await current_member(update, context)
    if member is None or not member.is_active:
        await update.callback_query.answer("Non sei abilitato a usare questa scheda.", show_alert=True)
        return
    await leads.card_button(update, context, member)


async def watch_settings(context: ContextTypes.DEFAULT_TYPE) -> None:
    watcher: SettingsWatcher = deps(context)["watcher"]
    try:
        messages = await watcher.check()
    except Exception:  # noqa: BLE001 - il controllo si ripete al giro successivo
        log.exception("Lettura delle impostazioni non riuscita")
        return
    for message in messages:
        await notify_members(context, message)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Errore non gestito", exc_info=context.error)
    if isinstance(update, Update):
        try:
            await reply(update, texts.GENERIC_ERROR)
        except TelegramError:
            pass


def register(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", start, filters=private))
    app.add_handler(CommandHandler("aiuto", aiuto, filters=private))
    app.add_handler(CommandHandler("help", aiuto, filters=private))
    app.add_handler(CommandHandler("collega", collega))
    app.add_handler(CommandHandler("io", io, filters=private))
    app.add_handler(CommandHandler("stato", stato, filters=private))
    app.add_handler(CommandHandler("codice", codice, filters=private))
    app.add_handler(CommandHandler("team", team, filters=private))
    app.add_handler(CommandHandler("pausa", pausa, filters=private))
    app.add_handler(CommandHandler("riprendi", riprendi, filters=private))
    app.add_handler(CommandHandler("modalita", modalita, filters=private))
    app.add_handler(CommandHandler("impostazioni", impostazioni, filters=private))
    app.add_handler(CommandHandler("cerca", cerca, filters=private))
    app.add_handler(CommandHandler("analizza", analizza, filters=private))
    app.add_handler(CommandHandler("annulla", annulla, filters=private))
    app.add_handler(CommandHandler("verifica", verifica, filters=private))
    app.add_handler(CallbackQueryHandler(card_button, pattern=r"^c:"))
    app.add_handler(MessageHandler(private & filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, plain_text))
    app.add_error_handler(on_error)
