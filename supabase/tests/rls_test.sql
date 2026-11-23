-- Prova delle regole di accesso. Si esegue dentro una transazione annullata:
-- non lascia nulla nel database.
begin;

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-000000000001', 'titolare@prova.test'),
  ('00000000-0000-4000-8000-000000000002', 'commerciale@prova.test'),
  ('00000000-0000-4000-8000-000000000003', 'estraneo@prova.test'),
  ('00000000-0000-4000-8000-000000000004', 'sospeso@prova.test');
insert into public.lead_finders (id, name, role, auth_user_id, is_active) values
  ('10000000-0000-4000-8000-000000000001', 'Titolare Prova', 'titolare', '00000000-0000-4000-8000-000000000001', true),
  ('10000000-0000-4000-8000-000000000002', 'Commerciale Prova', 'commerciale', '00000000-0000-4000-8000-000000000002', true),
  ('10000000-0000-4000-8000-000000000004', 'Sospeso Prova', 'commerciale', '00000000-0000-4000-8000-000000000004', false);
insert into public.properties (id, name, assigned_to) values
  ('20000000-0000-4000-8000-000000000001', 'Struttura di Commerciale', '10000000-0000-4000-8000-000000000002'),
  ('20000000-0000-4000-8000-000000000002', 'Struttura del Titolare', '10000000-0000-4000-8000-000000000001');

-- Punto di partenza uguale per tutti i database: giri in pausa (modifica del server, non registrata).
update public.finder_state set paused = true where id = 1;

create temp table esiti (prova text, ok boolean) on commit drop;
grant all on esiti to authenticated, anon, service_role;

-- Titolare con verifica in due passaggi
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000001","aal":"aal2","role":"authenticated"}';
insert into esiti select 'titolare vede tutto il team', count(*) filter (where name like '% Prova') = 3 from public.lead_finders;
insert into esiti select 'titolare vede tutte le strutture', count(*) filter (where id::text like '20000000-%') = 2 from public.properties;
update public.finder_settings set min_score = 77,
  zones = '[{"nome":"Abetone","lat":44.14,"lng":10.66,"raggio_km":15,"attiva":true}]' where id = 1;
insert into esiti select 'titolare modifica le impostazioni', min_score = 77 and updated_by = 'Titolare Prova' from public.finder_settings;
update public.finder_state set paused = false where id = 1;
insert into esiti select 'titolare modifica lo stato', not paused from public.finder_state;
insert into esiti select 'modifiche registrate nel registro', count(*) = 2 from public.audit_log where source = 'gestionale' and actor_label = 'Titolare Prova';
insert into public.link_codes (code_hash, lead_finder_id, expires_at, created_by)
  values ('prova-hash', '10000000-0000-4000-8000-000000000002', now() + interval '15 minutes', '10000000-0000-4000-8000-000000000001');
insert into esiti values ('titolare crea codice telegram', true);
reset role;

-- Commerciale con verifica in due passaggi
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000002","aal":"aal2","role":"authenticated"}';
insert into esiti select 'commerciale vede solo sé stesso', count(*) = 1 and min(name) = 'Commerciale Prova' from public.lead_finders;
insert into esiti select 'commerciale vede solo le sue strutture', count(*) = 1 and min(name) = 'Struttura di Commerciale' from public.properties;
insert into esiti select 'commerciale legge le impostazioni', count(*) = 1 from public.finder_settings;
update public.finder_settings set min_score = 10 where id = 1;
update public.finder_state set paused = true where id = 1;
update public.lead_finders set role = 'titolare' where id = '10000000-0000-4000-8000-000000000002';
insert into esiti select 'commerciale non vede il registro', count(*) = 0 from public.audit_log;
reset role;
insert into esiti select 'commerciale non cambia impostazioni', min_score = 77 from public.finder_settings;
insert into esiti select 'commerciale non cambia lo stato', not paused from public.finder_state;
insert into esiti select 'commerciale non si promuove titolare', role = 'commerciale' from public.lead_finders where id = '10000000-0000-4000-8000-000000000002';

