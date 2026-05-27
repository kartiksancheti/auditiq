"""
AuditIQ Leads Management - PostgreSQL Version
"""

import os
import asyncio
import aiosmtplib
import psycopg2
import psycopg2.extras
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5434)),
        database=os.getenv("DB_NAME", "auditiq"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "VPS@31"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
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
    cur.close()
    conn.close()

def save_lead_db(name, email, company, volume, plan):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO leads (name, email, company, volume, plan, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (name, email, company, volume, plan, datetime.now().isoformat())
    )
    conn.commit()
    cur.close()
    conn.close()

def get_all_leads():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads ORDER BY created_at DESC")
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(l) for l in leads]

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

async def handle_new_lead(name, email, company, volume, plan):
    save_lead_db(name, email, company, volume, plan)
    print(f"✅ Lead saved to DB: {email}")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_lead_sheets, name, email, company, volume, plan)

# Initialize DB on import
init_db()
