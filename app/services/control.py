"""Pausa e modalità dei giri."""

from __future__ import annotations

from app.db.repository import Repository
from app.domain.models import MODES, LeadFinder, State


class ControlService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    async def set_paused(self, actor: LeadFinder, paused: bool) -> tuple[State, bool]:
        """Restituisce il nuovo stato e se è cambiato qualcosa."""
        before = await self.repo.get_state()
        after = await self.repo.update_state(paused=paused, mode=None, updated_by=actor.name)
        changed = before.paused != after.paused
        if changed:
            await self.repo.add_audit(actor.id, actor.name, "telegram", "pausa" if paused else "ripresa", {})
        return after, changed

    async def set_mode(self, actor: LeadFinder, mode: str) -> tuple[State, bool]:
        if mode not in MODES:
            raise ValueError(mode)
        before = await self.repo.get_state()
        after = await self.repo.update_state(paused=None, mode=mode, updated_by=actor.name)
        changed = before.mode != after.mode
        if changed:
            await self.repo.add_audit(
                actor.id, actor.name, "telegram", "modalita", {"da": before.mode, "a": after.mode}
            )
        return after, changed
