import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_avvio_con_bot_py_spiega_le_variabili_mancanti():
    """`python bot.py` deve avviare lo stesso bot di `python -m app.main`."""
    for command in ([sys.executable, "bot.py"], [sys.executable, "-m", "app.main"]):
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 1
        assert "Variabili mancanti: TELEGRAM_BOT_TOKEN, DATABASE_URL" in result.stderr
