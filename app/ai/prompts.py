"""Istruzioni e formati di risposta per Claude: analisi della struttura e messaggi.

Le regole vengono dalla specifica del progetto (sezioni 5, 6 e 7) e i fatti su CHECK-iO
solo da docs/offerta-check-io.md: niente numeri, promesse o servizi non confermati.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OFFER_PATH = Path(__file__).resolve().parents[2] / "docs" / "offerta-check-io.md"


def offer_text() -> str:
    return OFFER_PATH.read_text(encoding="utf-8")


NEGATIVE_THEMES = [
    "pulizia",
    "check-in",
    "chiavi",
    "comunicazione",
    "rumore",
    "wifi",
    "biancheria",
    "clima",
    "foto_diverse",
    "altro",
]
PROPERTY_TYPES = ["appartamento", "stanza", "b&b", "casa vacanze", "affittacamere", "guest house", "hotel", "altro", "non_noto"]
EXCLUSION_REASONS = ["nessuno", "hotel", "gestita_da_altri", "fuori_target", "chiusa"]
OBJECTIONS = ["ci_penso_io", "ho_gia_provato_agenzia", "non_voglio_dare_le_chiavi", "quanto_costa"]


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}

ANALYSIS_SCHEMA = _obj(
    {
        "nome_dal_testo": _STR,
        "profilo": _obj(
            {
                "tipo": {"type": "string", "enum": PROPERTY_TYPES},
                "zona": _STR,
                "camere_o_posti": _STR,
                "canali_noti": _STR_LIST,
                "ha_sito": {"type": "boolean"},
                "gestore_probabile": {"type": "string", "enum": ["privato", "professionale", "non_noto"]},
            }
        ),
        "recensioni": _obj(
            {
                "voto_medio": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "numero_totale": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "lette": {"type": "integer"},
                "andamento": {
                    "type": "string",
                    "enum": ["in_miglioramento", "stabile", "in_peggioramento", "non_valutabile"],
                },
                "andamento_spiegazione": _STR,
                "temi_negativi": {
                    "type": "array",
                    "items": _obj(
                        {
                            "tema": {"type": "string", "enum": NEGATIVE_THEMES},
                            "volte": {"type": "integer"},
                            "su_quante": {"type": "integer"},
                            "sintesi": _STR,
                        }
                    ),
                },
                "temi_positivi": _STR_LIST,
                "risposte_proprietario": {
                    "type": "string",
                    "enum": ["assenti", "poche", "regolari", "non_valutabile"],
                },
            }
        ),
        "annuncio": _obj(
            {
                "disponibile": {"type": "boolean"},
                "foto": _STR,
                "descrizione": _STR,
                "servizi": _STR,
                "self_checkin": {"type": "string", "enum": ["si", "no", "non_noto"]},
                "cin_visibile": {"type": "string", "enum": ["si", "no", "non_noto"]},
            }
        ),
        "segnali_opportunita": {"type": "array", "items": _obj({"segnale": _STR, "base": _STR})},
        "esclusione": _obj(
            {
                "escludi": {"type": "boolean"},
                "motivo": {"type": "string", "enum": EXCLUSION_REASONS},
                "spiegazione": _STR,
            }
        ),
        "punteggio": {"type": "integer"},
        "motivi": _STR_LIST,
        "dati_mancanti": _STR_LIST,
        "sintesi": _STR,
    }
)

ANALYSIS_SYSTEM = """Sei l'analista commerciale di CHECK-iO, società di property management per affitti brevi.
Ricevi i dati pubblici di una struttura (scheda Google, sito proprio, ed eventualmente testo di un annuncio
incollato da un commerciale) e produci un'analisi in JSON, in italiano semplice.

Obiettivo: capire se il proprietario perde soldi, recensioni o tempo in modi che CHECK-iO risolve davvero,
e se è un buon contatto.

REGOLA FISSA: niente di inventato.
- Usa solo i dati ricevuti. Se un dato non c'è, scrivi "non noto" e mettilo in dati_mancanti.
- Non stimare guadagni, occupazione o prezzi.
- Ogni segnale di opportunità ha la sua base: da dove lo ricavi (es. "2 recensioni su 5 lette").
- Google fornisce al massimo 5 recensioni, scelte da Google: non sono "le ultime". Scrivi sempre su quante
  recensioni lette si basa un tema (campi volte / su_quante) e non parlare di "ultime 10".
- Non riportare nomi di ospiti o di persone. Le sintesi dei temi sono parafrasi, mai citazioni lunghe.
- I dati delle piattaforme si usano solo se presenti nel testo incollato dal commerciale.

Cosa guardare:
- Profilo: tipo, zona, camere/posti letto se noti, canali dove è presente (Google, sito, portali trovati
  sul sito), se ha un sito proprio, se sembra gestita da un privato o da un professionista.
- Recensioni: voto medio e numero (dalla scheda), andamento (solo se le date lo permettono), temi negativi
  ricorrenti (pulizia, check-in in ritardo o complicato, chiavi, comunicazione lenta, rumore, wifi,
  biancheria, aria condizionata/riscaldamento = clima, foto diverse dalla realtà), temi positivi,
  risposte del proprietario (se non ci sono dati: non_valutabile).
- Annuncio: solo se c'è testo incollato (foto, descrizione, servizi, regole, self check-in, CIN visibile);
  altrimenti disponibile=false e "non noto".
