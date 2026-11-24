"""Telegram per le fasi 2-4: giri, /cerca, /analizza, schede e pulsanti."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from app.ai.client import AIError, BudgetExceeded
from app.db.repository import Repository
from app.domain.dedupe import listing_fingerprints
from app.domain.models import LeadFinder, Property
from app.domain.shifts import day_code
from app.integrations.google_places import platform_of
from app.integrations.website import _CIN
from app.services.analysis import AnalysisService
from app.services.keycheck import check_anthropic, check_google, format_statuses, google_mode
from app.services.messages import MessageService
from app.services.rounds import DetailsTest, RoundService

from . import cards

log = logging.getLogger(__name__)

URL = re.compile(r"https?://\S+", re.IGNORECASE)
MIN_PASTED_CHARS = 150
MIN_REVIEWS_CHARS = 80
REVIEWS_PROMPT = (
    "📝 Recensioni per «{name}»\n"
    "Apri l'annuncio su Booking o Airbnb (o la scheda Google Maps, il link è nella scheda), copia 3-5 recensioni "
    "(testo, voto e data se ci sono) "
    "e incollale qui in un unico messaggio, senza i nomi di chi le ha scritte.\n"
    "Rifaccio l'analisi e riscrivo i messaggi. Per lasciar perdere: /annulla"
)
PURGE_TIME = "03:15"


def deps(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return context.application.bot_data


async def member_names(repo: Repository) -> dict[str, str]:
    return {m.id: m.name for m in await repo.list_members()}


class TelegramNotifier:
    """Invia schede e riepiloghi su Telegram."""

    def __init__(self, bot: Any, repo: Repository) -> None:
        self.bot = bot
        self.repo = repo

    async def send_card(self, member: LeadFinder, prop: Property) -> tuple[int, int] | None:
        if not member.telegram_chat_id:
            return None
        state = await self.repo.get_state()
        try:
            message = await self.bot.send_message(
                member.telegram_chat_id,
                cards.card_text(prop, state.mode, member.name),
                parse_mode=ParseMode.HTML,
                reply_markup=cards.card_keyboard(prop),
                disable_web_page_preview=True,
            )
        except (Forbidden, TelegramError) as exc:
            log.warning("Scheda non consegnata a %s: %s", member.id, exc.__class__.__name__)
            return None
        return member.telegram_chat_id, message.message_id

    async def notify_owners(self, text: str) -> None:
        for member in await self.repo.list_members():
            if member.is_owner and member.is_active and member.telegram_chat_id:
                try:
                    await self.bot.send_message(member.telegram_chat_id, text, disable_web_page_preview=True)
                except TelegramError as exc:
                    log.warning("Riepilogo non consegnato a %s: %s", member.id, exc.__class__.__name__)


# ── Giri programmati ─────────────────────────────────────────
async def start_round(context: ContextTypes.DEFAULT_TYPE, trigger: str, requester: LeadFinder | None = None) -> bool:
    rounds: RoundService | None = deps(context).get("rounds")
    if rounds is None or rounds.lock.locked():
        return False
    job = rounds.run(trigger) if requester is None or requester.is_owner else _run_for(context, rounds, trigger, requester)
    context.application.create_task(job, name=f"giro-{trigger}")
    return True


async def _run_for(context: ContextTypes.DEFAULT_TYPE, rounds: RoundService, trigger: str, member: LeadFinder) -> None:
    """Giro avviato da un commerciale: il riepilogo completo va al titolare, a lui un esito breve."""
    report = await rounds.run(trigger)
    if report is None or not member.telegram_chat_id:
        return
    text = (
        f"✅ Giro finito: {report.new} strutture nuove, {report.analyzed} analizzate, "
        f"{report.proposed} schede inviate a chi è di turno."
    )
    if report.waiting:
        text += f" {report.waiting} aspettano qualcuno di turno."
    try:
        await context.bot.send_message(member.telegram_chat_id, text)
    except TelegramError as exc:
        log.warning("Esito del giro non consegnato a %s: %s", member.id, exc.__class__.__name__)


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ogni 30 secondi: parte un giro se è l'ora giusta; di notte la pulizia della memoria."""
    data = deps(context)
    repo: Repository = data["repo"]
    now = datetime.now(data["timezone"])
    hhmm = now.strftime("%H:%M")
    key = now.strftime("%Y-%m-%d ") + hhmm
    try:
        if hhmm == PURGE_TIME and data.get("last_purge") != now.date():
            data["last_purge"] = now.date()
            removed = await repo.purge_expired()
            if removed:
                log.info("Pulizia della memoria: %s strutture cancellate (restano le impronte).", removed)
        settings = await repo.get_settings()
        if hhmm not in settings.run_times or day_code(now) not in settings.run_days or data.get("last_round") == key:
            return
        data["last_round"] = key
        state = await repo.get_state()
        if state.paused:
            return
        await start_round(context, "programmato")
    except Exception:  # noqa: BLE001 - si riprova al prossimo controllo
        log.exception("Controllo dei giri non riuscito")


