"""Prove dei comandi Telegram con dati finti (nessuna rete)."""

from datetime import UTC, datetime, timedelta

from app.bot import handlers
from app.domain.codes import hash_code
from app.services.linking import AttemptLimiter

from .fakes import SETUP_CODE, World

OWNER_ID = 1001
MATTEO_ID = 2002
STRANGER_ID = 9999


async def setup_owner(world: World) -> None:
    replies = await world.send(handlers.collega, user_id=OWNER_ID, args=[SETUP_CODE], first_name="Titolare")
    assert "Sei il titolare" in replies[0]


async def link_matteo(world: World) -> str:
    replies = await world.send(handlers.codice, user_id=OWNER_ID, args=["Matteo"])
    code = replies[0].split(": ", 1)[1].split("\n")[0]
    replies = await world.send(handlers.collega, user_id=MATTEO_ID, args=[code], first_name="Matteo")
    assert replies[0].startswith("Fatto, Matteo")
    return code


async def test_sconosciuto_riceve_solo_messaggio_di_cortesia():
    world = World()
    for handler in (handlers.start, handlers.aiuto, handlers.stato, handlers.pausa, handlers.plain_text):
        replies = await world.send(handler, user_id=STRANGER_ID)
        assert "riservato al team CHECK-iO" in replies[0]
    assert world.repo.state.paused is True


async def test_primo_titolare_con_codice_di_avvio_una_sola_volta():
    world = World()
    await setup_owner(world)
    owner = await world.repo.get_member_by_telegram(OWNER_ID)
    assert owner.is_owner and owner.name == "Titolare"
    replies = await world.send(handlers.collega, user_id=STRANGER_ID, args=[SETUP_CODE])
    assert "già stato usato" in replies[0]
    assert await world.repo.get_member_by_telegram(STRANGER_ID) is None


async def test_collegamento_commerciale_con_codice_monouso():
    world = World()
    await setup_owner(world)
    code = await link_matteo(world)
    matteo = await world.repo.get_member_by_telegram(MATTEO_ID)
    assert matteo.role == "commerciale" and matteo.is_linked
    assert world.linked_hooks == ["Titolare", "Matteo"]
    # il titolare viene avvisato
    assert any("Matteo ha collegato" in text for _, text in world.bot.sent)
    # il codice non funziona una seconda volta
    replies = await world.send(handlers.collega, user_id=STRANGER_ID, args=[code])
    assert "già stato usato" in replies[0]
    # /io mostra ruolo e turni
    replies = await world.send(handlers.io, user_id=MATTEO_ID)
    assert "Ruolo: commerciale" in replies[0] and "lun–ven 09:00–17:00" in replies[0]


