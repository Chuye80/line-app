"""Developer-only "view the app as another member".

Testing anything user-dependent - what a plain member may do, whose name the
survey hides, which registration button a player sees - otherwise means holding
several real accounts and signing in and out between them.

This lets one request act as another member without touching authentication:
the caller still presents their own access token and the real session is never
modified. Only the *identity the request runs as* changes, and only for that
request.

Three conditions must all hold, because an impersonation header is the kind of
thing that must fail loudly rather than quietly widen someone's access:

* the deployment must have developer endpoints switched on, which is off by
  default and must never be on in a deployed environment;
* the member being simulated must have a real account, since a virtual player
  has no identity to borrow; and
* the caller must be an administrator of the group that member belongs to, so
  even with the flag on nobody can borrow an identity from a group they do not
  run.

A request without the header does no extra work at all.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import CurrentUser, get_current_user
from backend.config import get_settings
from backend.database import get_db
from backend.models import Membership


ACT_AS_HEADER = "X-Dev-Act-As"


def acting_user(
    user: CurrentUser = Depends(get_current_user),
    act_as: str | None = Header(default=None, alias=ACT_AS_HEADER),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """The identity this request runs as, which is normally just the caller."""

    if act_as is None or not act_as.strip():
        return user

    if not get_settings().enable_dev_endpoints:
        raise HTTPException(
            status_code=403,
            detail="Developer impersonation is not enabled",
        )

    try:
        membership_id = UUID(act_as.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{ACT_AS_HEADER} must be a membership id",
        ) from exc

    target = db.get(Membership, membership_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="Virtual players have no account to simulate",
        )

    # Acting as yourself is a no-op rather than an error, so the frontend can
    # send the header unconditionally.
    if target.user_id == user.id:
        return user

    caller = db.execute(
        select(Membership).where(
            Membership.group_id == target.group_id,
            Membership.user_id == user.id,
        )
    ).scalar_one_or_none()

    if caller is None or not caller.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only an admin of the group can simulate its members",
        )

    return CurrentUser(id=target.user_id, email=None)
