"""Oggetti Telegram finti per provare i comandi senza rete."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.db.memory import InMemoryRepository
from app.services.control import ControlService
from app.services.linking import LinkingService
from app.services.settings_watch import SettingsWatcher

SETUP_CODE = "primo-avvio-segreto-2026"


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: object) -> None:
        self.replies.append(text)


class FakeBot:
    username = "checkio_leads_bot"

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.sent_kwargs: list[dict[str, object]] = []
        self.edited: list[dict[str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> SimpleNamespace:
        self.sent.append((chat_id, text))
        self.sent_kwargs.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text: str, **kwargs: object) -> None:
        self.edited.append({"text": text, **kwargs})


class World:
    """Un bot completo con database in memoria."""

    def __init__(self) -> None:
        self.repo = InMemoryRepository()
        self.bot = FakeBot()
        self.linked_hooks: list[str] = []

        async def hook(_app: object, member: object) -> None:
            self.linked_hooks.append(member.name)  # type: ignore[attr-defined]

        self.app = SimpleNamespace(
            bot=self.bot,
            bot_data={
                "repo": self.repo,
                "timezone": ZoneInfo("Europe/Rome"),
                "watcher": SettingsWatcher(self.repo),
                "control": ControlService(self.repo),
                "linking": LinkingService(self.repo, owner_setup_code=SETUP_CODE, code_ttl=timedelta(minutes=15)),
                "on_member_linked": hook,
            },
        )

    async def send(self, handler, *, user_id: int, args: list[str] | None = None, first_name: str = "Utente",
                   chat_type: str = "private") -> list[str]:
        message = FakeMessage()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, username=f"user{user_id}", first_name=first_name),
            effective_chat=SimpleNamespace(id=user_id, type=chat_type),
            effective_message=message,
        )
        context = SimpleNamespace(application=self.app, bot=self.bot, args=args or [])
        await handler(update, context)
        return message.replies