-- Titolare SENZA verifica in due passaggi: non vede nulla
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000001","aal":"aal1","role":"authenticated"}';
insert into esiti select 'senza 2FA niente dati team', count(*) = 0 from public.lead_finders;
insert into esiti select 'senza 2FA niente impostazioni', count(*) = 0 from public.finder_settings;
update public.finder_settings set min_score = 5 where id = 1;
reset role;
insert into esiti select 'senza 2FA nessuna modifica', min_score = 77 from public.finder_settings;

-- Account non collegato al team e account sospeso
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000003","aal":"aal2","role":"authenticated"}';
insert into esiti select 'estraneo non vede nulla', (select count(*) from public.lead_finders) = 0 and (select count(*) from public.finder_settings) = 0;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000004","aal":"aal2","role":"authenticated"}';
insert into esiti select 'sospeso non vede nulla', (select count(*) from public.finder_settings) = 0 and (select count(*) from public.properties) = 0;
reset role;

-- Visitatore anonimo (chiave pubblica)
set local role anon;
do $$ begin
  perform 1 from public.finder_settings;
  insert into esiti values ('anonimo bloccato', false);
exception when insufficient_privilege then
  insert into esiti values ('anonimo bloccato', true);
end $$;
reset role;

-- Zone non valide rifiutate
do $$ begin
  update public.finder_settings set zones = '[{"nome":"X","lat":44,"lng":10,"raggio_km":500}]' where id = 1;
  insert into esiti values ('zona con raggio assurdo rifiutata', false);
exception when check_violation then
  insert into esiti values ('zona con raggio assurdo rifiutata', true);
end $$;

-- Chiave segreta del server del gestionale (service_role): solo ciò che serve
set local role service_role;
do $$ begin
  update public.lead_finders set email = 'titolare@prova.test' where id = '10000000-0000-4000-8000-000000000001';
  insert into public.audit_log (actor_label, source, action) values ('Prova', 'gestionale', 'prova');
  insert into public.link_codes (code_hash, lead_finder_id, expires_at)
    values ('prova-hash-server', '10000000-0000-4000-8000-000000000002', now() + interval '15 minutes');
  update public.link_codes set used_at = now() where code_hash = 'prova-hash-server';
  insert into esiti values ('server collega account e crea codici', true);
exception when insufficient_privilege then
  insert into esiti values ('server collega account e crea codici', false);
end $$;
do $$ begin
  perform 1 from public.finder_settings;
  insert into esiti values ('server non legge le impostazioni', false);
exception when insufficient_privilege then
  insert into esiti values ('server non legge le impostazioni', true);
end $$;
reset role;

-- ── Radar per province e memoria storica ─────────────────────
-- Zone: province accettate, zone incomplete rifiutate
do $$ begin
  update public.finder_settings set zones = '[{"tipo":"provincia","codice":"047","nome":"Pistoia","attiva":true},{"nome":"Abetone","lat":44.14,"lng":10.66,"raggio_km":15}]' where id = 1;
  insert into esiti values ('zona provincia accettata', true);
exception when check_violation then
  insert into esiti values ('zona provincia accettata', false);
end $$;
do $$ begin
  update public.finder_settings set zones = '[{"tipo":"provincia","nome":"Senza codice"}]' where id = 1;
  insert into esiti values ('provincia senza codice rifiutata', false);
exception when check_violation then
  insert into esiti values ('provincia senza codice rifiutata', true);
end $$;
do $$ begin
  update public.finder_settings set zones = '[{"nome":"Senza centro","raggio_km":10}]' where id = 1;
  insert into esiti values ('cerchio senza centro rifiutato', false);
exception when check_violation then
  insert into esiti values ('cerchio senza centro rifiutato', true);
end $$;

-- Il titolare salva una provincia dal gestionale
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000001","aal":"aal2","role":"authenticated"}';
update public.finder_settings set zones = '[{"tipo":"provincia","codice":"047","nome":"Pistoia","attiva":true}]' where id = 1;
reset role;
insert into esiti select 'titolare salva una provincia', zones @> '[{"codice":"047"}]' from public.finder_settings;

