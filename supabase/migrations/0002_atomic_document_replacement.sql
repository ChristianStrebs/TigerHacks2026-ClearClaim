-- Replace the single shared demo index in one transaction.
-- Apply after 0001_init.sql. This does not add accounts or plan persistence.
-- PostgreSQL rolls back the DELETE if any row fails to insert.
create or replace function public.replace_documents(new_documents jsonb)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
    inserted_count integer;
begin
    if new_documents is null or jsonb_typeof(new_documents) <> 'array'
       or jsonb_array_length(new_documents) = 0 then
        raise exception 'Replacement must contain at least one document chunk';
    end if;

    -- Serialize replacement against other writers while allowing ordinary SELECTs.
    lock table public.documents in share row exclusive mode;
    delete from public.documents;
    insert into public.documents (id, document, content, embedding)
    select
        (chunk->>'id')::uuid,
        chunk->>'document',
        chunk->>'content',
        (chunk->>'embedding')::vector
    from jsonb_array_elements(new_documents) as chunks(chunk);
    get diagnostics inserted_count = row_count;
    return inserted_count;
end;
$$;

-- PUBLIC privileges are inherited: revoking only anon/authenticated is insufficient.
revoke all on function public.replace_documents(jsonb) from public, anon, authenticated;
grant execute on function public.replace_documents(jsonb) to service_role;
revoke all on function public.match_documents(vector, integer) from public, anon, authenticated;
grant execute on function public.match_documents(vector, integer) to service_role;
