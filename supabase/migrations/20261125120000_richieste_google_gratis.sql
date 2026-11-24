-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — ricerca su Google entro le richieste gratuite del mese
--
-- google_monthly_requests: quante richieste a Google il bot può fare in un mese
-- (ricerche + dettagli). 0 = nessun limite a numero (vale solo il tetto in euro,
-- che richiede il prezzo). Con un numero > 0 la ricerca funziona anche senza prezzo
-- e il bot si ferma da solo raggiunto il numero.
-- ─────────────────────────────────────────────────────────────
alter table public.finder_settings
  add column google_monthly_requests integer not null default 0
    check (google_monthly_requests between 0 and 1000000);
