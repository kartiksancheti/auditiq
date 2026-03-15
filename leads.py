"""
AuditIQ Leads Management
Saves leads to SQLite + Google Sheets + sends confirmation email
"""

import os
import sqlite3
import asyncio
import aiosmtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "leads.db"

# ── SQLite Setup ────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT NOT NULL,
            volume TEXT,
            plan TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'new'
        )
    """)
    conn.commit()
    conn.close()

def save_lead_db(name, email, company, volume, plan):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO leads (name, email, company, volume, plan, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, company, volume, plan, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_all_leads():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    leads = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(l) for l in leads]

# ── Google Sheets Setup ─────────────────────────────────────────────────────────
def save_lead_sheets(name, email, company, volume, plan):
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_creds.json")
        sheet_id   = os.getenv("GOOGLE_SHEET_ID", "")

        if not os.path.exists(creds_path) or not sheet_id:
            print("Google Sheets not configured, skipping...")
            return False

        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(sheet_id).sheet1

        # Add header if sheet is empty
        if sheet.row_count == 0 or not sheet.row_values(1):
            sheet.append_row(["ID", "Name", "Email", "Company", "Volume", "Plan", "Date", "Status"])

        sheet.append_row([
            sheet.row_count,
            name, email, company, volume, plan,
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            "New"
        ])
        print(f"✅ Lead saved to Google Sheets: {email}")
        return True

    except Exception as e:
        print(f"Google Sheets error: {e}")
        return False

# ── Confirmation Email ──────────────────────────────────────────────────────────
async def send_confirmation_email(name, email, plan):
    try:
        smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port     = int(os.getenv("SMTP_PORT", "587"))
        smtp_user     = os.getenv("SMTP_USER", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        from_email    = os.getenv("FROM_EMAIL", smtp_user)

        if not smtp_user or not smtp_password:
            print("SMTP not configured, skipping email...")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Welcome to AuditIQ — Your Free Trial is Ready 🎉"
        msg["From"]    = f"AuditIQ <{from_email}>"
        msg["To"]      = email

        html = f"""
<!DOCTYPE html>
<html>
<body style="font-family: 'DM Sans', Arial, sans-serif; background:#f5f7fa; margin:0; padding:40px 20px;">
  <div style="max-width:560px; margin:0 auto; background:white; border-radius:16px; overflow:hidden; box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    
    <div style="background:#080C12; padding:32px 40px; text-align:center;">
      <h1 style="color:white; font-size:28px; margin:0; font-weight:800;">
        Audit<span style="color:#00E5A0;">IQ</span>
      </h1>
      <p style="color:#6B7A99; margin:8px 0 0; font-size:14px;">AI Call Quality Auditing</p>
    </div>

    <div style="padding:40px;">
      <h2 style="color:#080C12; font-size:22px; margin:0 0 8px;">Hi {name}, welcome aboard! 👋</h2>
      <p style="color:#555; font-size:15px; line-height:1.7; margin:0 0 24px;">
        Thank you for signing up for AuditIQ. We're excited to show you how AI can transform your call center quality management.
      </p>

      <div style="background:#f0fdf8; border:1px solid #00E5A0; border-radius:12px; padding:24px; margin-bottom:24px;">
        <h3 style="color:#080C12; margin:0 0 12px; font-size:16px;">🎁 Your Free Trial Includes:</h3>
        <ul style="color:#333; font-size:14px; line-height:2; margin:0; padding-left:20px;">
          <li><strong>50 free call audits</strong> — no credit card required</li>
          <li>Full quality scoring for each call</li>
          <li>Compliance flagging with timestamps</li>
          <li>Hindi, Hinglish & English support</li>
          <li>Agent coaching suggestions</li>
        </ul>
      </div>

      <p style="color:#555; font-size:15px; line-height:1.7; margin:0 0 24px;">
        Our team will reach out to you within <strong>24 hours</strong> to set up your account and walk you through the dashboard.
      </p>

      <div style="text-align:center; margin:32px 0;">
        <a href="https://audit.nxtautomation.online/dashboard" 
           style="background:#00E5A0; color:#000; padding:16px 32px; border-radius:10px; font-weight:700; font-size:15px; text-decoration:none; display:inline-block;">
          View Dashboard →
        </a>
      </div>

      <p style="color:#888; font-size:13px; line-height:1.7; border-top:1px solid #f0f0f0; padding-top:20px; margin:0;">
        Questions? Just reply to this email. We typically respond within a few hours.<br><br>
        — Kartik & Team NXT Automation
      </p>
    </div>

    <div style="background:#f8f9fa; padding:20px 40px; text-align:center;">
      <p style="color:#aaa; font-size:12px; margin:0;">
        AuditIQ by NXT Automation · auditiq.nxtautomation.online<br>
        Made in India 🇮🇳
      </p>
    </div>
  </div>
</body>
</html>
"""
        msg.attach(MIMEText(html, "html"))

        async with aiosmtplib.SMTP(hostname=smtp_host, port=smtp_port, use_tls=True) as smtp:
            await smtp.login(smtp_user, smtp_password)
            await smtp.send_message(msg)

        print(f"✅ Confirmation email sent to {email}")
        return True

    except Exception as e:
        print(f"Email error: {e}")
        return False

# ── Main function to handle a new lead ─────────────────────────────────────────
async def handle_new_lead(name, email, company, volume, plan):
    # 1. Save to SQLite
    save_lead_db(name, email, company, volume, plan)
    print(f"✅ Lead saved to DB: {email}")

    # 2. Save to Google Sheets (runs in thread to avoid blocking)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_lead_sheets, name, email, company, volume, plan)

    # 3. Send confirmation email
    # await send_confirmation_email(name, email, plan)  # Disabled - magic link used instead

# Initialize DB on import
init_db()
