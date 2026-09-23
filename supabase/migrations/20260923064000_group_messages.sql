create table if not exists public.group_messages (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  sender_user_id uuid not null references auth.users (id) on delete cascade,
  message text not null,
  created_at timestamptz not null default now(),
  constraint group_messages_message_check
    check (char_length(btrim(message)) between 1 and 1000)
);

create index if not exists group_messages_group_created_idx
  on public.group_messages (group_id, created_at desc);

alter table public.group_messages enable row level security;

create policy group_messages_select_members
  on public.group_messages
  for select
  using (private.is_group_member(group_id));

create policy group_messages_insert_members
  on public.group_messages
  for insert
  with check (
    sender_user_id = auth.uid()
    and private.is_group_member(group_id)
  );

grant select, insert on public.group_messages to authenticated;
