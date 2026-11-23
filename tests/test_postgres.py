"""Prove sul database Postgres vero (stesso schema di Supabase).

Si eseguono solo se è impostata TEST_DATABASE_ADMIN_URL, per esempio:
TEST_DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1:54329/postgres
Il database di prova viene creato e cancellato ogni volta.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from app.db.postgres import PostgresRepository, create_pool
from app.db.repository import AlreadyLinkedError
from app.domain.codes import hash_code
from app.domain.models import ROLE_OWNER, ROLE_SALES
from app.services.control import ControlService
from app.services.linking import LinkingService, LinkOutcome
from app.services.settings_watch import SettingsWatcher

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL")
MIGRATIONS = sorted((Path(__file__).parent.parent / "supabase" / "migrations").glob("*.sql"))

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_DATABASE_ADMIN_URL non impostata")


@pytest.fixture
async def repo():
    name = f"checkio_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for migration in MIGRATIONS:
                conn.execute(migration.read_text())
        pool = create_pool(url)
        await pool.open(wait=True)
        try:
            yield PostgresRepository(pool), url
        finally:
            await pool.close()
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'drop database "{name}" with (force)')


async def test_schema_impostazioni_e_stato_iniziali(repo):
    repository, _ = repo
    settings = await repository.get_settings()
    state = await repository.get_state()
    assert settings.min_score == 60 and settings.zones == [] and settings.version == 1
    assert state.paused is True and state.mode == "misto"


async def test_flusso_collegamento_completo(repo):
    repository, _ = repo
    linking = LinkingService(repository, owner_setup_code="codice-avvio-123456")
    result = await linking.redeem(
        "codice-avvio-123456", telegram_user_id=1, chat_id=1, username="tit", display_name="Titolare"
    )
    assert result.outcome is LinkOutcome.OWNER_CREATED and result.member.role == ROLE_OWNER
    again = await linking.redeem(
        "codice-avvio-123456", telegram_user_id=2, chat_id=2, username=None, display_name="Altro"
    )
    assert again.outcome is LinkOutcome.USED

    issued = await linking.issue_code(issuer=result.member, name="Matteo")
    assert issued.created and issued.member.role == ROLE_SALES
    linked = await linking.redeem(issued.code, telegram_user_id=2, chat_id=2, username="matteo", display_name="M")
    assert linked.outcome is LinkOutcome.LINKED and linked.member.telegram_user_id == 2
    reused = await linking.redeem(issued.code, telegram_user_id=3, chat_id=3, username=None, display_name="X")
    assert reused.outcome is LinkOutcome.USED

    members = await repository.list_members()
    assert [m.name for m in members] == ["Titolare", "Matteo"]
    assert members[1].shifts["lun"] == [["09:00", "17:00"]]


async def test_codici_scaduti_impronta_e_unico_account(repo):
    repository, url = repo
    owner = await repository.create_member("Titolare", ROLE_OWNER, {})
    giulia = await repository.create_member("Giulia", ROLE_SALES, {})
    await repository.link_member_directly(owner.id, 10, 10, None)
    await repository.create_link_code(giulia.id, hash_code("ABCD-EFGH"), datetime.now(UTC) - timedelta(1), owner.id)
    linking = LinkingService(repository, owner_setup_code=None)
    expired = await linking.redeem("abcd efgh", telegram_user_id=11, chat_id=11, username=None, display_name="G")
    assert expired.outcome is LinkOutcome.EXPIRED
    # nel database c'è solo l'impronta del codice, mai il codice in chiaro
    with psycopg.connect(url) as conn:
        stored = conn.execute("select code_hash from link_codes").fetchone()[0]
    assert stored == hash_code("ABCD-EFGH") and "ABCD" not in stored
    with pytest.raises(AlreadyLinkedError):
        await repository.link_member_directly(giulia.id, 10, 10, None)


async def test_stato_e_versione_rilevati_dal_controllo(repo):
    repository, url = repo
    owner = await repository.create_member("Titolare", ROLE_OWNER, {})
    watcher = SettingsWatcher(repository)
    await watcher.load()
    control = ControlService(repository)
    state, changed = await control.set_paused(owner, False)
    assert changed and state.paused is False and state.version == 2 and state.updated_by == "Titolare"
    _, changed = await control.set_paused(owner, False)
    assert changed is False
    watcher.acknowledge_state(state)
    # modifica fatta da fuori (gestionale / editor Supabase)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("update finder_settings set min_score = 80, updated_by = 'gestionale' where id = 1")
        conn.execute("update finder_settings set min_score = 80 where id = 1")  # nessun cambiamento reale
    messages = await watcher.check()
    assert len(messages) == 1 and "Punteggio minimo: 60 → 80" in messages[0] and "da gestionale" in messages[0]
    assert await watcher.check() == []
    await repository.add_audit(owner.id, owner.name, "telegram", "prova", {"ok": True})
    with psycopg.connect(url) as conn:
        assert conn.execute("select count(*) from audit_log").fetchone()[0] >= 2


async def test_sicurezza_per_righe_attiva_su_tutte_le_tabelle(repo):
    _, url = repo
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
        ).fetchall()
    assert rows == []