async def test_codice_scaduto_e_codice_sbagliato():
    world = World()
    await setup_owner(world)
    replies = await world.send(handlers.codice, user_id=OWNER_ID, args=["Giulia"])
    code = replies[0].split(": ", 1)[1].split("\n")[0]
    world.repo.codes[hash_code(code)]["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)
    replies = await world.send(handlers.collega, user_id=MATTEO_ID, args=[code])
    assert "scaduto" in replies[0]
    replies = await world.send(handlers.collega, user_id=MATTEO_ID, args=["ZZZZ-ZZZZ"])
    assert "non valido" in replies[0]


async def test_nuovo_codice_annulla_il_precedente():
    world = World()
    await setup_owner(world)
    first = (await world.send(handlers.codice, user_id=OWNER_ID, args=["Matteo"]))[0].split(": ", 1)[1][:9]
    second = (await world.send(handlers.codice, user_id=OWNER_ID, args=["Matteo"]))[0].split(": ", 1)[1][:9]
    assert first != second
    assert "già stato usato" in (await world.send(handlers.collega, user_id=MATTEO_ID, args=[first]))[0]
    assert "Fatto" in (await world.send(handlers.collega, user_id=MATTEO_ID, args=[second]))[0]


async def test_troppi_tentativi_bloccano_il_collegamento():
    world = World()
    world.app.bot_data["linking"].limiter = AttemptLimiter(max_failures=3)
    for _ in range(3):
        await world.send(handlers.collega, user_id=STRANGER_ID, args=["AAAA-AAAA"])
    replies = await world.send(handlers.collega, user_id=STRANGER_ID, args=[SETUP_CODE])
    assert "Troppi tentativi" in replies[0]


async def test_collegamento_solo_in_chat_privata():
    world = World()
    replies = await world.send(handlers.collega, user_id=OWNER_ID, args=[SETUP_CODE], chat_type="group")
    assert "chat privata" in replies[0]
    assert await world.repo.count_linked_owners() == 0


async def test_commerciale_non_usa_comandi_del_titolare():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    for handler in (handlers.pausa, handlers.riprendi, handlers.codice, handlers.team, handlers.impostazioni):
        replies = await world.send(handler, user_id=MATTEO_ID, args=["telefonate"])
        assert replies == ["Questo comando è riservato al titolare."]


async def test_pausa_riprendi_e_modalita():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    world.bot.sent.clear()
    assert "già in pausa" in (await world.send(handlers.pausa, user_id=OWNER_ID))[0]
    assert "riavviato i giri" in (await world.send(handlers.riprendi, user_id=OWNER_ID))[0]
    assert world.repo.state.paused is False and world.repo.state.updated_by == "Titolare"
    # Matteo viene avvisato, il titolare no (ha già la risposta)
    assert world.bot.sent == [(MATTEO_ID, "🔔 Titolare ha riavviato i giri ▶️.")]
    assert "Scegli una modalità" in (await world.send(handlers.modalita, user_id=OWNER_ID, args=["boh"]))[0]
    assert "telefonate" in (await world.send(handlers.modalita, user_id=OWNER_ID, args=["Telefonate"]))[0]
    assert world.repo.state.mode == "telefonate"
    actions = [entry["action"] for entry in world.repo.audit]
    assert "ripresa" in actions and "modalita" in actions
    # Il controllo periodico non ripete avvisi già dati dal bot
    assert await world.app.bot_data["watcher"].check() == []


async def test_impostazioni_cambiate_dal_gestionale_vengono_segnalate_una_volta():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    watcher = world.app.bot_data["watcher"]
    await watcher.load()
    world.repo.change_settings(min_score=75, zones=[{"nome": "Abetone", "raggio_km": 15}], updated_by="gestionale")
    world.bot.sent.clear()
    context = type("C", (), {"application": world.app, "bot": world.bot})()
    await handlers.watch_settings(context)
    assert len(world.bot.sent) == 2  # titolare e Matteo
    text = world.bot.sent[0][1]
    assert "Impostazioni aggiornate da gestionale" in text and "Punteggio minimo: 60 → 75" in text
    world.bot.sent.clear()
    await handlers.watch_settings(context)
    assert world.bot.sent == []


async def test_stato_impostazioni_team_e_aiuto():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    assert "Giri: ⏸ in pausa" in (await world.send(handlers.stato, user_id=MATTEO_ID))[0]
    text = (await world.send(handlers.impostazioni, user_id=OWNER_ID))[0]
    assert "Punteggio minimo: 60" in text and "Zone: nessuna" in text
    team = (await world.send(handlers.team, user_id=OWNER_ID))[0]
    assert "Titolare — titolare, collegato" in team and "Matteo — commerciale, collegato" in team
    assert "/codice" in (await world.send(handlers.aiuto, user_id=OWNER_ID))[0]
    assert "/codice" not in (await world.send(handlers.aiuto, user_id=MATTEO_ID))[0]
    assert "Comando non riconosciuto" in (await world.send(handlers.unknown_command, user_id=MATTEO_ID))[0]


async def test_stesso_telegram_non_collegabile_a_due_persone():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    replies = await world.send(handlers.codice, user_id=OWNER_ID, args=["Giulia"])
    code = replies[0].split(": ", 1)[1].split("\n")[0]
    replies = await world.send(handlers.collega, user_id=MATTEO_ID, args=[code])
    assert "già collegato a un'altra persona" in replies[0]


async def test_cerca_anche_per_i_commerciali_con_pausa_e_avviso_al_titolare():
    from types import SimpleNamespace

    from app.services.rounds import RoundReport

    world = World()
    await setup_owner(world)
    await link_matteo(world)  # Matteo è commerciale
    owners_alerts: list[str] = []
    started: list[str] = []
    locked = {"value": False}

    class Notifier:
        async def notify_owners(self, text: str) -> None:
            owners_alerts.append(text)

    class Rounds:
        notifier = Notifier()
        lock = SimpleNamespace(locked=lambda: locked["value"])

        async def run(self, trigger: str) -> RoundReport:
            started.append(trigger)
            return RoundReport(trigger=trigger, started_at=datetime.now(UTC), new=3, analyzed=2, proposed=1)

    created: list = []
    world.app.bot_data["rounds"] = Rounds()
    world.app.create_task = lambda coro, name=None: created.append(coro)

    # in pausa il commerciale non può far partire giri
    assert world.repo.state.paused is True
    assert "in pausa" in (await world.send(handlers.cerca, user_id=MATTEO_ID))[0]
    assert created == []

    await world.send(handlers.riprendi, user_id=OWNER_ID)
    world.bot.sent.clear()
    replies = await world.send(handlers.cerca, user_id=MATTEO_ID)
    assert "Giro avviato" in replies[0] and "Ti scrivo quando è finito" in replies[0]
    assert owners_alerts == ["🛰 Matteo ha avviato un giro adesso."]
    await created.pop()
    assert started == ["avviato da Matteo"]
    assert world.bot.sent == [
        (MATTEO_ID, "✅ Giro finito: 3 strutture nuove, 2 analizzate, 1 schede inviate a chi è di turno.")
    ]

    # un giro alla volta
    locked["value"] = True
    assert "già un giro in corso" in (await world.send(handlers.cerca, user_id=MATTEO_ID))[0]
    locked["value"] = False

    # il titolare può avviarlo anche in pausa e riceve il riepilogo completo (dal giro stesso)
    await world.send(handlers.pausa, user_id=OWNER_ID)
    replies = await world.send(handlers.cerca, user_id=OWNER_ID)
    assert "Ti mando il riepilogo" in replies[0]
    await created.pop()
    assert started[-1] == "avviato da Titolare" and len(owners_alerts) == 1


async def test_aiuto_del_commerciale_mostra_cerca():
    world = World()
    await setup_owner(world)
    await link_matteo(world)
    text = (await world.send(handlers.aiuto, user_id=MATTEO_ID))[0]
    assert "/cerca" in text and "/codice" not in text
