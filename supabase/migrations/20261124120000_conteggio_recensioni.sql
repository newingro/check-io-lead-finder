-- Diagnostica: quante recensioni restituisce Google per ogni ricerca.
-- reviews_raw  = recensioni ricevute da Google (anche senza testo)
-- reviews_text = recensioni con testo, quelle che vanno all'analisi
-- Si salvano solo i conteggi, mai i testi.
alter table public.search_runs
  add column if not exists reviews_raw integer check (reviews_raw >= 0),
  add column if not exists reviews_text integer check (reviews_text >= 0);
