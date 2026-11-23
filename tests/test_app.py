from telegram.ext import CommandHandler

from app.config import Config
from app.main import OWNER_COMMANDS, build_application


def test_il_bot_si_costruisce_con_tutti_i_comandi():
    config = Config.from_env(
        {"TELEGRAM_BOT_TOKEN": "123456:TEST", "DATABASE_URL": "postgresql://localhost/nessuno"}
    )
    app = build_application(config)
    commands = {
        command
        for handler in app.handlers[0]
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }
    expected = {"start", "aiuto", "collega", "io", "stato", "codice", "team", "pausa", "riprendi", "modalita",
                "impostazioni"}
    assert expected <= commands
    assert {c.command for c in OWNER_COMMANDS} <= commands
    assert app.job_queue is not None
