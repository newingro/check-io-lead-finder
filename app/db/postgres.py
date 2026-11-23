"""Accesso al database Postgres (Supabase) dal server del bot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.domain.models import LeadFinder, Settings, State

from .repository import AlreadyLinkedError, CodeAlreadyUsedError, LinkTarget

MEMBER_COLUMNS = """id::text, name, role, telegram_user_id, telegram_chat_id, telegram_username, shifts,
    receives_cards, receives_daily_summary, is_active, linked_at"""


def create_pool(database_url: str) -> AsyncConnectionPool:
    # prepare_threshold=None: compatibile con il connection pooler di Supabase.
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"prepare_threshold": None, "row_factory": dict_row},
    )


def _member(row: dict[str, Any]) -> LeadFinder:
    return LeadFinder(**row)


class PostgresRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    # ── Persone ──────────────────────────────────────────────
    async def get_member_by_telegram(self, telegram_user_id: int) -> LeadFinder | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"select {MEMBER_COLUMNS} from lead_finders where telegram_user_id = %s", (telegram_user_id,)
            )
            row = await cur.fetchone()
        return _member(row) if row else None

    async def get_member_by_name(self, name: str) -> LeadFinder | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"select {MEMBER_COLUMNS} from lead_finders where lower(name) = lower(%s) order by created_at limit 1",
                (name.strip(),),
            )
            row = await cur.fetchone()
        return _member(row) if row else None

    async def list_members(self) -> list[LeadFinder]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"select {MEMBER_COLUMNS} from lead_finders order by role <> 'titolare', lower(name)"
            )
            rows = await cur.fetchall()
        return [_member(r) for r in rows]

    async def count_linked_owners(self) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select count(*) as n from lead_finders "
                "where role = 'titolare' and is_active and telegram_user_id is not null"
            )
            row = await cur.fetchone()
        return int(row["n"])

    async def create_member(self, name: str, role: str, shifts: dict[str, Any]) -> LeadFinder:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"insert into lead_finders (name, role, shifts) values (%s, %s, %s) returning {MEMBER_COLUMNS}",
                (name.strip(), role, Jsonb(shifts)),
            )
            row = await cur.fetchone()
        return _member(row)

    async def update_member_chat(self, member_id: str, chat_id: int, username: str | None) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "update lead_finders set telegram_chat_id = %s, telegram_username = %s "
                "where id = %s and (telegram_chat_id is distinct from %s or telegram_username is distinct from %s)",
                (chat_id, username, member_id, chat_id, username),
            )

    # ── Codici di collegamento ───────────────────────────────
    async def create_link_code(
        self, member_id: str, code_hash: str, expires_at: datetime, created_by: str | None
    ) -> None:
        async with self.pool.connection() as conn, conn.transaction():
            # Un solo codice valido per persona: i precedenti vengono annullati.
            await conn.execute(
                "update link_codes set used_at = now() where lead_finder_id = %s and used_at is null", (member_id,)
            )
            await conn.execute(
                "insert into link_codes (code_hash, lead_finder_id, expires_at, created_by) values (%s, %s, %s, %s)",
                (code_hash, member_id, expires_at, created_by),
            )

    async def find_link_code(self, code_hash: str) -> LinkTarget | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select id::text as code_id, lead_finder_id::text as member_id, expires_at, used_at "
                "from link_codes where code_hash = %s",
                (code_hash,),
            )
            code = await cur.fetchone()
            if code is None:
                return None
            cur = await conn.execute(
                f"select {MEMBER_COLUMNS} from lead_finders where id = %s", (code["member_id"],)
            )
            member = await cur.fetchone()
        return LinkTarget(
            code_id=code["code_id"],
            lead_finder=_member(member),
            expires_at=code["expires_at"],
            used_at=code["used_at"],
        )

    async def complete_link(
        self, code_id: str, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder:
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "update link_codes set used_at = now() where id = %s and used_at is null and expires_at > now() "
                "returning id",
                (code_id,),
            )
            if await cur.fetchone() is None:
                raise CodeAlreadyUsedError
            return await self._link(conn, member_id, telegram_user_id, chat_id, username)

    async def link_member_directly(
        self, member_id: str, telegram_user_id: int, chat_id: int, username: str | None
    ) -> LeadFinder:
        async with self.pool.connection() as conn, conn.transaction():
            return await self._link(conn, member_id, telegram_user_id, chat_id, username)

    async def _link(self, conn, member_id: str, telegram_user_id: int, chat_id: int, username: str | None):
        cur = await conn.execute(
            "select id from lead_finders where telegram_user_id = %s and id <> %s", (telegram_user_id, member_id)
        )
        if await cur.fetchone() is not None:
            raise AlreadyLinkedError
        cur = await conn.execute(
            f"update lead_finders set telegram_user_id = %s, telegram_chat_id = %s, telegram_username = %s, "
            f"linked_at = now(), is_active = true where id = %s returning {MEMBER_COLUMNS}",
            (telegram_user_id, chat_id, username, member_id),
        )
        return _member(await cur.fetchone())

    # ── Impostazioni e stato ─────────────────────────────────
    async def get_settings(self) -> Settings:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select zones, property_types, search_queries, min_score, cards_per_run, run_times, run_days, "
                "followup_days, max_followups, archive_after_days, max_call_attempts, call_retry_minutes, "
                "monthly_ai_budget_eur, monthly_search_budget_eur, data_retention_months, version, updated_by, "
                "updated_at from finder_settings where id = 1"
            )
            row = await cur.fetchone()
        return Settings(**row)

    async def get_state(self) -> State:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select paused, mode, version, updated_by, updated_at from finder_state where id = 1"
            )
            row = await cur.fetchone()
        return State(**row)

    async def update_state(self, *, paused: bool | None, mode: str | None, updated_by: str) -> State:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "update finder_state set paused = coalesce(%s, paused), mode = coalesce(%s, mode), "
                "updated_by = case when coalesce(%s, paused) is distinct from paused "
                "  or coalesce(%s, mode) is distinct from mode then %s else updated_by end "
                "where id = 1 returning paused, mode, version, updated_by, updated_at",
                (paused, mode, paused, mode, updated_by),
            )
            row = await cur.fetchone()
        return State(**row)

    # ── Registro ─────────────────────────────────────────────
    async def add_audit(
        self, actor_id: str | None, actor_label: str, source: str, action: str, details: dict[str, Any]
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into audit_log (actor_id, actor_label, source, action, details) values (%s, %s, %s, %s, %s)",
                (actor_id, actor_label, source, action, Jsonb(details)),
            )