-- Commerciale: vede province e copertura, non le impronte; consulta solo le sue strutture
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000002","aal":"aal2","role":"authenticated"}';
insert into esiti select 'team legge le province', count(*) = 110 from public.province;
insert into esiti select 'commerciale vede la copertura del radar', count(*) = 110 from public.radar_province();
do $$ begin
  perform 1 from public.property_fingerprints;
  insert into esiti values ('impronte non leggibili dal web', false);
exception when insufficient_privilege then
  insert into esiti values ('impronte non leggibili dal web', true);
end $$;
do $$ begin
  perform 1 from public.search_cells;
  insert into esiti values ('celle lette solo tramite funzioni', false);
exception when insufficient_privilege then
  insert into esiti values ('celle lette solo tramite funzioni', true);
end $$;
select public.segna_consultata('20000000-0000-4000-8000-000000000001');
do $$ begin
  perform public.segna_consultata('20000000-0000-4000-8000-000000000002');
  insert into esiti values ('commerciale non consulta strutture altrui', false);
exception when no_data_found then
  insert into esiti values ('commerciale non consulta strutture altrui', true);
end $$;
do $$ begin
  perform public.rimetti_in_ricerca('20000000-0000-4000-8000-000000000001');
  insert into esiti values ('commerciale non rimette in ricerca', false);
exception when insufficient_privilege then
  insert into esiti values ('commerciale non rimette in ricerca', true);
end $$;
reset role;
insert into esiti select 'consultazione registrata', view_count = 1 and last_viewed_by = '10000000-0000-4000-8000-000000000002'
  from public.properties where id = '20000000-0000-4000-8000-000000000001';
insert into esiti select 'evento consultata nello storico', count(*) = 1
  from public.property_events where property_id = '20000000-0000-4000-8000-000000000001' and event_type = 'consultata';

-- Account estraneo: niente province né radar
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000003","aal":"aal2","role":"authenticated"}';
insert into esiti select 'estraneo non vede province né radar',
  (select count(*) from public.province) = 0 and (select count(*) from public.radar_province()) = 0;
reset role;

-- Titolare: rimette in ricerca, ma mai chi ha chiesto di non essere contattato
update public.properties set status = 'scartato' where id = '20000000-0000-4000-8000-000000000002';
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000001","aal":"aal2","role":"authenticated"}';
select public.rimetti_in_ricerca('20000000-0000-4000-8000-000000000002', 'prova');
reset role;
insert into esiti select 'titolare rimette in ricerca', status = 'nuovo' from public.properties where id = '20000000-0000-4000-8000-000000000002';
insert into public.opt_out (phone_normalized, reason) values ('+390000000001', 'prova');
update public.properties set phone_normalized = '+390000000001', status = 'scartato' where id = '20000000-0000-4000-8000-000000000002';
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-4000-8000-000000000001","aal":"aal2","role":"authenticated"}';
do $$ begin
  perform public.rimetti_in_ricerca('20000000-0000-4000-8000-000000000002');
  insert into esiti values ('chi ha detto no non torna in ricerca', false);
exception when check_violation then
  insert into esiti values ('chi ha detto no non torna in ricerca', true);
end $$;
reset role;

-- Conservazione: i dati vecchi si cancellano (non i clienti), l'impronta resta
insert into public.properties (id, name, status, updated_at, last_seen_at) values
  ('20000000-0000-4000-8000-000000000003', 'Struttura vecchia', 'scartato', now() - interval '3 years', now() - interval '3 years'),
  ('20000000-0000-4000-8000-000000000004', 'Cliente vecchio', 'cliente', now() - interval '3 years', now() - interval '3 years');
insert into public.property_fingerprints (kind, hash, property_id)
  values ('google', repeat('a', 64), '20000000-0000-4000-8000-000000000003');
select public.pulisci_memoria();
insert into esiti select 'pulizia cancella i dati vecchi',
  not exists (select 1 from public.properties where id = '20000000-0000-4000-8000-000000000003');
insert into esiti select 'pulizia tiene i clienti',
  exists (select 1 from public.properties where id = '20000000-0000-4000-8000-000000000004');
insert into esiti select 'resta solo l impronta', property_id is null
  from public.property_fingerprints where kind = 'google' and hash = repeat('a', 64);

select prova, ok from esiti order by ok, prova;
rollback;
