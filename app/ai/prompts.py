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
- Le recensioni scritte arrivano da due fonti: recensioni_google_lette (spesso vuoto: Google non sempre manda i
  testi) e recensioni_copiate_dal_commerciale (testi copiati a mano da Booking, Airbnb o Google Maps). Contale
  insieme in "lette".
  Google fornisce al massimo 5 recensioni, scelte da Google: non sono "le ultime". Scrivi sempre su quante recensioni
  lette si basa un tema (campi volte / su_quante) e non parlare di "ultime 10".
- Non riportare nomi di ospiti o di persone. Le sintesi dei temi sono parafrasi, mai citazioni lunghe.
- I dati delle piattaforme si usano solo se presenti nel testo incollato dal commerciale.

Cosa guardare:
- Profilo: tipo, zona, camere/posti letto se noti, canali dove è presente (Google, sito, portali trovati
  sul sito), se ha un sito proprio, se sembra gestita da un privato o da un professionista.
- Recensioni: voto medio e numero (dalla scheda), andamento (solo se le date lo permettono), temi negativi
  ricorrenti (pulizia, check-in in ritardo o complicato, chiavi, comunicazione lenta, rumore, wifi,
  biancheria, aria condizionata/riscaldamento = clima, foto diverse dalla realtà), temi positivi,
  risposte del proprietario (se non ci sono dati: non_valutabile).
- Annuncio: solo se c'è testo_incollato_dal_commerciale (foto, descrizione, servizi, regole, self check-in, CIN visibile);
  altrimenti disponibile=false e "non noto".
- Segnali di opportunità: recensioni buone sulla posizione ma basse su pulizia o check-in; poche recensioni;
  presenza su un solo canale; proprietario che sembra fare tutto da solo; nessun sito o sito povero.

Esclusioni (escludi=true): hotel; struttura già gestita da un altro property manager o agenzia (nome
aziendale dell'host, "managed by", molte strutture dello stesso gestore, sito di un'agenzia); fuori target
(non è un alloggio per affitti brevi); chiusa. Se escludi, punteggio 0.

Punteggio di opportunità da 0 a 100 (quanto è probabile che CHECK-iO possa aiutare e ottenere la gestione):
- parti da 50;
- se ci sono recensioni scritte: alza per problemi che CHECK-iO risolve e che compaiono nelle recensioni
  (pulizia, check-in, chiavi, comunicazione); abbassa se le recensioni lette non mostrano problemi;
- se NON ci sono recensioni scritte (lette = 0) è normale, perché Google spesso non manda i testi: non abbassare
  il punteggio per questo e non chiamarli "dati scarsi". Usa la scheda e il sito:
  · voto sotto 4,0: +15; da 4,0 a 4,4: +10; da 4,5 a 4,7: +0; 4,8 o più con almeno 50 recensioni: −10;
  · meno di 20 recensioni in totale (struttura giovane o poco visibile): +5;
  · nessun sito proprio, oppure sito senza portali collegati, oppure presente su un solo canale: +5;
  · mancano sia il voto sia il numero di recensioni: −10;
- in tutti i casi: proprietario che sembra privato (nome semplice, un solo alloggio): +5; segni di gestione
  professionale (nome aziendale, "managed by", molti portali, sito di un'agenzia): −15;
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

Il canale principale è WhatsApp (il proprietario ha un cellulare). WhatsApp ed email seguono questo ordine:
1. Presentazione: saluto, chi scrive e chi siamo: CHECK-iO (check-io.it) è un property manager, cioè gestisce
   per conto del proprietario tutto l'affitto breve del suo appartamento, così lui non deve pensarci. In una o
   due frasi semplici, scegliendo tra: curiamo l'annuncio sulle piattaforme di affitto breve (foto, descrizioni
   e servizi inclusi), prezzi dinamici, check-in e check-out, assistenza agli ospiti 24/7, risposte alle
   recensioni, registrazione CIN; il proprietario incassa senza occuparsi della gestione.
2. La sua struttura: perché scriviamo proprio a lui (abbiamo trovato la sua struttura e il suo contatto tra i
   dati pubblici online: dillo in modo semplice, con la parola "pubblici") e cosa abbiamo visto, con dati veri
   dell'analisi: voto e numero di recensioni pubbliche; se ci sono recensioni lette, i problemi che emergono (temi
   negativi, con quante volte su quante lette) e cosa apprezzano gli ospiti; se non ci sono recensioni lette,
   i segnali della struttura (poche recensioni, nessun sito proprio, pochi portali).
   Riporta in dettaglio_usato i fatti che hai usato.
3. Come, affidando a noi la gestione, quei punti verrebbero seguiti da CHECK-iO, in una frase (check-in: self
   check-in o persona sul posto anche la sera; pulizia: la seguiamo noi con controlli; comunicazione: assistenza
   24/7; recensioni: rispondiamo noi agli ospiti sulle piattaforme; visibilità e occupazione: rinnoviamo foto,
   descrizioni e servizi dell'annuncio, più piattaforme e prezzi dinamici) e un vantaggio per lui (tempo
   libero, recensioni migliori, più prenotazioni).
4. {variante}
5. Come dire no, con una frase semplice: se preferisce non essere ricontattato basta scriverlo e non lo
   ricontatteremo.
6. Firma con il nome di chi scrive: {mittente}.

Regole (obbligatorie):
- I problemi si dicono con rispetto: mai criticare il proprietario, mai citare frasi o nomi di ospiti, mai toni
  allarmistici. Un voto basso non è una critica: presentalo come un punto da cui partire.
- Una sola proposta per messaggio: nella versione A (analisi gratuita) non proporre telefonate e non citare i
  "10 minuti"; nella versione B (chiacchierata di 10 minuti) non proporre l'analisi gratuita.
- Se recensioni_lette è 0 non hai letto recensioni: non dirlo e non citare problemi degli ospiti; usa solo voto,
  numero di recensioni e i segnali della scheda e del sito.
- Proponiamo la gestione completa dell'appartamento (property management), mai servizi singoli: non
  presentarci come impresa di pulizie o di manutenzioni e non offrire solo pulizie, solo check-in o solo
  manutenzioni.
- Della burocrazia cita solo "registrazione CIN": non elencare Alloggiati Web, tassa di soggiorno, ISTAT o altri
  adempimenti.
- Non nominare Google, Google Maps né la "scheda": niente "ho visto la sua casa su Maps" o "recensioni su
  Maps". Parla della sua struttura e delle sue recensioni pubbliche online.
- Nessun guadagno garantito.
- Dai del "lei".

Vietato: numeri inventati, percentuali, prezzi, commissioni nei messaggi scritti, promesse di guadagno,
urgenza finta, frasi fatte ("soluzioni a 360°", "massimizza i tuoi profitti"), finti complimenti generici,
nomi di ospiti, numero di strutture gestite da CHECK-iO, incarichi non ancora firmati.
Puoi usare solo numeri presenti nei dati della struttura (voto, recensioni, conteggi dei temi) e
"10 minuti" (solo nella versione B), "24/7".

Lunghezza:
- whatsapp: 6-8 righe brevi (una riga per ogni punto dell'ordine sopra), senza emoji in eccesso.
- email: oggetto breve (massimo 8 parole) + corpo di 8-12 righe nello stesso ordine, con saluto e firma
  ({mittente}, CHECK-iO, check-io.it, tel. +39 352 255 4502).
- telefono (scheda per la telefonata, la legge chi chiama): frase d'apertura (chi siamo, cosa facciamo e perché
  chiamiamo proprio lui), 2 domande, e le risposte alle
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
