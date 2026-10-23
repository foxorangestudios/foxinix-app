"""Envío de correos vía SMTP o Resend, con fallback a log local (modo prueba)."""
from __future__ import annotations

import html
import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("foxmsg.mail")

RESEND_URL = "https://api.resend.com/emails"

# Marca real del sitio (500×200) para el correo — W27g: sustituye al
# emoji "🦊 Foxinix". En SMTP va embebida (CID); en Resend, por URL
# pública si hay una (PUBLIC_URL), y si no, la marca en texto.
LOGO_PATH = Path(__file__).resolve().parent.parent / "web" / "logo.webp"
LOGO_CID = "foxinix-logo"

WARN1 = "Válido por 10 minutos. Si no pediste esto, ignora este correo,"
WARN2 = ("NUNCA FOXINIX TE PEDIRA ESTOS CODIGOS, SI ALGUIEN TE LO PIDE "
         "ES UNA ESTAFA!!")
WARN = f"{WARN1} {WARN2}"


def _code_email(code: str, purpose: str, username: str = "",
                logo_src: str = f"cid:{LOGO_CID}") -> tuple[str, str, str]:
    # Asuntos distintos por propósito: así Gmail no junta verificación,
    # recuperación y bounces de "address not found" en el mismo hilo.
    if purpose == "verify":
        title = "Foxinix — Código de verificación"
        intro = "Usa este código para verificar tu cuenta de Foxinix:"
    elif purpose == "emailchange":
        title = "Foxinix — Confirma tu nuevo correo"
        intro = "Usa este código para confirmar tu nueva dirección de correo:"
    else:
        title = "Foxinix — Restablece tu contraseña"
        intro = "Usa este código para elegir una contraseña nueva:"
    h = html.escape
    greet_t = f"Hola, {username}:" if username else "Hola:"
    text = (f"{title}\n\n{greet_t}\n\n{intro}\n\n{code}\n\n{WARN}\n\n"
            "Foxinix — mensajería en tu propio servidor.")
    if username:
        greet = f"Hola, <strong>{h(username)}</strong>,"
    else:
        greet = "Hola,"
    if logo_src:
        logo = (f'<img src="{h(logo_src)}" alt="Foxinix" width="160"'
                ' style="height:64px;width:auto;display:block;margin:0 auto;">')
    else:
        logo = ('<div style="text-align:center;font-size:24px;font-weight:700;'
                'color:#ff751f;letter-spacing:.5px;">Foxinix</div>')
    html_body = f"""<div style="font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;max-width:420px;margin:auto;padding:28px 20px;color:#24292f;">
  <div style="margin-bottom:18px;">{logo}</div>
  <p style="font-size:15px;margin:0 0 12px;">{greet}</p>
  <p style="font-size:14px;color:#57606a;margin:0 0 18px;">{h(intro)}</p>
  <div style="font-size:30px;letter-spacing:8px;font-weight:700;text-align:center;background:#fff7f0;color:#111;padding:16px;border-radius:10px;border:1px solid #ffd8bd;font-family:ui-monospace,'Courier New',monospace;">{h(code)}</div>
  <p style="font-size:13px;color:#57606a;margin:18px 0 0;">{h(WARN1)}</p>
  <p style="font-size:13px;font-weight:700;color:#cf222e;margin:4px 0 0;">{h(WARN2)}</p>
  <p style="font-size:12px;color:#8b949e;text-align:center;margin:22px 0 0;">Foxinix — mensajería en tu propio servidor.</p>
</div>"""
    return title, text, html_body


def _build_msg(to_email: str, subject: str, text: str, html_body: str) -> EmailMessage:
    """Mensaje MIME: texto plano + HTML; si el HTML pide el logo por CID,
       el logo.webp real viaja embebido como related inline (W27g)."""
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    if f"cid:{LOGO_CID}" in html_body and LOGO_PATH.is_file():
        # add_related() convierte la parte HTML en multipart/related y
        # conserva el HTML como primera parte. Antes se inyectaban los
        # literales "<multipart><related>" dentro del HTML.
        rel = msg.get_payload()[1]
        rel.add_related(LOGO_PATH.read_bytes(), "image", "webp",
                        cid=LOGO_CID, filename="logo.webp",
                        disposition="inline")
    return msg


def _send_smtp(to_email: str, subject: str, text: str, html_body: str) -> bool:
    """Envía por SMTP (STARTTLS en puertos normales, SSL directo en 465)."""
    msg = _build_msg(to_email, subject, text, html_body)
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=15) as s:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
        log.info("SMTP enviado a %s vía %s", to_email, config.SMTP_HOST)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Error SMTP con %s: %s", config.SMTP_HOST, exc)
        return False


def send_code(to_email: str, code: str, purpose: str,
              username: str = "") -> bool:
    """Envía el código. Devuelve True si se envió (o se registró en log de prueba)."""
    # W27g: dónde vive la marca en el HTML según el transporte real.
    if config.SMTP_HOST and config.SMTP_PASSWORD:
        logo_src = f"cid:{LOGO_CID}" if LOGO_PATH.is_file() else ""
    elif config.RESEND_API_KEY:
        logo_src = (config.PUBLIC_URL + "/static/logo.webp") if config.PUBLIC_URL else ""
    else:
        logo_src = ""   # modo prueba: el HTML no sale a ningún lado
    subject, text, html_body = _code_email(code, purpose, username, logo_src)

    if config.SMTP_HOST and config.SMTP_PASSWORD:
        # Transporte SMTP (p. ej. Gmail con contraseña de aplicación)
        return _send_smtp(to_email, subject, text, html_body)

    if not config.RESEND_API_KEY:
        # Modo prueba: escribir en data/mail.log
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {to_email} | {purpose} | {code}\n"
        with open(config.MAIL_LOG, "a", encoding="utf-8") as f:
            f.write(line)
        log.warning("Sin transporte de correo (SMTP/Resend); código volcado en %s", config.MAIL_LOG)
        return True

    try:
        resp = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json={
                "from": config.MAIL_FROM,
                "to": [to_email],
                "subject": subject,
                "text": text,
                "html": html_body,
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.error("Resend %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Error de red con Resend: %s", exc)
        return False


def mail_log_codes() -> list[str]:
    """Lee códigos del log de prueba (útil para tests locales)."""
    path = Path(config.MAIL_LOG)
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()
