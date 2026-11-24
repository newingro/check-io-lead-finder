"""Accesso al database Postgres (Supabase) dal server del bot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.domain.dedupe import Candidate, normalize_email, normalize_phone
from app.domain.models import OPEN_STATUSES, LeadFinder, Property, Settings, State
from app.domain.radar import CellMemory

from .repository import AlreadyLinkedError, CodeAlreadyUsedError, LinkTarget

MEMBER_COLUMNS = """id::text, name, role, telegram_user_id, telegram_chat_id, telegram_username, shifts,
    receives_cards, receives_daily_summary, is_active, linked_at"""

PROPERTY_COLUMNS = """id::text, name, status, property_type, address, zone, provincia, latitude, longitude, phone,
    phone_normalized, email, email_normalized, website, cin, google_place_id, ratings, listing_urls, owner_type,
    analysis, score, coalesce(score_reasons, '{}') as score_reasons, assigned_to::text, messages, message_variant,
    channel, website_check, discard_reason, source, search_query, times_seen, telegram_chat_id, telegram_message_id,
    message_edited, created_at, contacted_at"""

UPDATABLE_PROPERTY_COLUMNS = {
    "name", "status", "property_type", "email", "email_normalized", "cin", "listing_urls", "owner_type", "analysis",
    "score", "score_reasons", "assigned_to", "messages", "message_variant", "channel", "website_check",
    "discard_reason", "analyzed_at", "proposed_at", "telegram_chat_id", "telegram_message_id", "message_edited",
    "contacted_at", "archived_at",
}


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
                "updated_at, searches_per_run, google_monthly_requests from finder_settings where id = 1"
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

    # ── Radar: province e memoria delle ricerche ─────────────
    async def province_cells(self, codes: list[str]) -> dict[str, list[str]]:
        if not codes:
            return {}
        async with self.pool.connection() as conn:
            cur = await conn.execute("select codice, celle from province where codice = any(%s)", (codes,))
            rows = await cur.fetchall()
        return {row["codice"]: list(row["celle"]) for row in rows}

    async def province_for_cells(self, cells: list[str]) -> dict[str, str]:
        if not cells:
            return {}
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select c as cell, min(codice) as codice from province, unnest(celle) as c "
                "where c = any(%s) group by c",
                (cells,),
            )
            rows = await cur.fetchall()
        return {row["cell"]: row["codice"] for row in rows}

    async def get_cell_memory(self, cells: list[str], queries: list[str]) -> dict[tuple[str, str], CellMemory]:
        if not cells or not queries:
            return {}
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select cell, query, searches, last_searched_at, empty_streak, rest_until, last_results, last_new "
                "from search_cells where cell = any(%s) and query = any(%s)",
                (cells, queries),
            )
            rows = await cur.fetchall()
        return {(row["cell"], row["query"]): CellMemory(**row) for row in rows}

    async def save_cell_memory(self, memory: CellMemory, results: int, new: int) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into search_cells (cell, query, searches, results_total, new_total, last_results, last_new, "
                "  empty_streak, first_searched_at, last_searched_at, rest_until) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (cell, query) do update set searches = excluded.searches, "
                "  results_total = search_cells.results_total + excluded.results_total, "
                "  new_total = search_cells.new_total + excluded.new_total, "
                "  last_results = excluded.last_results, last_new = excluded.last_new, "
                "  empty_streak = excluded.empty_streak, last_searched_at = excluded.last_searched_at, "
                "  rest_until = excluded.rest_until",
                (
                    memory.cell, memory.query, memory.searches, results, new, memory.last_results, memory.last_new,
                    memory.empty_streak, memory.last_searched_at, memory.last_searched_at, memory.rest_until,
                ),
            )

    # ── Memoria delle strutture ──────────────────────────────
    async def find_fingerprints(self, prints: list[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
        if not prints:
            return {}
        kinds, hashes = [k for k, _ in prints], [h for _, h in prints]
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select f.kind, f.hash, f.property_id::text as property_id from property_fingerprints f "
                "join unnest(%s::text[], %s::text[]) as u(kind, hash) using (kind, hash)",
                (kinds, hashes),
            )
            rows = await cur.fetchall()
        return {(row["kind"], row["hash"]): row["property_id"] for row in rows}

    async def touch_property(self, property_id: str | None, prints: list[tuple[str, str]]) -> None:
        kinds, hashes = [k for k, _ in prints], [h for _, h in prints]
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "update property_fingerprints f set last_seen_at = now(), times_seen = f.times_seen + 1 "
                "from unnest(%s::text[], %s::text[]) as u(kind, hash) where f.kind = u.kind and f.hash = u.hash",
                (kinds, hashes),
            )
            # Impronte nuove della stessa struttura (es. ora ha anche il telefono): si aggiungono.
            await conn.execute(
                "insert into property_fingerprints (kind, hash, property_id) "
                "select kind, hash, %s from unnest(%s::text[], %s::text[]) as u(kind, hash) "
                "on conflict (kind, hash) do nothing",
                (property_id, kinds, hashes),
            )
            if property_id:
                await conn.execute(
                    "update properties set times_seen = times_seen + 1, last_seen_at = now() where id = %s",
                    (property_id,),
                )

    async def is_opted_out(self, phone: str | None, email: str | None) -> bool:
        if not phone and not email:
            return False
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select exists (select 1 from opt_out where (%s::text is not null and phone_normalized = %s) "
                "or (%s::text is not null and email_normalized = %s)) as found",
                (phone, phone, email, email),
            )
            row = await cur.fetchone()
        return bool(row["found"])

    async def insert_property(
        self,
        candidate: Candidate,
        prints: list[tuple[str, str]],
        *,
        cell: str,
        provincia: str | None,
        zone: str,
        query: str,
    ) -> str | None:
        kinds, hashes = [k for k, _ in prints], [h for _, h in prints]
        try:
            async with self.pool.connection() as conn, conn.transaction():
                cur = await conn.execute(
                    "insert into properties (name, property_type, address, zone, latitude, longitude, cin, "
                    "  google_place_id, listing_urls, website, phone, phone_normalized, email, email_normalized, "
                    "  ratings, source, cell, provincia, search_query) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'google_places', %s, %s, %s) "
                    "returning id::text as id",
                    (
                        candidate.name, candidate.property_type, candidate.address, zone, candidate.latitude,
                        candidate.longitude, candidate.cin, candidate.google_place_id, Jsonb(candidate.listing_urls),
                        candidate.website, candidate.phone, normalize_phone(candidate.phone), candidate.email,
                        normalize_email(candidate.email), Jsonb(candidate.ratings), cell, provincia, query,
                    ),
                )
                property_id = (await cur.fetchone())["id"]
                cur = await conn.execute(
                    "insert into property_fingerprints (kind, hash, property_id) "
                    "select kind, hash, %s from unnest(%s::text[], %s::text[]) as u(kind, hash) "
                    "on conflict (kind, hash) do nothing returning kind",
                    (property_id, kinds, hashes),
                )
                if len(await cur.fetchall()) < len(prints):
                    # Qualcun altro l'ha salvata nel frattempo: è già in memoria.
                    raise _AlreadyKnown
                await conn.execute(
                    "insert into property_events (property_id, actor_label, source, event_type, to_status, details) "
                    "values (%s, 'bot', 'bot', 'trovata', 'nuovo', %s)",
                    (property_id, Jsonb({"zona": zone, "cella": cell, "ricerca": query})),
                )
        except (_AlreadyKnown, errors.UniqueViolation):
            return None
        return property_id

    async def purge_expired(self) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute("select public.pulisci_memoria() as removed")
            row = await cur.fetchone()
        return int(row["removed"])


    # ── Strutture ────────────────────────────────────────────
    async def get_property(self, property_id: str) -> Property | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(f"select {PROPERTY_COLUMNS} from properties where id = %s", (property_id,))
            row = await cur.fetchone()
        return Property(**row) if row else None

    async def properties_by_status(self, status: str, limit: int) -> list[Property]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"select {PROPERTY_COLUMNS} from properties where status = %s and archived_at is null "
                "order by created_at limit %s",
                (status, limit),
            )
            rows = await cur.fetchall()
        return [Property(**row) for row in rows]

    async def update_property(self, property_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - UPDATABLE_PROPERTY_COLUMNS
        if unknown:
            raise ValueError(f"Colonne non modificabili: {sorted(unknown)}")
        names = sorted(fields)
        assignments = ", ".join(f"{name} = %s" for name in names)
        values = [Jsonb(fields[n]) if isinstance(fields[n], dict) else fields[n] for n in names]
        async with self.pool.connection() as conn:
            await conn.execute(f"update properties set {assignments} where id = %s", (*values, property_id))

    async def add_property_event(
        self,
        property_id: str,
        *,
        actor_id: str | None,
        actor_label: str,
        source: str,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into property_events (property_id, actor_id, actor_label, source, event_type, from_status, "
                "to_status, details) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (property_id, actor_id, actor_label, source, event_type, from_status, to_status, Jsonb(details or {})),
            )

    async def proposal_candidates(self, min_score: int, limit: int) -> list[Property]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"select {PROPERTY_COLUMNS} from properties where status = 'analizzato' and assigned_to is null "
                "and archived_at is null and score >= %s order by score desc, created_at limit %s",
                (min_score, limit),
            )
            rows = await cur.fetchall()
        return [Property(**row) for row in rows]

    async def open_assignments(self) -> dict[str, int]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select assigned_to::text as member, count(*) as n from properties "
                "where assigned_to is not null and status = any(%s) group by assigned_to",
                (list(OPEN_STATUSES),),
            )
            rows = await cur.fetchall()
        return {row["member"]: int(row["n"]) for row in rows}

    async def add_opt_out(self, phone: str | None, email: str | None, reason: str, member_id: str | None) -> None:
        if not phone and not email:
            return
        async with self.pool.connection() as conn, conn.transaction():
            if phone:
                await conn.execute(
                    "insert into opt_out (phone_normalized, reason, created_by) values (%s, %s, %s) "
                    "on conflict (phone_normalized) where phone_normalized is not null do nothing",
                    (phone, reason, member_id),
                )
            if email:
                await conn.execute(
                    "insert into opt_out (email_normalized, reason, created_by) values (%s, %s, %s) "
                    "on conflict (email_normalized) where email_normalized is not null do nothing",
                    (email, reason, member_id),
                )

    async def insert_manual_property(
        self, name: str, listing_urls: dict[str, str], prints: list[tuple[str, str]], cin: str | None, member_id: str
    ) -> str | None:
        kinds, hashes = [k for k, _ in prints], [h for _, h in prints]
        try:
            async with self.pool.connection() as conn, conn.transaction():
                cur = await conn.execute(
                    "insert into properties (name, listing_urls, cin, source, assigned_to) "
                    "values (%s, %s, %s, 'link_incollato', %s) returning id::text as id",
                    (name, Jsonb(listing_urls), cin, member_id),
                )
                property_id = (await cur.fetchone())["id"]
                cur = await conn.execute(
                    "insert into property_fingerprints (kind, hash, property_id) "
                    "select kind, hash, %s from unnest(%s::text[], %s::text[]) as u(kind, hash) "
                    "on conflict (kind, hash) do nothing returning kind",
                    (property_id, kinds, hashes),
                )
                if len(await cur.fetchall()) < len(prints):
                    raise _AlreadyKnown
        except (_AlreadyKnown, errors.UniqueViolation):
            return None
        return property_id

    # ── Costi ────────────────────────────────────────────────
    async def month_costs(self, since: datetime) -> tuple[Decimal, Decimal]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select (select coalesce(sum(cost_eur), 0) from search_runs where started_at >= %s) as ricerche, "
                "(select coalesce(sum(cost_eur), 0) from ai_usage where created_at >= %s) as ai",
                (since, since),
            )
            row = await cur.fetchone()
        return Decimal(row["ricerche"]), Decimal(row["ai"])

    async def month_google_requests(self, since: datetime) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select coalesce(sum(pages), 0) as n from search_runs where started_at >= %s", (since,)
            )
            row = await cur.fetchone()
        return int(row["n"])

    async def start_search_run(self, *, zone: str, query: str, cell: str | None, provincia: str | None) -> str:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "insert into search_runs (zone, query, cell, provincia) values (%s, %s, %s, %s) returning id::text as id",
                (zone, query, cell, provincia),
            )
            row = await cur.fetchone()
        return row["id"]

    async def finish_search_run(
        self,
        run_id: str,
        *,
        status: str,
        results: int,
        new: int,
        known: int,
        excluded: int,
        pages: int,
        cost_eur: Decimal,
        error: str | None = None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "update search_runs set finished_at = now(), status = %s, results_count = %s, new_count = %s, "
                "known_count = %s, excluded_count = %s, pages = %s, cost_eur = %s, error = %s where id = %s",
                (status, results, new, known, excluded, pages, cost_eur, error, run_id),
            )

    async def record_ai_usage(
        self,
        *,
        purpose: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_eur: Decimal,
        property_id: str | None,
        request_id: str | None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into ai_usage (purpose, model, input_tokens, output_tokens, cost_eur, property_id, request_id) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (purpose, model, input_tokens, output_tokens, cost_eur, property_id, request_id),
            )

class _AlreadyKnown(Exception):
    """Annulla il salvataggio: la struttura è già in memoria."""
