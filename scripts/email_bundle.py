#!/usr/bin/env python3
"""
email_bundle.py — e-mail the data-archive bundle as an attachment.

Optional. Used by .github/workflows/data-release.yml only when the repository
has SMTP secrets configured; with no secrets the workflow never calls it.
Standard library only (smtplib over TLS), so there is no third-party action or
package with access to the mailbox credentials.

    python3 scripts/email_bundle.py --subject "..." --body NOTES.md --attach bundle.zip
    python3 scripts/email_bundle.py ... --dry-run     # build the message, send nothing

Configuration comes from environment variables (GitHub Actions secrets):
    SMTP_HOST      e.g. smtp.mail.yahoo.com, smtp.gmail.com, smtp.office365.com
    SMTP_PORT      465 (implicit TLS, default) or 587 (STARTTLS)
    SMTP_USER      the mailbox that sends the message
    SMTP_PASSWORD  an APP PASSWORD for that mailbox — never the account password
    MAIL_TO        recipient(s), comma-separated; defaults to SMTP_USER

The password is never written to stdout/stderr. Exit codes: 0 sent (or dry run),
2 configuration problem, 1 sending failed.
"""
import argparse, os, smtplib, ssl, sys
from email.message import EmailMessage

MAX_ATTACH_BYTES = 20 * 1024 * 1024      # most mailboxes refuse more than ~25 MB

def build_message(sender, recipients, subject, body, attach_path):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    with open(attach_path, "rb") as f:
        data = f.read()
    if len(data) > MAX_ATTACH_BYTES:
        raise ValueError(f"attachment is {len(data):,} bytes — over the {MAX_ATTACH_BYTES:,} byte limit")
    msg.add_attachment(data, maintype="application", subtype="zip",
                       filename=os.path.basename(attach_path))
    return msg

def main(argv):
    ap = argparse.ArgumentParser(description="E-mail the data-archive bundle.")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", required=True, help="text/Markdown file used as the message body")
    ap.add_argument("--attach", required=True, help="file to attach (the bundle zip)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    port_raw = (os.environ.get("SMTP_PORT") or "465").strip()
    to_raw = (os.environ.get("MAIL_TO") or user).strip()
    recipients = [x.strip() for x in to_raw.split(",") if x.strip()]
    missing = [n for n, v in (("SMTP_HOST", host), ("SMTP_USER", user)) if not v]
    if not a.dry_run and not password: missing.append("SMTP_PASSWORD")
    if missing or not recipients:
        print("email_bundle: missing configuration: " + ", ".join(missing or ["MAIL_TO"]), file=sys.stderr)
        return 2
    try:
        port = int(port_raw)
    except ValueError:
        print(f"email_bundle: SMTP_PORT must be a number, got {port_raw!r}", file=sys.stderr)
        return 2
    try:
        with open(a.body, encoding="utf-8") as f:
            body = f.read()
        msg = build_message(user, recipients, a.subject, body, a.attach)
    except (OSError, ValueError) as e:
        print(f"email_bundle: {e}", file=sys.stderr)
        return 2

    size = os.path.getsize(a.attach)
    if a.dry_run:
        print(f"email_bundle (dry run): would send '{a.subject}' to {len(recipients)} recipient(s) "
              f"via {host}:{port} with {os.path.basename(a.attach)} ({size:,} bytes)")
        return 0
    ctx = ssl.create_default_context()
    try:
        if port == 587:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx); s.login(user, password); s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password); s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # Report the failure class and the server's reply, never the credentials.
        print(f"email_bundle: sending failed — {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"email_bundle: sent '{a.subject}' to {len(recipients)} recipient(s) "
          f"with {os.path.basename(a.attach)} ({size:,} bytes)")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
