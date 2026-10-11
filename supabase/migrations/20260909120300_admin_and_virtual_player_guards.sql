-- Admin and virtual-player guarantees, enforced by the database.
--
-- Both rules were previously only checked in one Python branch each, so any
-- other code path (or two concurrent requests) could leave a group without a
-- reachable administrator.

-- ---------------------------------------------------------------------------
-- Virtual players cannot be administrators.
--
-- A virtual player has no account, so nobody can ever sign in as them. Marking
-- one as admin inflated the administrator count that the "last admin" check
-- relies on, which let the only real admin walk out of a group and leave it
-- permanently unmanageable.
-- ---------------------------------------------------------------------------

update public.memberships
set is_admin = false
where user_id is null and is_admin;

alter table public.memberships
    drop constraint if exists memberships_virtual_players_not_admin;
alter table public.memberships
    add constraint memberships_virtual_players_not_admin
    check (user_id is not null or not is_admin);

-- ---------------------------------------------------------------------------
-- A group that has real members always has at least one real administrator.
-- ---------------------------------------------------------------------------

-- Repair groups that are already stranded by promoting their longest-standing
-- real member, mirroring how the creator becomes admin at creation time.
update public.memberships m
set is_admin = true
where m.id in (
    select distinct on (candidate.group_id) candidate.id
    from public.memberships candidate
    join public.groups g on g.id = candidate.group_id
    where candidate.user_id is not null
      and not exists (
          select 1
          from public.memberships admin
          where admin.group_id = candidate.group_id
            and admin.user_id is not null
            and admin.is_admin
      )
    order by candidate.group_id, candidate.created_at, candidate.id
);

create or replace function public.assert_group_has_admin()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
    affected_group uuid;
    affected_groups uuid[];
begin
    if tg_op = 'INSERT' then
        affected_groups := array[new.group_id];
    elsif tg_op = 'DELETE' then
        affected_groups := array[old.group_id];
    else
        -- A direct database update may move a membership. Check both sides so
        -- the old group cannot be stranded even though the API never mutates
        -- group_id.
        affected_groups := array[old.group_id, new.group_id];
    end if;

    -- Take locks in UUID order so concurrent changes serialize without
    -- introducing opposite lock orders when two groups are involved.
    for affected_group in
        select distinct candidate
        from unnest(affected_groups) as candidate
        where candidate is not null
        order by candidate
    loop
        -- Cascading group deletes remove memberships too. The check is
        -- deferred to commit time, by which point the group row is gone and
        -- there is nothing left to protect.
        perform 1
        from public.groups
        where id = affected_group
        for update;

        if not found then
            continue;
        end if;

        if not exists (
            select 1
            from public.memberships
            where group_id = affected_group
              and user_id is not null
        ) then
            continue;
        end if;

        if not exists (
            select 1
            from public.memberships
            where group_id = affected_group
              and user_id is not null
              and is_admin
        ) then
            raise exception
                'group % would be left without an administrator', affected_group
                using errcode = 'check_violation';
        end if;
    end loop;

    return null;
end;
$$;

drop trigger if exists memberships_require_admin on public.memberships;

create constraint trigger memberships_require_admin
after insert or update or delete on public.memberships
deferrable initially deferred
for each row
execute function public.assert_group_has_admin();
