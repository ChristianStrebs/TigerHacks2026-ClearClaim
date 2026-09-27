-- ClearClaim per-user storage.
--
-- Every visitor gets a Supabase user (anonymous sign-in), and the backend forwards
-- that user's JWT, so row level security decides what each request can touch.
-- A user has at most one plan. Replacing or deleting it cascades to that plan's
-- search chunks, bill scans, and chat messages, because they were all produced
-- against the old plan.

create extension if not exists vector with schema extensions;

-- --------------------------------------------------------------------------
-- Tables
-- --------------------------------------------------------------------------

create table public.plans (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    name text not null check (char_length(name) between 1 and 300),
    source text not null check (source in ('demo', 'document')),
    deductible_total numeric(12, 2) not null check (deductible_total >= 0),
    deductible_met numeric(12, 2) not null check (deductible_met >= 0),
    coinsurance_rate numeric(6, 5) not null check (coinsurance_rate between 0 and 1),
    oop_max numeric(12, 2) not null check (oop_max >= 0),
    demo_fields text[] not null default '{}'
        check (demo_fields <@ array['deductible_total', 'coinsurance_rate', 'oop_max']),
    summary text not null check (char_length(summary) <= 20000),
    summary_live boolean not null,
    -- Vectors from different embedding models can't be compared, so searches skip
    -- chunks written under a different model than the one currently running.
    embed_model text not null check (char_length(embed_model) between 1 and 200),
    created_at timestamptz not null default now(),
    constraint plans_one_per_user unique (user_id),
    constraint plans_user_id_id_key unique (user_id, id)
);
comment on table public.plans is 'The member''s active benefits plan; at most one per user.';

