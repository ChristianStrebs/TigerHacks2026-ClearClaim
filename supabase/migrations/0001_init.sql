-- ClearClaim — pgvector schema for benefits document retrieval.
-- Embedding dimension (768) must match backend EMBED_DIM / GEMINI_EMBED_MODEL.

create extension if not exists vector;

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    document text not null,
    content text not null,
    embedding vector(768) not null,
    created_at timestamptz not null default now()
);

-- Approximate nearest-neighbor index for cosine distance.
create index if not exists documents_embedding_idx
    on public.documents
    using hnsw (embedding vector_cosine_ops);

-- RLS is enabled so the table is never readable through the public Data API.
-- The backend connects with the service role key, which bypasses RLS. No
-- policies are granted to anon/authenticated, so browser clients cannot read
-- or write benefits content directly.
alter table public.documents enable row level security;

-- Similarity search RPC used by the backend's SupabaseVectorStore.
-- SECURITY DEFINER with a pinned search_path so it runs predictably; it is only
-- invoked server-side via the service role.
create or replace function public.match_documents(
    query_embedding vector(768),
    match_count int default 4
)
returns table (
    id uuid,
    document text,
    content text,
    similarity float
)
language sql
stable
security definer
set search_path = public
as $$
    select
        d.id,
        d.document,
        d.content,
        1 - (d.embedding <=> query_embedding) as similarity
    from public.documents d
    order by d.embedding <=> query_embedding
    limit match_count;
$$;

revoke all on function public.match_documents(vector, int) from anon, authenticated;
