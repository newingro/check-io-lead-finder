-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — accesso dal gestionale (admin.check-io.it)
--
-- Ogni persona del team ha un account (Supabase Auth) collegato alla
-- sua riga in lead_finders. Le regole di accesso:
--   • servono login + verifica in due passaggi (aal2) per vedere qualsiasi dato;
--   • il titolare vede e modifica tutto;
--   • il commerciale vede stato, zone e impostazioni (senza modificarle)
--     e, quando ci saranno, solo le strutture assegnate a lui.
-- Il bot si collega dal server con l'utente del database e non è
-- soggetto a queste regole.
-- ─────────────────────────────────────────────────────────────

alter table public.lead_finders
  add column auth_user_id uuid unique references auth.users(id) on delete set null,
  add column email text;

-- Funzioni di supporto in uno schema non esposto dalle API.
create schema if not exists private;
grant usage on schema private to authenticated;

create or replace function private.mfa_ok() returns boolean
language sql stable set search_path = '' as $$
  select coalesce((select auth.jwt() ->> 'aal'), '') = 'aal2'
$$;

create or replace function private.current_member_id() returns uuid
language sql stable security definer set search_path = '' as $$
  select id from public.lead_finders
  where auth_user_id = (select auth.uid()) and is_active
$$;

create or replace function private.is_member() returns boolean
language sql stable security definer set search_path = '' as $$
  select private.mfa_ok() and exists (
    select 1 from public.lead_finders where auth_user_id = (select auth.uid()) and is_active
  )
$$;

create or replace function private.is_owner() returns boolean
language sql stable security definer set search_path = '' as $$
  select private.mfa_ok() and exists (
    select 1 from public.lead_finders
    where auth_user_id = (select auth.uid()) and is_active and role = 'titolare'
  )
$$;

revoke all on function private.mfa_ok(), private.current_member_id(), private.is_member(), private.is_owner()
  from public, anon;
grant execute on function private.mfa_ok(), private.current_member_id(), private.is_member(), private.is_owner()
  to authenticated;

-- Le zone devono essere sempre valide, da qualunque parte arrivino.
create or replace function private.valid_zones(zones jsonb) returns boolean
language sql immutable set search_path = '' as $$
  select jsonb_typeof(zones) = 'array'
    and jsonb_array_length(zones) <= 50
    and not exists (
      select 1 from jsonb_array_elements(zones) as z
      where jsonb_typeof(z) <> 'object'
         or coalesce(length(trim(z ->> 'nome')), 0) not between 1 and 80
         or jsonb_typeof(z -> 'lat') <> 'number' or (z ->> 'lat')::numeric not between -90 and 90
         or jsonb_typeof(z -> 'lng') <> 'number' or (z ->> 'lng')::numeric not between -180 and 180
         or jsonb_typeof(z -> 'raggio_km') <> 'number' or (z ->> 'raggio_km')::numeric not between 1 and 100
         or (z ? 'attiva' and jsonb_typeof(z -> 'attiva') <> 'boolean')
    )
$$;
alter table public.finder_settings add constraint finder_settings_zones_valid check (private.valid_zones(zones));

-- Chi modifica dal gestionale viene registrato automaticamente.
create or replace function private.stamp_web_change() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  member record;
begin
  if (select auth.uid()) is null then
    return new; -- modifica fatta dal bot o dall'editor di Supabase
  end if;
  select id, name into member from public.lead_finders where auth_user_id = (select auth.uid());
  new.updated_by := coalesce(member.name, 'gestionale');
  return new;
end;
$$;

create or replace function private.log_web_change() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  member record;
  changed text[];
begin
  if (select auth.uid()) is null then
    return null;
  end if;
  select id, name into member from public.lead_finders where auth_user_id = (select auth.uid());
  select coalesce(array_agg(n.key order by n.key), '{}') into changed
  from jsonb_each(to_jsonb(new)) as n
  join jsonb_each(to_jsonb(old)) as o using (key)
  where n.value is distinct from o.value and n.key not in ('version', 'updated_at', 'updated_by');
  if cardinality(changed) > 0 then
    insert into public.audit_log (actor_id, actor_label, source, action, details)
    values (member.id, coalesce(member.name, 'gestionale'), 'gestionale', tg_argv[0],
            jsonb_build_object('campi', to_jsonb(changed)));
  end if;
  return null;
