"""Import every model here so Base.metadata knows about all tables."""
from app.models.people import (Role, RolePermission, Employee, AdminInvitation, RefreshToken)
from app.models.visitor import (VisitorType, Visitor, VisitorFaceData, VisitorGroup)
from app.models.invite import (Invite, InviteHost, InviteNotification)
from app.models.visit import (Visit, VisitMovement)
from app.models.security_models import (Approval, BlocklistEntry, OtpChallenge, Device,
                                        WalkInSession)
from app.models.system import (Notification, AuditLog, AppSetting, LegalDocument, LegalSignature)

__all__ = [
    "Role", "RolePermission", "Employee", "AdminInvitation", "RefreshToken",
    "VisitorType", "Visitor", "VisitorFaceData", "VisitorGroup",
    "Invite", "InviteHost", "InviteNotification",
    "Visit", "VisitMovement",
    "Approval", "BlocklistEntry", "OtpChallenge", "Device", "WalkInSession",
    "Notification", "AuditLog", "AppSetting", "LegalDocument", "LegalSignature",
]
