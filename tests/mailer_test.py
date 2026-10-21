#!/usr/bin/env python
"""Unit W27g: plantilla del correo de código.

Sin server ni navegador: comprueba la plantilla _code_email (saludo
"Hola, [usuario]", advertencia completa antiestafa, marca real del sitio
en vez del emoji 🦊), el MIME real que sale por SMTP (logo.webp embebido
vía CID) y que el log de prueba conserva el formato exacto que leen los
tests (wait_code: `| email | propósito | código`).

Uso: server/.venv/bin/python tests/mailer_test.py
"""
import email as email_mod
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import mailer  # noqa: E402

CODE = "123456"
ok = 0
fail = 0


def step(msg, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {msg}")
    else:
        fail += 1
        print(f"  ✗ {msg}: {detail}")


def main():
    print("→ paso1 plantilla por propósito")
    for purpose, needle in (
        ("verify", "verificar tu cuenta"),
        ("emailchange", "confirmar tu nueva dirección"),
        ("reset", "elegir una contraseña nueva"),
    ):
        title, text, html = mailer._code_email(CODE, purpose, "ana")
        step(f"{purpose}: asunto e intro",
             title.startswith("Foxinix") and needle in text and needle in html,
             (title, needle))

    print("→ paso2 saludo, advertencia y código")
    title, text, html = mailer._code_email(CODE, "reset", "ana")
    step("el HTML saluda con Hola, <strong>ana</strong>,",
         "Hola, <strong>ana</strong>," in html, html[:240])
    step("el texto saluda con Hola, ana:", "Hola, ana:" in text,
         text.splitlines()[:5])
    step("advertencia en el HTML (unida y en sus dos bloques)",
         mailer.WARN1 in html and mailer.WARN2 in html
         and mailer.WARN1.rstrip(",") in mailer.WARN,
         mailer.WARN)
    step("advertencia completa en el texto plano", mailer.WARN in text,
         text[-260:])
    step("el código de 6 dígitos está en ambos", CODE in html and CODE in text)
    step("sin emoji 🦊 (va la marca real)", "🦊" not in html)
    step("el HTML pide el logo por CID", 'src="cid:foxinix-logo"' in html,
         html[:200])
    step("sin logo_src, la marca queda en texto",
         "Foxinix</div>" in mailer._code_email(CODE, "reset", "ana", "")[2])

    print("→ paso3 MIME con logo embebido (lo que manda SMTP)")
    msg = mailer._build_msg("ana@mail.com", title, text, html)
    raw = msg.as_bytes()
    root = email_mod.message_from_bytes(raw)
    parts = [p.get_content_type() for p in root.get_payload()]
    step("alternative: texto plano + related",
         parts == ["text/plain", "multipart/related"], parts)
    rel = root.get_payload()[1]
    rel_parts = [p.get_content_type() for p in rel.get_payload()]
    step("related: html + image/webp",
         rel_parts == ["text/html", "image/webp"], rel_parts)
    imgs = [p for p in rel.get_payload() if p.get_content_type() == "image/webp"]
    cid = imgs[0].get("Content-ID", "") if imgs else ""
    step("Content-ID del logo", mailer.LOGO_CID in cid, cid)
    step("el logo.webp real viaja con bytes",
         bool(imgs) and len(imgs[0].get_payload(decode=True) or b"") > 0,
         [len(p.get_payload(decode=True) or b"") for p in imgs])

    print("→ paso4 modo prueba: formato del log (wait_code)")
    with tempfile.TemporaryDirectory() as td:
        # fuerza modo prueba sin tocar la config real
        mailer.config.SMTP_HOST = ""
        mailer.config.SMTP_PASSWORD = ""
        mailer.config.RESEND_API_KEY = ""
        mailer.config.MAIL_LOG = Path(td) / "mail.log"
        sent = mailer.send_code("ana@mail.com", CODE, "reset", "ana")
        content = (mailer.config.MAIL_LOG.read_text(encoding="utf-8")
                   if mailer.config.MAIL_LOG.is_file() else "")
        pat = re.compile(r"\| ana@mail\.com \| reset \| (\d+)")
        step("send_code en modo prueba devuelve True", sent is True, sent)
        step("el log se lee con el mismo patrón de wait_code",
            pat.findall(content) == [CODE], repr(content))

    print(f"\nmailer test: {ok} ok, {fail} fallas")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
