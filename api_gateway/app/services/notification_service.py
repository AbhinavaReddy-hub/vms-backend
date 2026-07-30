"""Decides WHAT to send and THROUGH WHICH channel.

The clients only deliver. This file holds the routing rules, so channel
preferences live in exactly one place.
"""
from sqlalchemy.orm import Session

from app.clients.email_client import email_client
from app.clients.sms_client import sms_client
from app.clients.teams_client import teams_client
from app.core.config import settings
from app.models import Employee, Notification

# One shared palette for every outbound email - cool, professional blue,
# no red anywhere.
_BRAND = "#1D4ED8"
_BRAND_DARK = "#1E3A8A"
_INK = "#0F172A"
_MUTED = "#64748B"
_BORDER = "#E2E8F0"
_BG = "#F1F5F9"


def _email_shell(brand_label: str, body_html: str) -> str:
    """Wraps every email in the same card: gradient header, white body,
    quiet footer. Keeps every notification looking like one product."""
    return f"""
      <div style="background:{_BG};padding:32px 16px;font-family:'Segoe UI',Arial,sans-serif;">
        <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:14px;
                    border:1px solid {_BORDER};overflow:hidden;">
          <div style="background:linear-gradient(135deg,{_BRAND},{_BRAND_DARK});padding:22px 28px;">
            <p style="margin:0;color:#fff;font-size:14px;font-weight:700;letter-spacing:.4px;
                      text-transform:uppercase;">{brand_label}</p>
          </div>
          <div style="padding:28px;">
            {body_html}
          </div>
          <div style="padding:16px 28px;border-top:1px solid {_BORDER};">
            <p style="margin:0;color:{_MUTED};font-size:12px;">
              Automated message from your workplace's Visitor Management System.
            </p>
          </div>
        </div>
      </div>
    """


def notify_employee(db: Session, employee: Employee | None, *, type: str, title: str,
                    body: str = "", entity_type: str | None = None, entity_id: int | None = None,
                    severity: str = "info", facts: dict | None = None,
                    actions: list[dict] | None = None):
    """Always creates the in-app notification. Email and Teams only if the
    employee has that channel switched on."""
    if not employee:
        return

    db.add(Notification(
        employee_id=employee.id, type=type, title=title, body=body,
        entity_type=entity_type, entity_id=entity_id, severity=severity,
    ))
    db.commit()

    if employee.notify_email:
        email_client.send(employee.work_email, title, _employee_email_html(title, body, facts, actions))

    if employee.notify_teams:
        teams_client.send_card(employee.teams_webhook_url, title, body, facts, actions)


def _employee_email_html(title: str, body: str, facts: dict | None, actions: list[dict] | None) -> str:
    facts_html = ""
    if facts:
        rows = "".join(
            f'<tr><td style="padding:5px 14px 5px 0;color:{_MUTED};font-size:13px;">{k}</td>'
            f'<td style="padding:5px 0;color:{_INK};font-weight:600;font-size:13px;">{v}</td></tr>'
            for k, v in facts.items()
        )
        facts_html = (f'<table style="margin-top:16px;border-collapse:collapse;width:100%;'
                      f'background:{_BG};border-radius:8px;padding:4px 12px;">{rows}</table>')

    actions_html = ""
    if actions:
        buttons = "".join(
            f'<a href="{a["url"]}" style="display:inline-block;margin:16px 10px 0 0;padding:11px 24px;'
            f'border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;'
            f'{"background:" + _BRAND + ";color:#fff;" if a["title"] == "Approve" else "border:1.5px solid " + _BORDER + ";color:" + _INK + ";"}">'
            f'{a["title"]}</a>'
            for a in actions
        )
        actions_html = f'<div>{buttons}</div>'

    body_html = f"""
      <h2 style="margin:0 0 10px;color:{_INK};font-size:19px;">{title}</h2>
      <p style="margin:0;color:{_MUTED};font-size:15px;line-height:1.6;">{body}</p>
      {facts_html}
      {actions_html}
    """
    return _email_shell("Workplace Notification", body_html)


