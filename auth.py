"""
AuditIQ Authentication - Magic Link System
"""

import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

DB_PATH = "leads.db"
BASE_URL = os.getenv("BASE_URL", "https://audit.nxtautomation.online")

TRIAL_LIMIT = 50
WARNING_LIMIT = 40

# ── DB Setup ────────────────────────────────────────────────────────────────────
def init_auth_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            company TEXT,
            plan TEXT DEFAULT 'trial',
            calls_used INTEGER DEFAULT 0,
            calls_limit INTEGER DEFAULT 50,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS magic_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def create_or_get_user(email, name, company, plan="trial"):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        conn.execute(
            "INSERT INTO users (email, name, company, plan) VALUES (?, ?, ?, ?)",
            (email, name, company, plan)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(user)

def get_user_by_email(email):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_token(token):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat()
    token_row = conn.execute(
        "SELECT * FROM magic_tokens WHERE token = ? AND used = 0 AND expires_at > ?",
        (token, now)
    ).fetchone()
    if not token_row:
        conn.close()
        return None
    # Mark token as used
    conn.execute("UPDATE magic_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (token_row["email"],)).fetchone()
    conn.close()
    return dict(user) if user else None

def create_magic_token(email):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    # Delete old tokens for this email
    conn.execute("DELETE FROM magic_tokens WHERE email = ?", (email,))
    conn.execute(
        "INSERT INTO magic_tokens (email, token, expires_at) VALUES (?, ?, ?)",
        (email, token, expires_at)
    )
    conn.commit()
    conn.close()
    return token

def increment_call_count(email):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("UPDATE users SET calls_used = calls_used + 1 WHERE email = ?", (email,))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(user)

def check_call_limit(email):
    user = get_user_by_email(email)
    if not user:
        return {"allowed": False, "reason": "User not found"}
    used = user["calls_used"]
    limit = user["calls_limit"]
    if used >= limit:
        return {"allowed": False, "reason": "limit_reached", "used": used, "limit": limit}
    if used >= WARNING_LIMIT:
        return {"allowed": True, "warning": True, "used": used, "limit": limit, "remaining": limit - used}
    return {"allowed": True, "warning": False, "used": used, "limit": limit, "remaining": limit - used}

def create_session_token(email):
    token = secrets.token_urlsafe(48)
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO sessions (email, token, expires_at) VALUES (?, ?, ?)",
        (email, token, expires_at)
    )
    conn.commit()
    conn.close()
    return token

def verify_session_token(token):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    now = datetime.now().isoformat()
    session = conn.execute(
        "SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
        (token, now)
    ).fetchone()
    if not session:
        conn.close()
        return None
    user = conn.execute("SELECT * FROM users WHERE email = ?", (session["email"],)).fetchone()
    conn.close()
    return dict(user) if user else None

async def send_magic_link(email, name, token):
    smtp_host     = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port     = int(os.getenv("SMTP_PORT", "465"))
    smtp_user     = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        print(f"❌ SMTP not configured — SMTP_USER or SMTP_PASSWORD missing")
        raise ValueError("SMTP credentials not configured")

    magic_url = f"{BASE_URL}/auth/verify?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your AuditIQ Dashboard Access Link 🔐"
    msg["From"]    = f"AuditIQ <{smtp_user}>"
    msg["To"]      = email

    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background:#f5f7fa; margin:0; padding:40px 20px;">
  <div style="max-width:560px; margin:0 auto; background:white; border-radius:16px; overflow:hidden; box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <div style="background:#080C12; padding:32px 40px; text-align:center;">
      <h1 style="color:white; font-size:28px; margin:0; font-weight:800;">Audit<span style="color:#00E5A0;">IQ</span></h1>
    </div>
    <div style="padding:40px;">
      <h2 style="color:#080C12; font-size:22px; margin:0 0 16px;">Hi {name}, here's your dashboard link 👋</h2>
      <p style="color:#555; font-size:15px; line-height:1.7; margin:0 0 32px;">
        Click the button below to access your AuditIQ dashboard. This link expires in <strong>24 hours</strong>.
      </p>
      <div style="text-align:center; margin:32px 0;">
        <a href="{magic_url}"
           style="background:#00E5A0; color:#000; padding:18px 36px; border-radius:10px; font-weight:700; font-size:16px; text-decoration:none; display:inline-block;">
          Access My Dashboard →
        </a>
      </div>
      <p style="color:#888; font-size:13px; line-height:1.7; border-top:1px solid #f0f0f0; padding-top:20px; margin:0;">
        If you didn't request this, you can safely ignore this email.<br>
        This link can only be used once and expires in 24 hours.
      </p>
    </div>
    <div style="background:#f8f9fa; padding:20px 40px; text-align:center;">
      <p style="color:#aaa; font-size:12px; margin:0;">AuditIQ by NXT Automation · Made in India 🇮🇳</p>
    </div>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(html, "html"))

    try:
        print(f"📧 Attempting to send magic link to {email} via {smtp_host}:{smtp_port}")
        async with aiosmtplib.SMTP(hostname=smtp_host, port=smtp_port, use_tls=True) as smtp:
            await smtp.login(smtp_user, smtp_password)
            await smtp.send_message(msg)
        print(f"✅ Magic link sent successfully to {email}")
    except aiosmtplib.SMTPAuthenticationError as e:
        print(f"❌ SMTP AUTH FAILED for {email}: {e}")
        raise
    except aiosmtplib.SMTPConnectError as e:
        print(f"❌ SMTP CONNECT FAILED ({smtp_host}:{smtp_port}): {e}")
        raise
    except aiosmtplib.SMTPRecipientRefused as e:
        print(f"❌ RECIPIENT REFUSED {email}: {e}")
        raise
    except Exception as e:
        print(f"❌ SMTP ERROR sending to {email}: {type(e).__name__}: {e}")
        raise

# Initialize on import
init_auth_db()
