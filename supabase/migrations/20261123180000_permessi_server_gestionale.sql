-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — permessi della chiave segreta del gestionale
--
-- In questo progetto Supabase le tabelle non danno permessi automatici
-- a nessun ruolo. Il server del gestionale usa la chiave segreta
-- (ruolo service_role) solo per: creare il primo titolare, creare gli
-- account del team, scrivere nel registro e preparare i codici Telegram.
-- Gli diamo esattamente questi permessi, niente di più.
-- La chiave segreta sta solo nelle variabili del server (Vercel).
-- ─────────────────────────────────────────────────────────────

grant select, insert, update on public.lead_finders to service_role;
grant select, insert, update on public.link_codes   to service_role;
grant insert                 on public.audit_log    to service_role;
grant usage on sequence public.audit_log_id_seq     to service_role;