def notify_visitor_invite(db: Session, invite, raw_token: str, host_name: str | None,
                          company_name: str, qr_data_url: str | None = None):
    from app.core.tokens import invite_link
    from app.models import InviteNotification

    link = invite_link(raw_token)
    body_html = f"""
      <h2 style="margin:0 0 10px;color:{_INK};font-size:20px;">You're invited to {company_name}</h2>
      <p style="margin:0 0 14px;color:{_MUTED};font-size:15px;line-height:1.6;">
        Hi {invite.full_name}, you're confirmed for a visit on
        <b style="color:{_INK};">{invite.arrival_at:%A, %d %b %Y at %I:%M %p}</b>
        {'with <b style="color:' + _INK + ';">' + host_name + '</b>' if host_name else ''}.
      </p>
      {f'<p style="margin:0 0 14px;color:{_INK};font-size:15px;line-height:1.6;">{invite.custom_message}</p>' if invite.custom_message else ''}
      {f'<p style="margin:0 0 14px;color:{_MUTED};font-size:14px;font-style:italic;">{invite.public_notes}</p>' if invite.public_notes else ''}
      <a href="{link}"
         style="display:inline-block;margin-top:6px;background:{_BRAND};color:#fff;
                padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
        Complete your registration
      </a>
      <p style="margin:16px 0 0;color:{_MUTED};font-size:13px;">
        Prefer a plain link? <a href="{link}" style="color:{_BRAND};">{link}</a>
      </p>
      <p style="margin:14px 0 0;color:{_MUTED};font-size:12px;">
        This invitation is personal to you and expires on {invite.valid_until:%d %b %Y}.
      </p>
    """
    html = _email_shell("You're Invited", body_html)
    result = email_client.send(invite.email, f"You're invited to visit {company_name}", html)

    db.add(InviteNotification(
        invite_id=invite.id, channel="email",
        status="sent" if result.get("sent") else "not_sent",
        sent_at=invite.sent_at, error=result.get("error"),
    ))
    db.commit()
    return result


def notify_visitor_welcome(db: Session, *, visitor, pass_token_raw: str, access_code: str,
                           host_name: str | None, company_name: str):
    """Sent exactly once - the moment a registration is approved (or
    auto-approved). Both channels, since this link + code is the visitor's
    only way to check in once they arrive."""
    from app.core.tokens import pass_link

    link = pass_link(pass_token_raw)
    host_line = f" with {host_name}" if host_name else ""

    if visitor.email:
        body_html = f"""
          <h2 style="margin:0 0 10px;color:{_INK};font-size:20px;">You're all set, {visitor.full_name}!</h2>
          <p style="margin:0 0 16px;color:{_MUTED};font-size:15px;line-height:1.6;">
            Your visit to <b style="color:{_INK};">{company_name}</b>{host_line} has been approved.
            Show this pass at the entrance to check in.
          </p>
          <a href="{link}"
             style="display:inline-block;background:{_BRAND};color:#fff;padding:12px 24px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
            View your pass &amp; QR code
          </a>
          <p style="margin:18px 0 0;color:{_MUTED};font-size:13px;">
            Prefer a plain link? <a href="{link}" style="color:{_BRAND};">{link}</a>
          </p>
          <div style="margin-top:18px;padding:14px 18px;background:{_BG};border-radius:8px;">
            <p style="margin:0 0 4px;color:{_MUTED};font-size:12px;">Your entry code</p>
            <p style="margin:0;color:{_INK};font-size:22px;font-weight:700;letter-spacing:3px;">{access_code}</p>
          </div>
          <p style="margin:10px 0 0;color:{_MUTED};font-size:12px;">
            No smartphone handy? Just read this code out at the kiosk.
          </p>
        """
        html = _email_shell("You're Approved", body_html)
        email_client.send(visitor.email, f"You're approved to visit {company_name}", html)

    if visitor.phone:
        sms_client.send(
            visitor.phone,
            f"Good news! You're approved to visit {company_name}{host_line}. "
            f"Your pass: {link}  Entry code: {access_code}",
        )
