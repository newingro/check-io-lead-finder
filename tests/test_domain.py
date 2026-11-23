from decimal import Decimal

from app.config import Config, ConfigError
from app.db.memory import default_settings
from app.domain.codes import ALPHABET, generate_code, hash_code, matches_secret, normalize_code
from app.domain.models import State
from app.domain.settings_view import diff_settings, diff_state, format_settings
from app.domain.shifts import default_shifts, format_shifts

import pytest
from dataclasses import replace


def test_codice_leggibile_e_senza_caratteri_ambigui():
    code = generate_code()
    assert len(code) == 9 and code[4] == "-"
    assert all(ch in ALPHABET for ch in code.replace("-", ""))
    assert not set("01OIL") & set(ALPHABET)


def test_codice_normalizzato_e_impronta_stabile():
    assert normalize_code(" abcd-efgh ") == "ABCDEFGH"
    assert hash_code("abcd efgh") == hash_code("ABCD-EFGH")
    assert hash_code("ABCD-EFGH") != hash_code("ABCD-EFGJ")


def test_codice_di_primo_avvio():
    assert matches_secret(" segreto-lungo-123 ", "segreto-lungo-123")
    assert not matches_secret("altro", "segreto-lungo-123")
    assert not matches_secret("qualsiasi", None)


def test_turni_predefiniti_e_testo():
    assert format_shifts(default_shifts()) == "lun–ven 09:00–17:00"
    assert format_shifts({}) == "nessun turno impostato"
    shifts = {"lun": [["09:00", "13:00"]], "mar": [["09:00", "13:00"]], "sab": [["10:00", "12:00"]]}
    assert format_shifts(shifts) == "lun–mar 09:00–13:00; sab 10:00–12:00"


def test_differenze_impostazioni_in_italiano():
    old = default_settings()
    new = replace(old, min_score=70, zones=[{"nome": "Abetone", "raggio_km": 15}], version=2)
    changes = diff_settings(old, new)
    assert "• Punteggio minimo: 60 → 70" in changes
    assert any(c.startswith("• Zone: nessuna") and "Abetone (15 km)" in c for c in changes)
    assert diff_settings(old, replace(old, version=5)) == []
    text = format_settings(old)
    assert "Tetto mensile AI: 30,00 €" in text and "Follow-up dopo: 5 giorni" in text


def test_differenze_stato():
    a = State(paused=True, mode="misto", version=1)
    b = State(paused=False, mode="telefonate", version=2)
    assert diff_state(a, b) == ["• Giri: ripresi ▶️", "• Modalità: misto → telefonate"]


def test_configurazione():
    env = {"TELEGRAM_BOT_TOKEN": "x", "DATABASE_URL": "postgresql://h/db", "OWNER_SETUP_CODE": "abcdefghijkl"}
    config = Config.from_env(env)
    assert config.settings_poll_seconds == 300 and config.link_code_ttl_minutes == 15
    with pytest.raises(ConfigError):
        Config.from_env({"DATABASE_URL": "x"})
    with pytest.raises(ConfigError):
        Config.from_env({**env, "OWNER_SETUP_CODE": "corto"})
    with pytest.raises(ConfigError):
        Config.from_env({**env, "SETTINGS_POLL_SECONDS": "5"})
    assert Decimal("30") == default_settings().monthly_ai_budget_eur


def test_zone_in_telegram_province_e_cerchi():
    from app.domain.settings_view import format_settings

    settings = replace(
        default_settings(),
        zones=[
            {"tipo": "provincia", "codice": "047", "nome": "Pistoia", "attiva": True},
            {"nome": "Abetone", "lat": 44.14, "lng": 10.66, "raggio_km": 15, "attiva": True},
            {"tipo": "provincia", "codice": "048", "nome": "Firenze", "attiva": False},
        ],
    )
    assert "Zone: Pistoia (provincia), Abetone (15 km)" in format_settings(settings)
