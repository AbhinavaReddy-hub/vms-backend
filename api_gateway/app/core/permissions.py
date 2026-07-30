"""The permission catalog and the one function every protected endpoint uses.

The frontend hides buttons. THIS is what actually enforces access.
"""
from fastapi import Depends, HTTPException, status

# key -> (module, sub_category, label)
PERMISSION_CATALOG = {
    # Visitors log and entries
    "visitors.entries.view_all":      ("Visitors", "Visitors log and entries", "View all visitor entries"),
    "visitors.entries.add":           ("Visitors", "Visitors log and entries", "Add visitor entries"),
    "visitors.entries.edit":          ("Visitors", "Visitors log and entries", "Edit visitor entries"),
    "visitors.entries.delete":        ("Visitors", "Visitors log and entries", "Delete visitor entries"),
    "visitors.entries.export_all":    ("Visitors", "Visitors log and entries", "Export all visitor entries"),
    # Invites
    "invites.view_all":               ("Visitors", "Invites", "View all invites"),
    "invites.edit_all":               ("Visitors", "Invites", "Edit all invites"),
    "invites.delete_all":             ("Visitors", "Invites", "Delete all invites"),
    "invites.export_all":             ("Visitors", "Invites", "Export all invites"),
    # Devices
    "devices.view":                   ("Visitors", "Devices", "View devices"),
    "devices.edit":                   ("Visitors", "Devices", "Edit devices"),
    # Invite settings
    "invite_settings.view":           ("Visitors", "Invite settings", "View invite settings"),
    "invite_settings.edit":           ("Visitors", "Invite settings", "Edit invite settings"),
    # Sign-in flows
    "signin_flows.view":              ("Visitors", "Sign-in flows", "View sign-in flows"),
    "signin_flows.edit":              ("Visitors", "Sign-in flows", "Edit sign-in flows"),
    # Emails and guides
    "emails_guides.view":             ("Visitors", "Emails and guides", "View emails and guides"),
    "emails_guides.edit":             ("Visitors", "Emails and guides", "Edit emails and guides"),
    # Blocklist
    "blocklist.view":                 ("Visitors", "Blocklist management", "View blocklist"),
    "blocklist.edit":                 ("Visitors", "Blocklist management", "Edit blocklist"),
    # Approvals
    "approvals.view_match_details":   ("Visitors", "Approvals", "View specific details of screening matches"),
    "approvals.decide_screening":     ("Visitors", "Approvals", "Approve or deny screening matches"),
    "approvals.decide_blocklist":     ("Visitors", "Approvals", "Approve or deny blocklist matches"),
    "approvals.decide_invites":       ("Visitors", "Approvals", "Approve or deny outgoing invites"),
    # Security screening
    "security_screening.view":        ("Visitors", "Security screening", "View security screening"),
    "security_screening.edit":        ("Visitors", "Security screening", "Edit security screening"),
    # Full visitor history
    "visitor_history.view_full":      ("Visitors", "Full visitor history", "View full visitor history"),
    # Face recognition (our addition - not in the reference UI)
    "face.settings.view":             ("System", "Face recognition", "View face settings"),
    "face.settings.edit":             ("System", "Face recognition", "Edit face settings"),
    "face.data.delete":               ("System", "Face recognition", "Delete visitor face data"),
    # People and access
    "employees.view":                 ("People", "Employee directory", "View employees"),
    "employees.edit":                 ("People", "Employee directory", "Add or edit employees"),
    "employees.delete":               ("People", "Employee directory", "Deactivate employees"),
    "admins.view":                    ("Manage", "Admins", "View admins"),
    "admins.edit":                    ("Manage", "Admins", "Add or edit admins"),
    "admins.delete":                  ("Manage", "Admins", "Remove admins"),
    "roles.view":                     ("Manage", "Roles", "View roles"),
    "roles.edit":                     ("Manage", "Roles", "Create or edit roles"),
    "roles.delete":                   ("Manage", "Roles", "Delete roles"),
    # System
    "analytics.view":                 ("System", "Analytics", "View analytics"),
    "audit.view":                     ("System", "Audit log", "View audit log"),
    "settings.view":                  ("System", "Settings", "View settings"),
    "settings.edit":                  ("System", "Settings", "Edit settings"),
    "privacy.manage":                 ("System", "Data and privacy", "Manage retention and privacy"),
}

ALL_PERMISSIONS = list(PERMISSION_CATALOG.keys())

# Roles seeded on first run. Global Admin gets everything.
SYSTEM_ROLES = {
    "Global Admin": ALL_PERMISSIONS,
    "Global Admin without deletion": [
        p for p in ALL_PERMISSIONS if not p.endswith(".delete") and "delete" not in p
    ],
    "Approvals Admin": [
        "visitors.entries.view_all", "visitors.entries.add", "visitors.entries.edit",
        "blocklist.view",
        "approvals.view_match_details", "approvals.decide_screening",
        "approvals.decide_blocklist", "approvals.decide_invites",
    ],
    "Analytics Viewer": ["analytics.view", "visitors.entries.view_all"],
    "Security Desk": [
        "visitors.entries.view_all", "visitors.entries.add", "visitors.entries.edit",
        "invites.view_all", "blocklist.view", "blocklist.edit",
        "approvals.view_match_details", "approvals.decide_blocklist", "approvals.decide_invites",
        "devices.view", "employees.view",
    ],
    # A normal employee. Can only manage their OWN visitors - enforced in the
    # service layer by row filtering, not by this permission list.
    "Host": ["employees.view"],
}


def require_permission(*keys: str):
    """FastAPI dependency. Usage:

        user = Depends(require_permission("invites.delete_all"))

    Deny by default: if the user's role does not carry the key, it is a 403.
    """
    from app.core.deps import get_current_employee

    def checker(user=Depends(get_current_employee)):
        granted = getattr(user, "_permissions", set())
        if not any(k in granted for k in keys):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {' or '.join(keys)}",
            )
        return user

    return checker
