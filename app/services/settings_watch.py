"""Rilegge impostazioni e stato e segnala cosa è cambiato.

Le impostazioni si modificano dal gestionale (o dall'editor di Supabase):
il bot non va ripubblicato, le rilegge ogni pochi minuti.
"""

from __future__ import annotations

from app.db.repository import Repository
from app.domain.models import Settings, State
from app.domain.settings_view import diff_settings, diff_state


class SettingsWatcher:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.settings: Settings | None = None
        self.state: State | None = None

    async def load(self) -> None:
        self.settings = await self.repo.get_settings()
        self.state = await self.repo.get_state()

    def acknowledge_state(self, state: State) -> None:
        """Una modifica fatta dal bot è già stata comunicata: non ripeterla."""
        self.state = state

    async def check(self) -> list[str]:
        """Restituisce i messaggi da inviare (vuoto se non è cambiato nulla)."""
        if self.settings is None or self.state is None:
            await self.load()
            return []
        messages: list[str] = []

        settings = await self.repo.get_settings()
        if settings.version != self.settings.version:
            changes = diff_settings(self.settings, settings)
            if changes:
                who = f" da {settings.updated_by}" if settings.updated_by else ""
                messages.append("⚙️ Impostazioni aggiornate" + who + ":\n" + "\n".join(changes))
            self.settings = settings

        state = await self.repo.get_state()
        if state.version != self.state.version:
            changes = diff_state(self.state, state)
            if changes:
                who = f" da {state.updated_by}" if state.updated_by else ""
                messages.append("🔔 Stato aggiornato" + who + ":\n" + "\n".join(changes))
            self.state = state

        return messages