async def cerca(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    if deps(context).get("rounds") is None:
        await update.effective_message.reply_text("I giri non sono attivi su questo server.")
        return
    repo: Repository = deps(context)["repo"]
    if not member.is_owner and (await repo.get_state()).paused:
        await update.effective_message.reply_text("I giri sono in pausa: può riattivarli solo il titolare.")
        return
    if not await start_round(context, f"avviato da {member.name}", requester=member):
        await update.effective_message.reply_text("C'è già un giro in corso: aspetta che finisca.")
        return
    if member.is_owner:
        await update.effective_message.reply_text(
            "🛰 Giro avviato. Ti mando il riepilogo alla fine (circa 10-15 minuti); "
            "le schede arrivano a chi è di turno."
        )
        return
    await update.effective_message.reply_text(
        "🛰 Giro avviato. Ti scrivo quando è finito (circa 10-15 minuti); "
        "le schede arrivano a chi è di turno."
    )
    rounds: RoundService = deps(context)["rounds"]
    try:
        await rounds.notifier.notify_owners(f"🛰 {member.name} ha avviato un giro adesso.")
    except Exception:  # noqa: BLE001 - l'avviso non deve bloccare il giro
        log.exception("Avviso al titolare non inviato")


# ── /analizza ────────────────────────────────────────────────
ANALIZZA_USAGE = (
    "Incolla il link dell'annuncio e, sotto, il testo dell'annuncio o delle recensioni (copia e incolla dalla pagina). "
    "Il bot non apre Booking, Airbnb o Trivago: lavora solo su quello che incolli.\n\n"
    "Esempio:\n/analizza https://www.booking.com/hotel/it/esempio.html\nTesto dell'annuncio e recensioni…"
)


async def analizza(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    message = update.effective_message
    data = deps(context)
    analysis: AnalysisService | None = data.get("analysis")
    if analysis is None:
        await message.reply_text("Analisi AI non attiva: manca ANTHROPIC_API_KEY sul server.")
        return
    raw = (message.text or "").split(maxsplit=1)
    body = raw[1] if len(raw) > 1 else ""
    links = URL.findall(body)
    link = links[0].rstrip(").,;") if links else None
    text = URL.sub(" ", body).strip()
    if len(text) < MIN_PASTED_CHARS:
        await message.reply_text(ANALIZZA_USAGE)
        return
    cin_match = _CIN.search(text)
    cin = re.sub(r"\s", "", cin_match.group(0)).upper() if cin_match else None
    portal = platform_of(link) or "annuncio"
    prints = listing_fingerprints(link, cin)
    repo: Repository = data["repo"]
    if prints:
        property_id = await repo.insert_manual_property(
            f"Annuncio {portal}", {portal: link} if link else {}, prints, cin, member.id
        )
        if property_id is None:
            await message.reply_text("Questa struttura è già in memoria (stesso link o stesso CIN): non la ripropongo.")
            return
    else:
        property_id = await repo.insert_manual_property(f"Annuncio {portal}", {}, [], None, member.id)
    await message.reply_text("🧠 Analisi in corso: ti mando la scheda tra poco.")
    context.application.create_task(_run_pasted(context, member, property_id, text, link))


async def _run_pasted(
    context: ContextTypes.DEFAULT_TYPE, member: LeadFinder, property_id: str, text: str, link: str | None
) -> None:
    data = deps(context)
    repo: Repository = data["repo"]
    analysis: AnalysisService = data["analysis"]
    messages: MessageService | None = data.get("messages")
    chat_id = member.telegram_chat_id
    try:
        prop = await repo.get_property(property_id)
        prop = await analysis.analyze(prop, [], pasted_text=text, pasted_link=link, require_contacts=False)
        if prop.status == "analizzato" and messages is not None:
            await messages.write(prop, member.name)
            await repo.update_property(prop.id, status="proposto", assigned_to=member.id, proposed_at=datetime.now(UTC))
            await repo.add_property_event(
                prop.id, actor_id=member.id, actor_label=member.name, source="telegram", event_type="proposta",
                from_status="analizzato", to_status="proposto", details={"da": "/analizza"},
            )
            prop = await repo.get_property(prop.id)
        state = await repo.get_state()
        note = None
        if prop.status == "scartato":
            note = f"❌ Esclusa dall'analisi: {((prop.analysis or {}).get('esclusione') or {}).get('spiegazione', prop.discard_reason)}"
        sent = await context.bot.send_message(
            chat_id, cards.card_text(prop, state.mode, member.name, note), parse_mode=ParseMode.HTML,
            reply_markup=cards.card_keyboard(prop), disable_web_page_preview=True,
        )
        await repo.update_property(prop.id, telegram_chat_id=chat_id, telegram_message_id=sent.message_id)
    except BudgetExceeded as exc:
        await context.bot.send_message(chat_id, f"⚠️ {exc}")
    except (AIError, TelegramError) as exc:
        log.warning("Analisi incollata non riuscita: %s", exc)
        await context.bot.send_message(chat_id, "⚠️ Analisi non riuscita. Riprova tra poco.")


# ── Pulsanti delle schede ────────────────────────────────────
async def _refresh_card(context: ContextTypes.DEFAULT_TYPE, prop: Property, note: str | None = None) -> None:
    if not (prop.telegram_chat_id and prop.telegram_message_id):
        return
    repo: Repository = deps(context)["repo"]
    state = await repo.get_state()
    names = await member_names(repo)
    try:
        await context.bot.edit_message_text(
            cards.card_text(prop, state.mode, names.get(prop.assigned_to or ""), note),
            chat_id=prop.telegram_chat_id,
            message_id=prop.telegram_message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=cards.card_keyboard(prop),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            log.warning("Scheda non aggiornata: %s", exc)


async def _change(
    repo: Repository, prop: Property, member: LeadFinder, status: str, event: str, **fields: Any
) -> Property:
    await repo.update_property(prop.id, status=status, **fields)
    await repo.add_property_event(
        prop.id, actor_id=member.id, actor_label=member.name, source="telegram", event_type=event,
        from_status=prop.status, to_status=status, details={k: str(v) for k, v in fields.items() if k != "messages"},
    )
    return await repo.get_property(prop.id) or prop


ACTIVE = ("proposto", "approvato")


async def card_button(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    query = update.callback_query
    try:
        _, action, property_id = (query.data or "").split(":", 2)
    except ValueError:
        await query.answer()
        return
    repo: Repository = deps(context)["repo"]
    prop = await repo.get_property(property_id)
    if prop is None:
        await query.answer("Struttura non trovata.", show_alert=True)
        return
    if not member.is_owner and prop.assigned_to != member.id:
        await query.answer("Questa scheda è assegnata a un'altra persona.", show_alert=True)
        return
    now = datetime.now(UTC)

    if action == "em":
        await query.answer()
        await context.bot.send_message(query.message.chat_id, cards.email_text(prop), parse_mode=ParseMode.HTML)
        return
    if action == "tel":
        await query.answer()
        await context.bot.send_message(query.message.chat_id, cards.phone_text(prop), parse_mode=ParseMode.HTML)
        return
    if action == "ed":
        await query.answer()
        await context.bot.send_message(
            query.message.chat_id, f"Cosa vuoi modificare di «{prop.name}»?", reply_markup=cards.edit_choice_keyboard(prop)
        )
        return
    if action == "rv":
        if prop.status not in ACTIVE:
            await query.answer("Questa scheda è già chiusa.", show_alert=True)
            return
        context.user_data.pop("edit", None)
        context.user_data["reviews"] = prop.id
        await query.answer()
        await context.bot.send_message(query.message.chat_id, REVIEWS_PROMPT.format(name=prop.name))
        return
    if action in ("ew", "ee"):
        context.user_data.pop("reviews", None)
        context.user_data["edit"] = {"property_id": prop.id, "channel": "whatsapp" if action == "ew" else "email"}
        await query.answer()
        what = "del messaggio WhatsApp" if action == "ew" else "dell'email (solo il corpo, l'oggetto resta)"
        await context.bot.send_message(query.message.chat_id, f"Scrivi il nuovo testo {what}.\nPer lasciar perdere: /annulla")
        return

    if prop.status not in ACTIVE and action != "oo":
        await query.answer("Questa scheda è già chiusa.", show_alert=True)
        return
    if action == "ok":
        prop = await _change(repo, prop, member, "approvato", "approvata")
        await query.answer("Approvata")
    elif action == "no":
        prop = await _change(repo, prop, member, "scartato", "scartata", discard_reason="scartata_dal_team")
        await query.answer("Scartata")
    elif action == "pm":
        prop = await _change(repo, prop, member, "scartato", "gia_gestita", discard_reason="gestita_da_altri")
        await query.answer("Segnata come già gestita da altri")
    elif action == "oo":
        await repo.add_opt_out(prop.phone_normalized, prop.email_normalized, "chiesto dal team", member.id)
        prop = await _change(repo, prop, member, "perso", "opt_out", discard_reason="opt_out")
        await query.answer("Non verrà più contattata")
    elif action in ("sw", "se"):
        channel = "whatsapp" if action == "sw" else "email"
        prop = await _change(repo, prop, member, "contattato", "inviato", channel=channel, contacted_at=now)
        await query.answer("Segnato come inviato")
    else:
        await query.answer()
        return
    await _refresh_card(context, prop)


# ── Modifica dei testi ───────────────────────────────────────
async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> bool:
    """Se c'è una modifica (o un incolla di recensioni) in sospeso la gestisce e restituisce True."""
    pending_reviews = context.user_data.pop("reviews", None)
    if pending_reviews:
        await start_reviews(update, context, member, pending_reviews)
        return True
    pending = context.user_data.get("edit")
    if not pending:
        return False
    context.user_data.pop("edit", None)
    repo: Repository = deps(context)["repo"]
    prop = await repo.get_property(pending["property_id"])
    text = (update.effective_message.text or "").strip()
    if prop is None or not text:
        await update.effective_message.reply_text("Modifica annullata.")
        return True
    if not member.is_owner and prop.assigned_to != member.id:
        await update.effective_message.reply_text("Questa scheda è assegnata a un'altra persona.")
        return True
    messages = dict(prop.messages or {})
    if pending["channel"] == "whatsapp":
        messages["whatsapp"] = text[:2000]
    else:
        messages["email"] = {**(messages.get("email") or {}), "corpo": text[:5000]}
    await repo.update_property(prop.id, messages=messages, message_edited=True)
    await repo.add_property_event(
        prop.id, actor_id=member.id, actor_label=member.name, source="telegram", event_type="messaggio_modificato",
        details={"canale": pending["channel"]},
    )
    prop = await repo.get_property(prop.id)
    await _refresh_card(context, prop)
    await update.effective_message.reply_text("✅ Testo salvato. La scheda è aggiornata.")
    return True


async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    had_edit = context.user_data.pop("edit", None)
    had_reviews = context.user_data.pop("reviews", None)
    await update.effective_message.reply_text(
        "Modifica annullata." if had_edit or had_reviews else "Nessuna modifica in corso."
    )


# ── Recensioni incollate dal commerciale ─────────────────────
async def start_reviews(
    update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder, property_id: str
) -> None:
    message = update.effective_message
    data = deps(context)
    repo: Repository = data["repo"]
    text = (message.text or "").strip()
    prop = await repo.get_property(property_id)
    if prop is None or prop.status not in ACTIVE:
        await message.reply_text("La scheda è già chiusa: recensioni non usate.")
        return
    if not member.is_owner and prop.assigned_to != member.id:
        await message.reply_text("Questa scheda è assegnata a un'altra persona.")
        return
    if data.get("analysis") is None or data.get("messages") is None:
        await message.reply_text("Analisi AI non attiva: manca ANTHROPIC_API_KEY sul server.")
        return
    if len(text) < MIN_REVIEWS_CHARS:
        await message.reply_text(
            "Testo troppo corto: incolla almeno una recensione intera. Riprova dal pulsante «📝 Recensioni»."
        )
        return
    await message.reply_text("🧠 Rifaccio l'analisi con le recensioni: ti aggiorno la scheda tra poco.")
    context.application.create_task(apply_reviews(context, member, prop.id, text, message.chat_id))


async def apply_reviews(
    context: ContextTypes.DEFAULT_TYPE, member: LeadFinder, property_id: str, text: str, chat_id: int
) -> None:
    data = deps(context)
    repo: Repository = data["repo"]
    analysis: AnalysisService = data["analysis"]
    messages: MessageService = data["messages"]
    prop = await repo.get_property(property_id)
    if prop is None:
        return
    before, previous_status = prop.score, prop.status
    try:
        prop = await analysis.analyze(prop, [], pasted_text=text, pasted_kind="recensioni", require_contacts=False)
        await repo.add_property_event(
            prop.id, actor_id=member.id, actor_label=member.name, source="telegram", event_type="recensioni_aggiunte",
            details={"punteggio_prima": before, "punteggio_dopo": prop.score},
        )
        if prop.status == "scartato":
            why = ((prop.analysis or {}).get("esclusione") or {}).get("spiegazione") or prop.discard_reason
            await _refresh_card(context, prop, f"❌ Esclusa dopo le recensioni: {why}")
            await context.bot.send_message(chat_id, f"❌ «{prop.name}» esclusa dopo le recensioni: {why}")
            return
        await repo.update_property(prop.id, status=previous_status)
        if prop.status != "analizzato":  # analisi non riuscita: la scheda resta com'era
            await context.bot.send_message(chat_id, "⚠️ Analisi non riuscita: la scheda resta com'era. Riprova tra poco.")
            return
        sender = (await member_names(repo)).get(prop.assigned_to or "") or member.name
        prop = await repo.get_property(prop.id) or prop
        await messages.write(prop, sender, variant=prop.message_variant)
        prop = await repo.get_property(prop.id) or prop
        await _refresh_card(context, prop)
        await context.bot.send_message(
            chat_id,
            f"✅ Analisi di «{prop.name}» aggiornata con le recensioni: punteggio {before} → {prop.score}. "
            "Messaggi riscritti: li trovi nella scheda.",
        )
    except BudgetExceeded as exc:
        await repo.update_property(property_id, status=previous_status)
        await context.bot.send_message(chat_id, f"⚠️ {exc}")
    except (AIError, TelegramError) as exc:
        log.warning("Recensioni incollate non usate: %s", exc)
        await repo.update_property(property_id, status=previous_status)
        await context.bot.send_message(chat_id, "⚠️ Non sono riuscito ad aggiornare la scheda. Riprova tra poco.")



# ── Verifica delle chiavi (nessuna spesa) ────────────────────
async def run_key_check(app: Any) -> str:
    data = app.bot_data
    config = data["config"]
    statuses = [
        await check_anthropic(data.get("anthropic"), config.claude_model),
        await check_google(config.google_maps_api_key, data["http"]),
    ]
    settings = await data["repo"].get_settings()
    price_set = config.google_search_usd_per_1000 is not None
    await data["repo"].add_audit(
        None, "bot", "bot", "verifica_chiavi",
        {s.name: {"ok": s.ok, "esito": s.message} for s in statuses}
        | {"prezzo_google_impostato": price_set, "richieste_google_al_mese": settings.google_monthly_requests,
           "modello": config.claude_model},
    )
    return format_statuses(statuses, google_mode(price_set, settings.google_monthly_requests))


async def startup_key_check(app: Any) -> None:
    try:
        text = await run_key_check(app)
        await TelegramNotifier(app.bot, app.bot_data["repo"]).notify_owners(text)
    except Exception:  # noqa: BLE001 - la verifica non deve fermare il bot
        log.exception("Verifica delle chiavi non riuscita")


def format_details_test(t: DetailsTest) -> str:
    usage = f"\nRichieste Google del mese: {t.used} su {t.limit}." if t.limit else ""
    if t.outcome == "recensioni":
        return (
            f"✅ Prova della scheda singola (1 richiesta): Google manda le recensioni. Per «{t.name}» ne sono "
            f"arrivate {t.text} con testo.\nDa ora, prima di mandare una scheda, il bot legge le recensioni della "
            "struttura (1 richiesta ciascuna, dentro il tetto del mese) e rifà l'analisi." + usage
        )
    if t.outcome == "senza_testo":
        return (
            f"⚠️ Prova della scheda singola (1 richiesta): per «{t.name}» Google manda {t.raw} recensioni ma senza "
            "testo, quindi non servono all'analisi. Il bot non legge le schede singole. Per le strutture migliori "
            "potete incollare le recensioni col pulsante «📝 Recensioni» sulla scheda." + usage
        )
    if t.outcome == "nessuna":
        return (
            f"❌ Prova della scheda singola (1 richiesta): Google non manda le recensioni nemmeno qui (provato su "
            f"«{t.name}», che su Google ne ha {t.ratings}).\nIl bot continua senza: punteggio su voto, numero di "
            "recensioni, canali e sito. Per le strutture migliori potete incollarle voi col pulsante "
            "«📝 Recensioni» sulla scheda." + usage
        )
    if t.outcome == "errore":
        return f"❌ Prova non riuscita: Google ha risposto con un errore ({t.error}). Riprova con /verifica recensioni."
    if t.outcome == "limite":
        return f"➖ Richieste Google del mese finite ({t.used} su {t.limit}): nessuna prova fatta."
    if t.outcome == "nessuna_struttura":
        return "➖ Nessuna struttura in memoria con recensioni su Google: la prova si fa dopo il primo giro."
    if t.outcome == "giro_in_corso":
        return "⏳ C'è un giro in corso: riprova /verifica recensioni quando è finito."
    return "➖ Ricerca Google spenta: nessuna prova fatta."


async def run_details_test(app: Any) -> str:
    rounds: RoundService | None = app.bot_data.get("rounds")
    if rounds is None:
        return "➖ I giri non sono attivi su questo server: nessuna prova fatta."
    result = await rounds.test_details()
    if result.outcome in ("recensioni", "senza_testo", "nessuna", "errore"):
        await app.bot_data["repo"].add_audit(
            None, "bot", "bot", "prova_recensioni",
            {"esito": result.outcome, "struttura": result.name, "recensioni": result.raw, "con_testo": result.text},
        )
    return format_details_test(result)


async def startup_details_test(app: Any) -> None:
    """Una volta sola: se non c'è ancora nessuna lettura di schede singole, prova con 1 richiesta."""
    try:
        rounds: RoundService | None = app.bot_data.get("rounds")
        if rounds is None or rounds.places is None or await app.bot_data["repo"].recent_details_runs(1):
            return
        text = await run_details_test(app)
        await TelegramNotifier(app.bot, app.bot_data["repo"]).notify_owners(text)
    except Exception:  # noqa: BLE001 - la prova non deve fermare il bot
        log.exception("Prova delle recensioni non riuscita")


async def verifica(update: Update, context: ContextTypes.DEFAULT_TYPE, member: LeadFinder) -> None:
    if context.args and context.args[0].casefold().startswith("recension"):
        await update.effective_message.reply_text("🔎 Provo la scheda singola di Google (1 richiesta)…")
        await update.effective_message.reply_text(await run_details_test(context.application))
        return
    await update.effective_message.reply_text("🔑 Verifico le chiavi (senza spendere)…")
    await update.effective_message.reply_text(await run_key_check(context.application))