create table public.plan_chunks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    plan_id uuid not null,
    document text not null check (char_length(document) between 1 and 300),
    content text not null check (char_length(content) between 1 and 20000),
    embedding extensions.vector(768) not null,
    created_at timestamptz not null default now(),
    -- Composite key: a chunk can only belong to a plan owned by the same user.
    constraint plan_chunks_plan_fkey foreign key (user_id, plan_id)
        references public.plans (user_id, id) on delete cascade
);
comment on table public.plan_chunks is 'Embedded excerpts of the plan, searched to ground chat answers.';
-- Each user has a few dozen chunks, so an exact scan of their rows beats an
-- approximate vector index (which would also filter out other users' rows late).
create index plan_chunks_user_plan_idx on public.plan_chunks (user_id, plan_id);

create table public.bill_scans (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null default auth.uid(),
    plan_id uuid not null,
    file_name text not null check (char_length(file_name) between 1 and 300),
    result jsonb not null check (jsonb_typeof(result) = 'object'),
    created_at timestamptz not null default now(),
    constraint bill_scans_plan_fkey foreign key (user_id, plan_id)
        references public.plans (user_id, id) on delete cascade
);
comment on table public.bill_scans is 'Bill and EOB reviews, checked against the plan they reference.';
create index bill_scans_user_plan_created_idx
    on public.bill_scans (user_id, plan_id, created_at desc);

create table public.chat_messages (
    id bigint generated always as identity primary key,
    user_id uuid not null default auth.uid(),
    plan_id uuid not null,
    question text not null check (char_length(question) between 1 and 4000),
    response jsonb not null check (jsonb_typeof(response) = 'object'),
    created_at timestamptz not null default now(),
    constraint chat_messages_plan_fkey foreign key (user_id, plan_id)
        references public.plans (user_id, id) on delete cascade
);
comment on table public.chat_messages is 'Questions and ClearClaim''s answers about the active plan.';
create index chat_messages_user_plan_id_idx on public.chat_messages (user_id, plan_id, id);

-- --------------------------------------------------------------------------
-- Privileges and row level security
-- --------------------------------------------------------------------------

-- Signed-out requests get nothing; signed-in users may read, add, and delete
-- their own rows. Rows are never edited in place, so there is no UPDATE grant.
revoke all on table public.plans, public.plan_chunks, public.bill_scans, public.chat_messages
    from anon, authenticated;
grant select, insert, delete
    on table public.plans, public.plan_chunks, public.bill_scans, public.chat_messages
    to authenticated;

alter table public.plans enable row level security;
alter table public.plan_chunks enable row level security;
alter table public.bill_scans enable row level security;
alter table public.chat_messages enable row level security;

create policy "Users read their own plan" on public.plans
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "Users add their own plan" on public.plans
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Users delete their own plan" on public.plans
    for delete to authenticated using ((select auth.uid()) = user_id);

create policy "Users read their own plan chunks" on public.plan_chunks
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "Users add their own plan chunks" on public.plan_chunks
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Users delete their own plan chunks" on public.plan_chunks
    for delete to authenticated using ((select auth.uid()) = user_id);

create policy "Users read their own bill scans" on public.bill_scans
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "Users add their own bill scans" on public.bill_scans
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Users delete their own bill scans" on public.bill_scans
    for delete to authenticated using ((select auth.uid()) = user_id);

create policy "Users read their own chat messages" on public.chat_messages
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "Users add their own chat messages" on public.chat_messages
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Users delete their own chat messages" on public.chat_messages
    for delete to authenticated using ((select auth.uid()) = user_id);

-- --------------------------------------------------------------------------
-- Functions (security invoker: they run with the caller's RLS)
-- --------------------------------------------------------------------------

-- Swap the caller's plan and its chunks in one transaction, so a failed upload
-- never leaves the member with a half-indexed plan or no plan at all.
create function public.replace_plan(new_plan jsonb, new_chunks jsonb)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    caller uuid := (select auth.uid());
    new_plan_id uuid;
begin
    if caller is null then
        raise exception 'Sign in before saving a plan' using errcode = '42501';
    end if;
    if jsonb_typeof(new_chunks) is distinct from 'array' or jsonb_array_length(new_chunks) = 0 then
        raise exception 'A plan needs at least one indexed chunk' using errcode = '22023';
    end if;

    -- Two uploads from the same user would otherwise race on plans_one_per_user.
    perform pg_advisory_xact_lock(hashtextextended(caller::text, 0));

    delete from public.plans where user_id = caller;

    insert into public.plans (
        user_id, name, source, deductible_total, deductible_met, coinsurance_rate,
        oop_max, demo_fields, summary, summary_live, embed_model
    )
    select
        caller, p.name, p.source, p.deductible_total, p.deductible_met, p.coinsurance_rate,
        p.oop_max, coalesce(p.demo_fields, '{}'), p.summary, p.summary_live, p.embed_model
    from jsonb_to_record(new_plan) as p (
        name text, source text, deductible_total numeric, deductible_met numeric,
        coinsurance_rate numeric, oop_max numeric, demo_fields text[], summary text,
        summary_live boolean, embed_model text
    )
    returning id into new_plan_id;

    insert into public.plan_chunks (user_id, plan_id, document, content, embedding)
    select caller, new_plan_id, c.document, c.content, c.embedding::text::extensions.vector
    from jsonb_to_recordset(new_chunks) as c (document text, content text, embedding jsonb);

    return new_plan_id;
end;
$$;

-- Closest excerpts from the caller's own plan (cosine similarity, 1 = identical).
create function public.match_plan_chunks(
    query_embedding extensions.vector(768),
    match_count integer default 4
)
returns table (document text, content text, similarity double precision)
language sql
stable
security invoker
set search_path = ''
as $$
    select
        c.document,
        c.content,
        1 - (c.embedding operator(extensions.<=>) query_embedding) as similarity
    from public.plan_chunks as c
    where c.user_id = (select auth.uid())
    order by c.embedding operator(extensions.<=>) query_embedding
    limit least(greatest(match_count, 1), 20);
$$;

revoke all on function public.replace_plan(jsonb, jsonb) from public, anon;
revoke all on function public.match_plan_chunks(extensions.vector, integer) from public, anon;
grant execute on function public.replace_plan(jsonb, jsonb) to authenticated;
grant execute on function public.match_plan_chunks(extensions.vector, integer) to authenticated;