end;
$$;

create trigger finder_settings_stamp before update on public.finder_settings
  for each row execute function private.stamp_web_change();
create trigger finder_state_stamp before update on public.finder_state
  for each row execute function private.stamp_web_change();
create trigger finder_settings_log after update on public.finder_settings
  for each row execute function private.log_web_change('impostazioni');
create trigger finder_state_log after update on public.finder_state
  for each row execute function private.log_web_change('stato');
create trigger lead_finders_log after update on public.lead_finders
  for each row execute function private.log_web_change('team');

-- ── Permessi sulle tabelle (solo utenti autenticati) ─────────
grant select, update on public.lead_finders to authenticated;
grant select, update on public.finder_settings to authenticated;
grant select, update on public.finder_state to authenticated;
grant select, insert, update, delete on public.call_windows to authenticated;
grant usage, select on sequence public.call_windows_id_seq to authenticated;
grant select, update on public.properties to authenticated;
grant select on public.property_events to authenticated;
grant select on public.audit_log to authenticated;
grant select on public.search_runs to authenticated;
grant select on public.ai_usage to authenticated;
grant select, insert on public.opt_out to authenticated;
grant usage, select on sequence public.opt_out_id_seq to authenticated;
grant insert on public.link_codes to authenticated;

-- ── Regole per riga ──────────────────────────────────────────
create policy "persone: il titolare vede tutti, ognuno vede sé stesso"
  on public.lead_finders for select to authenticated
  using ((select private.is_owner()) or (private.mfa_ok() and id = (select private.current_member_id())));
create policy "persone: modifica solo il titolare"
  on public.lead_finders for update to authenticated
  using ((select private.is_owner())) with check ((select private.is_owner()));

create policy "impostazioni: lettura team" on public.finder_settings for select to authenticated
  using ((select private.is_member()));
create policy "impostazioni: modifica titolare" on public.finder_settings for update to authenticated
  using ((select private.is_owner())) with check ((select private.is_owner()));

create policy "stato: lettura team" on public.finder_state for select to authenticated
  using ((select private.is_member()));
create policy "stato: modifica titolare" on public.finder_state for update to authenticated
  using ((select private.is_owner())) with check ((select private.is_owner()));

create policy "fasce orarie: lettura team" on public.call_windows for select to authenticated
  using ((select private.is_member()));
create policy "fasce orarie: gestione titolare" on public.call_windows for all to authenticated
  using ((select private.is_owner())) with check ((select private.is_owner()));

create policy "strutture: titolare tutte, commerciale le sue" on public.properties for select to authenticated
  using ((select private.is_owner()) or (private.mfa_ok() and assigned_to = (select private.current_member_id())));
create policy "strutture: modifica titolare o assegnatario" on public.properties for update to authenticated
  using ((select private.is_owner()) or (private.mfa_ok() and assigned_to = (select private.current_member_id())))
  with check ((select private.is_owner()) or (private.mfa_ok() and assigned_to = (select private.current_member_id())));

create policy "storico: come le strutture" on public.property_events for select to authenticated
  using (exists (
    select 1 from public.properties p
    where p.id = property_id
      and ((select private.is_owner()) or (private.mfa_ok() and p.assigned_to = (select private.current_member_id())))
  ));

create policy "registro: solo titolare" on public.audit_log for select to authenticated
  using ((select private.is_owner()));
create policy "ricerche: solo titolare" on public.search_runs for select to authenticated
  using ((select private.is_owner()));
create policy "consumi AI: solo titolare" on public.ai_usage for select to authenticated
  using ((select private.is_owner()));

create policy "esclusioni: lettura team" on public.opt_out for select to authenticated
  using ((select private.is_member()));
create policy "esclusioni: inserimento team" on public.opt_out for insert to authenticated
  with check ((select private.is_member()) and created_by = (select private.current_member_id()));

create policy "codici telegram: creati dal titolare" on public.link_codes for insert to authenticated
  with check ((select private.is_owner()) and created_by = (select private.current_member_id()));
