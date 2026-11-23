"""Collegamento del Telegram delle persone tramite codice temporaneo."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from app.db.repository import AlreadyLinkedError, CodeAlreadyUsedError, Repository
from app.domain.codes import generate_code, hash_code, matches_secret, normalize_code
from app.domain.models import ROLE_OWNER, ROLE_SALES, LeadFinder
from app.domain.shifts import default_shifts

MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW_SECONDS = 3600


class LinkOutcome(Enum):
    LINKED = "collegato"
    OWNER_CREATED = "titolare_creato"
    INVALID = "non_valido"
    EXPIRED = "scaduto"
    USED = "gia_usato"
    OTHER_ACCOUNT = "altro_account"
    RATE_LIMITED = "troppi_tentativi"


@dataclass(frozen=True)
class LinkResult:
    outcome: LinkOutcome
    member: LeadFinder | None = None


@dataclass(frozen=True)
class IssuedCode:
    member: LeadFinder
    code: str
    expires_at: datetime
    was_linked: bool
    created: bool


class AttemptLimiter:
    """Limita i tentativi sbagliati di /collega (per account Telegram)."""

    def __init__(self, max_failures: int = MAX_FAILED_ATTEMPTS, window_seconds: int = FAILED_WINDOW_SECONDS):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[int, deque[float]] = defaultdict(deque)

    def _prune(self, user_id: int, now: float) -> deque[float]:
        attempts = self._failures[user_id]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def blocked(self, user_id: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return len(self._prune(user_id, now)) >= self.max_failures

    def fail(self, user_id: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(user_id, now).append(now)

    def reset(self, user_id: int) -> None:
        self._failures.pop(user_id, None)


class LinkingService:
    def __init__(
        self,
        repo: Repository,
        *,
        owner_setup_code: str | None,
        code_ttl: timedelta = timedelta(minutes=15),
        limiter: AttemptLimiter | None = None,
    ) -> None:
        self.repo = repo
        self.owner_setup_code = owner_setup_code
        self.code_ttl = code_ttl
        self.limiter = limiter or AttemptLimiter()

    async def issue_code(self, *, issuer: LeadFinder, name: str, role: str = ROLE_SALES) -> IssuedCode:
        """Il titolare crea (o rinnova) il codice per collegare una persona."""
        if not issuer.is_owner:
            raise PermissionError("solo il titolare può creare codici")
        member = await self.repo.get_member_by_name(name)
        created = member is None
        if member is None:
            member = await self.repo.create_member(name, role, default_shifts())
        code = generate_code()
        expires_at = datetime.now(UTC) + self.code_ttl
        await self.repo.create_link_code(member.id, hash_code(code), expires_at, issuer.id)
        await self.repo.add_audit(
            issuer.id, issuer.name, "telegram", "codice_creato", {"per": member.name, "ruolo": member.role}
        )
        return IssuedCode(member=member, code=code, expires_at=expires_at, was_linked=member.is_linked, created=created)

    async def redeem(
        self,
        raw_code: str,
        *,
        telegram_user_id: int,
        chat_id: int,
        username: str | None,
        display_name: str,
    ) -> LinkResult:
        if self.limiter.blocked(telegram_user_id):
            return LinkResult(LinkOutcome.RATE_LIMITED)

        # Primo avvio: il codice segreto del server crea il titolare (una volta sola).
        if matches_secret(raw_code, self.owner_setup_code):
            if await self.repo.count_linked_owners() > 0:
                self.limiter.fail(telegram_user_id)
                return LinkResult(LinkOutcome.USED)
            if await self.repo.get_member_by_telegram(telegram_user_id) is not None:
                return LinkResult(LinkOutcome.OTHER_ACCOUNT)
            owner = await self.repo.create_member(display_name or "Titolare", ROLE_OWNER, default_shifts())
            owner = await self.repo.link_member_directly(owner.id, telegram_user_id, chat_id, username)
            await self.repo.add_audit(owner.id, owner.name, "telegram", "titolare_collegato", {})
            self.limiter.reset(telegram_user_id)
            return LinkResult(LinkOutcome.OWNER_CREATED, owner)

        if len(normalize_code(raw_code)) != 8:
            self.limiter.fail(telegram_user_id)
            return LinkResult(LinkOutcome.INVALID)

        target = await self.repo.find_link_code(hash_code(raw_code))
        if target is None:
            self.limiter.fail(telegram_user_id)
            return LinkResult(LinkOutcome.INVALID)
        if target.used_at is not None:
            self.limiter.fail(telegram_user_id)
            return LinkResult(LinkOutcome.USED)
        if target.expires_at <= datetime.now(UTC):
            self.limiter.fail(telegram_user_id)
            return LinkResult(LinkOutcome.EXPIRED)

        try:
            member = await self.repo.complete_link(
                target.code_id, target.lead_finder.id, telegram_user_id, chat_id, username
            )
        except AlreadyLinkedError:
            return LinkResult(LinkOutcome.OTHER_ACCOUNT)
        except CodeAlreadyUsedError:
            return LinkResult(LinkOutcome.USED)

        await self.repo.add_audit(member.id, member.name, "telegram", "telegram_collegato", {"ruolo": member.role})
        self.limiter.reset(telegram_user_id)
        return LinkResult(LinkOutcome.LINKED, member)
