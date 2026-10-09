"""User seeder — creates demo accounts with argon2 hashed passwords.

Demo password for all accounts: Demo@1234

Accounts created:
  - One employee per dept_role (e.g. frontoffice@demo, admission@demo, …)
  - billing.super@demo  → employee with BOTH "Billing" AND "Billing Supervisor" (dual-hat)
  - agent@demo          → app_role=agent (no dept roles by design)
  - admin@demo          → app_role=admin

All passwords: Demo@1234
"""

from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.models import DeptRole, User, UserDeptRole
from app.core.security import hash_password

DEMO_PASSWORD = "Demo@1234"

DEPT_ROLES = [
    "Front Office",
    "Admission",
    "Discharge",
    "Billing",
    "Billing Supervisor",
    "Insurance/TPA",
    "IT Support",
    "Lab",
    "Radiology",
    "Quality",
    "Operations Manager",
]

# email_prefix, name, app_role, dept_roles (list)
DEMO_USERS: list[tuple[str, str, str, list[str]]] = [
    ("frontoffice@demo",   "Alex Front",          "employee", ["Front Office"]),
    ("admission@demo",     "Morgan Admit",         "employee", ["Admission"]),
    ("discharge@demo",     "Casey Discharge",      "employee", ["Discharge"]),
    ("billing@demo",       "Taylor Billing",       "employee", ["Billing"]),
    ("insurance@demo",     "Jordan Insurance",     "employee", ["Insurance/TPA"]),
    ("itsupport@demo",     "Riley IT",             "employee", ["IT Support"]),
    ("lab@demo",           "Sam Lab",              "employee", ["Lab"]),
    ("radiology@demo",     "Dana Radiology",       "employee", ["Radiology"]),
    ("quality@demo",       "Quinn Quality",        "employee", ["Quality"]),
    ("opsmanager@demo",    "Chris Ops",            "employee", ["Operations Manager"]),
    # Dual-hat: Billing + Billing Supervisor
    ("billing.super@demo", "Pat BillingSupervisor","employee", ["Billing", "Billing Supervisor"]),
    # Agent and admin
    ("agent@demo",         "Agent User",           "agent",    []),
    ("admin@demo",         "Admin User",           "admin",    []),
]


def seed_users(db: Session) -> None:
    """Idempotent: deletes and re-creates all demo users and dept roles."""

    # Ensure all dept roles exist
    role_map: dict[str, DeptRole] = {}
    for role_name in DEPT_ROLES:
        dr = db.execute(select(DeptRole).where(DeptRole.name == role_name)).scalar_one_or_none()
        if dr is None:
            dr = DeptRole(name=role_name)
            db.add(dr)
            db.flush()
        role_map[role_name] = dr

    # Remove existing demo users (idempotent)
    demo_emails = [email for email, *_ in DEMO_USERS]
    existing = db.execute(select(User).where(User.email.in_(demo_emails))).scalars().all()
    for u in existing:
        db.execute(delete(UserDeptRole).where(UserDeptRole.user_id == u.id))
        db.delete(u)
    db.flush()

    # Create fresh
    hashed_pw = hash_password(DEMO_PASSWORD)
    for email, name, app_role, dept_roles_list in DEMO_USERS:
        user = User(email=email, name=name, app_role=app_role, password_hash=hashed_pw)
        db.add(user)
        db.flush()

        for role_name in dept_roles_list:
            dr = role_map[role_name]
            db.add(UserDeptRole(user_id=user.id, dept_role_id=dr.id))

    db.commit()
    print("✓ Demo users seeded:")
    for email, name, app_role, roles in DEMO_USERS:
        roles_str = ", ".join(roles) if roles else "(no dept roles)"
        print(f"  [{app_role:8s}] {email:30s}  dept: {roles_str}")
    print(f"\n  Password for all accounts: {DEMO_PASSWORD}")