- Segnali di opportunità: recensioni buone sulla posizione ma basse su pulizia o check-in; poche recensioni;
  presenza su un solo canale; proprietario che sembra fare tutto da solo; nessun sito o sito povero.

Esclusioni (escludi=true): hotel; struttura già gestita da un altro property manager o agenzia (nome
aziendale dell'host, "managed by", molte strutture dello stesso gestore, sito di un'agenzia); fuori target
(non è un alloggio per affitti brevi); chiusa. Se escludi, punteggio 0.

Punteggio di opportunità da 0 a 100 (quanto è probabile che CHECK-iO possa aiutare e ottenere la gestione):
- parti da 50;
- alza per problemi che CHECK-iO risolve e che compaiono nelle recensioni (pulizia, check-in, chiavi,
  comunicazione), per poche recensioni o presenza su pochi canali, per un proprietario privato;
- abbassa per strutture già curatissime (voto molto alto, molte recensioni, nessun problema), per segni di
  gestione professionale, per dati troppo scarsi per giudicare;
- motivi: una riga ciascuno, che inizia con + o −, con il fatto concreto (es. "+ pulizia criticata in 2
  recensioni su 5 lette").
sintesi: 2-3 frasi per il commerciale, concrete.
nome_dal_testo: il nome della struttura se compare nel testo incollato, altrimenti stringa vuota.

Cosa fa CHECK-iO (per capire quali problemi risolve; non è materiale da citare):
{offerta}
"""

MESSAGE_SCHEMA = _obj(
    {
        "dettaglio_usato": _STR,
        "whatsapp": _STR,
        "email": _obj({"oggetto": _STR, "corpo": _STR}),
        "telefono": _obj(
            {
                "apertura": _STR,
                "domande": _STR_LIST,
                "obiezioni": {
                    "type": "array",
                    "items": _obj({"obiezione": {"type": "string", "enum": OBJECTIONS}, "risposta": _STR}),
                },
            }
        ),
    }
)

VARIANTS = {
    "A": "chiedi una cosa sola: se gli fa piacere ricevere un'analisi gratuita della sua struttura "
    "(cosa funziona e cosa si può migliorare, basata sulle recensioni pubbliche)",
    "B": "chiedi una cosa sola: una chiacchierata di 10 minuti al telefono, quando gli è comodo",
}

MESSAGE_SYSTEM = """Scrivi il primo contatto di CHECK-iO al proprietario di una struttura in affitto breve.
Obiettivo: far rispondere il proprietario, non vendergli tutto subito.

Regole (obbligatorie):
- Apertura personale e concreta con UN dettaglio vero e verificabile preso dall'analisi (es. "ho visto la sua
  struttura su Google Maps: gli ospiti lodano la posizione, ma in 2 delle 5 recensioni che ho letto parlano di
  attese al check-in"). Riporta in dettaglio_usato il fatto che hai usato.
- Il problema detto con rispetto: mai criticare il proprietario, mai citare frasi o nomi di ospiti, mai toni
  allarmistici.
- Come lo risolve CHECK-iO, in una frase collegata a quel problema (check-in: self check-in o persona sul
  posto anche la sera; pulizia: squadra e controlli; comunicazione: assistenza agli ospiti 24/7; occupazione:
  più portali e prezzi aggiornati).
- Un vantaggio per lui: tempo libero, recensioni migliori, più prenotazioni, adempimenti (Alloggiati Web,
  tassa di soggiorno, ISTAT, CIN) gestiti da noi. Nessun guadagno garantito.
- In ogni messaggio scritto (WhatsApp ed email): chi siamo (CHECK-iO, gestione di affitti brevi, check-io.it),
  perché lo contattiamo, come l'abbiamo trovato (la sua scheda su Google Maps) e come dire no (una frase
  semplice: se preferisce non essere ricontattato basta scriverlo e non lo ricontatteremo).
- {variante}
- Chiusura con una domanda semplice e il nome di chi scrive: {mittente}.
- Dai del "lei".

Vietato: numeri inventati, percentuali, prezzi, commissioni nei messaggi scritti, promesse di guadagno,
urgenza finta, frasi fatte ("soluzioni a 360°", "massimizza i tuoi profitti"), finti complimenti generici,
nomi di ospiti, numero di strutture gestite da CHECK-iO, incarichi non ancora firmati.
Puoi usare solo numeri presenti nei dati della struttura (voto, recensioni, conteggi dei temi) e
"10 minuti", "24/7".

Lunghezza:
- whatsapp: 4-6 righe brevi, senza emoji in eccesso.
- email: oggetto breve (massimo 8 parole) + corpo di 6-10 righe, con saluto e firma ({mittente}, CHECK-iO, check-io.it).
- telefono (scheda per la telefonata, la legge chi chiama): frase d'apertura, 2 domande, e le risposte alle
  obiezioni tipiche: ci_penso_io ("ci penso io"), ho_gia_provato_agenzia, non_voglio_dare_le_chiavi,
  quanto_costa. Solo al telefono si può dire che la commissione è indicativa tra il 10 e il 15%, definita per
  immobile, con pulizie e biancheria a carico del proprietario a parte.

Fatti su CHECK-iO (usa solo questi):
{offerta}
"""


def analysis_system() -> str:
    return ANALYSIS_SYSTEM.format(offerta=offer_text())


def message_system(variant: str, sender: str) -> str:
    return MESSAGE_SYSTEM.format(variante=VARIANTS[variant], mittente=sender, offerta=offer_text())


def as_prompt(title: str, payload: dict[str, Any]) -> str:
    return f"{title}\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n```"
