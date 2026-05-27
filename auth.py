"""
AuditIQ Authentication - Magic Link System (PostgreSQL)
"""

import os
import secrets
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "https://audit.nxtautomation.online")
TRIAL_LIMIT = 50
WARNING_LIMIT = 40

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5434)),
        database=os.getenv("DB_NAME", "auditiq"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "VPS@31"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def init_auth_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS magic_tokens (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def create_or_get_user(email, name, company, plan="trial"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    if not user:
        cur.execute(
            "INSERT INTO users (email, name, company, plan) VALUES (%s, %s, %s, %s)",
            (email, name, company, plan)
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
    cur.close()
    conn.close()
    return dict(user)

def get_user_by_email(email):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return dict(user) if user else None

def get_user_by_token(token):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "SELECT * FROM magic_tokens WHERE token = %s AND used = 0 AND expires_at > %s",
        (token, now)
    )
    token_row = cur.fetchone()
    if not token_row:
        cur.close()
        conn.close()
        return None
    cur.execute("UPDATE magic_tokens SET used = 1 WHERE token = %s", (token,))
    conn.commit()
    cur.execute("SELECT * FROM users WHERE email = %s", (token_row["email"],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return dict(user) if user else None

def create_magic_token(email):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM magic_tokens WHERE email = %s", (email,))
    cur.execute(
        "INSERT INTO magic_tokens (email, token, expires_at) VALUES (%s, %s, %s)",
        (email, token, expires_at)
    )
    conn.commit()
    cur.close()
    conn.close()
    return token

def increment_call_count(email):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET calls_used = calls_used + 1 WHERE email = %s", (email,))
    conn.commit()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close()
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
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (email, token, expires_at) VALUES (%s, %s, %s)",
        (email, token, expires_at)
    )
    conn.commit()
    cur.close()
    conn.close()
    return token

def verify_session_token(token):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "SELECT * FROM sessions WHERE token = %s AND expires_at > %s",
        (token, now)
    )
    session = cur.fetchone()
    if not session:
        cur.close()
        conn.close()
        return None
    cur.execute("SELECT * FROM users WHERE email = %s", (session["email"],))
    user = cur.fetchone()
    cur.close()
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
