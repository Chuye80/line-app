-- Enforce the product invariant below the API layer as well.
-- Existing real-member roles are unchanged.

alter table public.memberships
  drop constraint if exists memberships_virtual_not_admin;

alter table public.memberships
  add constraint memberships_virtual_not_admin
  check (user_id is not null or not is_admin);
