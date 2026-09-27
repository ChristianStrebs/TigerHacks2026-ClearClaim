-- Supabase's "enable RLS on new tables" event trigger function is SECURITY DEFINER
-- and was exposed at /rest/v1/rpc/rls_auto_enable. Event triggers fire without
-- EXECUTE being checked, so removing API access keeps the trigger working.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
