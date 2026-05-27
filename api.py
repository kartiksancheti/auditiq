import os, json, uuid
import asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Cookie, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from auth import (
    create_or_get_user, create_magic_token, get_user_by_token, get_user_by_email,
    create_session_token, verify_session_token, check_call_limit,
    increment_call_count, send_magic_link,
)

load_dotenv()
from auditor import audit_call, DEFAULT_CRITERIA
from leads import handle_new_lead, get_all_leads

# ── Google OAuth ────────────────────────────────────────────────────────────────
from authlib.integrations.starlette_client import OAuth
oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
# ───────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="AuditIQ", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["https://audit.nxtautomation.online","https://auditiq.nxtautomation.online"], allow_methods=["GET","POST"], allow_headers=["*"], allow_credentials=True)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "auditiq-secret-key-2026"))

UPLOAD_DIR = Path("uploads")
FRANCHISE_CLIENTS = {"salim@delightservices.in", "musicbeats897@gmail.com"}

FRANCHISE_USERS = {
    "salim@delightservices.in": os.getenv("FRANCHISE_PASSWORD_SALIM", "delight2024"),
    "musicbeats897@gmail.com":  os.getenv("FRANCHISE_PASSWORD_MUSIC", "music2024"),
}
REPORTS_DIR = Path("reports")
UPLOAD_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "https://audit.nxtautomation.online")

@app.get("/admin/report/download/{audit_id}")
async def download_report(audit_id: str, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    # Try standard report
    for path in [Path(f"reports/{audit_id}.json"), Path(f"reports/{audit_id}.checklist.json")]:
        if path.exists():
            return FileResponse(str(path), filename=f"{audit_id}_report.json", media_type="application/json")
    # Search checklist reports by audit_id field
    for rf in Path("reports").glob("*.checklist.json"):
        try:
            with open(rf) as f:
                d = json.load(f)
            if d.get("audit_id") == audit_id:
                return FileResponse(str(rf), filename=f"{audit_id}_report.json", media_type="application/json")
        except:
            continue
    raise HTTPException(404, "Report not found")

@app.get("/admin/recording/download/{audit_id}")
async def download_recording(audit_id: str, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    # Search in uploads and franchise_recordings
    for folder in [Path("uploads"), Path("franchise_recordings")]:
        for f in folder.glob(f"{audit_id}*"):
            return FileResponse(str(f), filename=f.name)
    raise HTTPException(404, "Recording not found")

@app.post("/admin/report/delete/{audit_id}")
async def delete_report(audit_id: str, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    deleted = False
    user_email = None

    # Try standard report
    for path in [Path(f"reports/{audit_id}.json"), Path(f"reports/{audit_id}.checklist.json")]:
        if path.exists():
            with open(path) as f:
                d = json.load(f)
            user_email = d.get("user_email")
            path.unlink()
            deleted = True

    # Search checklist reports by audit_id field
    if not deleted:
        for rf in Path("reports").glob("*.checklist.json"):
            try:
                with open(rf) as f:
                    d = json.load(f)
                if d.get("audit_id") == audit_id:
                    user_email = d.get("user_email")
                    rf.unlink()
                    deleted = True
                    break
            except:
                continue

    if not deleted:
        raise HTTPException(404, "Report not found")

    # Decrement calls_used for the user
    if user_email and user_email != "anonymous":
        try:
            import psycopg2
            conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31")
            cur = conn.cursor()
            cur.execute("UPDATE users SET calls_used = GREATEST(0, calls_used - 1) WHERE email = %s", (user_email,))
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

    return {"success": True}

# ══════════════════════════════════════════════════════════════════════════════
#  HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AuditIQ — Sign In</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'DM Sans', sans-serif;
  background: #080C12;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
body::before {
  content: '';
  position: fixed;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(0,229,160,0.07) 0%, transparent 70%);
  top: -100px; left: 50%;
  transform: translateX(-50%);
  pointer-events: none;
}
.card {
  background: #0E1420;
  border: 1px solid #1E2D45;
  border-radius: 24px;
  padding: 48px;
  width: 100%;
  max-width: 440px;
  text-align: center;
  animation: fadeUp 0.4s ease;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}
.logo { font-family: 'Syne', sans-serif; font-size: 28px; font-weight: 800; color: white; margin-bottom: 8px; }
.logo span { color: #00E5A0; }
.tagline { color: #6B7A99; font-size: 14px; margin-bottom: 36px; }
.tabs { display: flex; background: #141C2E; border-radius: 10px; padding: 4px; margin-bottom: 28px; }
.tab { flex: 1; padding: 10px; border: none; background: none; color: #6B7A99; font-size: 14px; font-weight: 500; cursor: pointer; border-radius: 8px; transition: all 0.2s; font-family: 'DM Sans', sans-serif; }
.tab.active { background: #1E2D45; color: #F0F4FF; }
.form-group { margin-bottom: 16px; text-align: left; }
.form-group label { display: block; font-size: 13px; color: #6B7A99; margin-bottom: 6px; }
.form-group input {
  width: 100%; background: #141C2E; border: 1px solid #1E2D45;
  border-radius: 10px; padding: 13px 16px; font-size: 14px; color: #E8EDF5;
  outline: none; transition: border-color 0.2s; font-family: 'DM Sans', sans-serif;
}
.form-group input:focus { border-color: #00E5A0; }
.btn-main {
  width: 100%; background: #00E5A0; color: #000; border: none; padding: 14px;
  border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  font-family: 'DM Sans', sans-serif; transition: all 0.2s; margin-top: 4px;
}
.btn-main:hover { background: #00ffb3; transform: translateY(-1px); }
.btn-main:disabled { background: #1E2D45; color: #6B7A99; cursor: not-allowed; transform: none; }
.divider { display: flex; align-items: center; gap: 12px; margin: 22px 0; color: #2A3A52; font-size: 13px; }
.divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: #1E2D45; }
.btn-google {
  width: 100%; background: white; color: #333; border: none; padding: 13px;
  border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer;
  font-family: 'DM Sans', sans-serif; transition: all 0.2s;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  text-decoration: none;
}
.btn-google:hover { background: #f0f0f0; transform: translateY(-1px); box-shadow: 0 4px 16px rgba(0,0,0,0.3); }
.msg { margin-top: 14px; padding: 12px 16px; border-radius: 8px; font-size: 13px; display: none; line-height: 1.6; }
.msg.success { background: rgba(0,229,160,0.1); border: 1px solid rgba(0,229,160,0.2); color: #00E5A0; }
.msg.error   { background: rgba(255,64,96,0.1);  border: 1px solid rgba(255,64,96,0.2);  color: #FF4060; }
.footer-link { margin-top: 24px; font-size: 13px; color: #6B7A99; }
.footer-link a { color: #00E5A0; text-decoration: none; }
@media (max-width: 480px) { .card { padding: 32px 20px; } }
</style>
</head>
<body>
<div class="card">
  <div class="logo">Audit<span>IQ</span></div>
  <p class="tagline">AI Call Quality Auditing for Indian BPOs</p>

  <div class="tabs">
    <button class="tab active" id="tabSignin" onclick="showTab('signin')">Sign In</button>
    <button class="tab"        id="tabSignup" onclick="showTab('signup')">Sign Up</button>
  </div>

  <!-- Sign In -->
  <div id="signinForm">
    <div class="form-group">
      <label>Work Email</label>
      <input type="email" id="signinEmail" placeholder="you@company.com"
             onkeydown="if(event.key==='Enter') requestMagicLink()">
    </div>
    <button class="btn-main" id="signinBtn" onclick="requestMagicLink()">Send Magic Link →</button>
    <div class="msg" id="signinMsg"></div>
  </div>

  <!-- Sign Up -->
  <div id="signupForm" style="display:none">
    <div class="form-group">
      <label>Your Name</label>
      <input type="text" id="signupName" placeholder="Rahul Sharma">
    </div>
    <div class="form-group">
      <label>Work Email</label>
      <input type="email" id="signupEmail" placeholder="you@company.com">
    </div>
    <div class="form-group">
      <label>Company / BPO Name</label>
      <input type="text" id="signupCompany" placeholder="Excellon BPO Pvt Ltd">
    </div>
    <button class="btn-main" id="signupBtn" onclick="doSignup()">Start Free Trial →</button>
    <div class="msg" id="signupMsg"></div>
  </div>

  <div class="divider">or</div>

  <a href="/auth/google" class="btn-google">
    <svg width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.35-8.16 2.35-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
    Continue with Google
  </a>

  <p class="footer-link"><a href="https://auditiq.nxtautomation.online">← Back to AuditIQ</a></p>
</div>

<script>
const params = new URLSearchParams(window.location.search);
if (params.get('error') === 'google_failed') showMsg('signinMsg', 'error', '❌ Google sign-in failed. Try again or use email.');
if (params.get('tab') === 'signup') showTab('signup');

function showTab(tab) {
  ['signin','signup'].forEach(t => {
    document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1)).classList.toggle('active', t === tab);
    document.getElementById(t + 'Form').style.display = t === tab ? 'block' : 'none';
  });
}
function showMsg(id, type, html) {
  const el = document.getElementById(id);
  el.className = 'msg ' + type; el.innerHTML = html; el.style.display = 'block';
}

async function requestMagicLink() {
  const email = document.getElementById('signinEmail').value.trim();
  if (!email) { showMsg('signinMsg','error','Please enter your email'); return; }
  const btn = document.getElementById('signinBtn');
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const res = await fetch('/auth/login', { method:'POST', body: new URLSearchParams({email}) });
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 404)
        showMsg('signinMsg','error','❌ No account found. <a href="javascript:void(0)" onclick="showTab(\'signup\')" style="color:#FF4060;font-weight:700">Sign up here →</a>');
      else throw new Error(data.detail || 'Failed');
    } else {
      showMsg('signinMsg','success','✅ Magic link sent! Check your inbox (and spam).');
      btn.textContent = '✅ Link Sent!';
      return;
    }
  } catch(e) { showMsg('signinMsg','error','❌ ' + e.message); }
  btn.disabled = false; btn.textContent = 'Send Magic Link →';
}

async function doSignup() {
  const name    = document.getElementById('signupName').value.trim();
  const email   = document.getElementById('signupEmail').value.trim();
  const company = document.getElementById('signupCompany').value.trim();
  if (!name || !email || !company) { showMsg('signupMsg','error','Please fill all fields'); return; }
  const btn = document.getElementById('signupBtn');
  btn.disabled = true; btn.textContent = 'Creating account...';
  try {
    const res = await fetch('/leads', { method:'POST', body: new URLSearchParams({name, email, company, volume:'', plan:'trial'}) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Signup failed');
    showMsg('signupMsg','success','✅ Account created! Check your email for the dashboard link.');
    btn.textContent = '✅ Done!';
  } catch(e) {
    showMsg('signupMsg','error','❌ ' + e.message);
    btn.disabled = false; btn.textContent = 'Start Free Trial →';
  }
}
</script>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AuditIQ — Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #333; }
.header { background: #1a1a2e; color: white; padding: 16px 30px; display: flex; align-items: center; justify-content: space-between; }
.header-left { display: flex; align-items: center; gap: 12px; }
.logo { font-size: 18px; font-weight: 700; }
.logo span { color: #00E5A0; }
.badge { background: #e94560; color: white; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
.header-right { display: flex; align-items: center; gap: 12px; }
.user-email { font-size: 13px; color: #6B7A99; }
#usagePill { display: none; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; background: #1E2D45; color: #aaa; }
#usagePill.warn { background: rgba(255,184,0,0.2); color: #FFB800; }
#usagePill.danger { background: rgba(255,64,96,0.2); color: #FF4060; }
.logout-btn { background: none; border: 1px solid #333; color: #777; padding: 6px 14px; border-radius: 8px; cursor: pointer; font-size: 12px; }
.logout-btn:hover { border-color: #FF4060; color: #FF4060; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
.alert { padding: 14px 20px; border-radius: 10px; font-size: 14px; font-weight: 500; margin-bottom: 20px; display: none; }
.alert.yellow { background: #fff8e1; border: 1px solid #ffc107; color: #856404; }
.wall { background: white; border-radius: 16px; padding: 60px 40px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; display: none; }
.wall h2 { font-size: 22px; color: #333; margin: 16px 0 8px; }
.wall p { color: #888; margin-bottom: 24px; }
.wall a { background: #00E5A0; color: #000; padding: 13px 28px; border-radius: 10px; font-weight: 700; text-decoration: none; font-size: 15px; display: inline-block; }
.card { background: white; border-radius: 12px; padding: 28px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.card h2 { font-size: 15px; color: #555; font-weight: 600; margin-bottom: 20px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.fg { display: flex; flex-direction: column; gap: 6px; }
.fg label { font-size: 13px; color: #666; font-weight: 500; }
.fg input { border: 1px solid #ddd; border-radius: 8px; padding: 10px 14px; font-size: 14px; outline: none; }
.fg input:focus { border-color: #e94560; }
.drop-zone { border: 2px dashed #ddd; border-radius: 10px; padding: 32px; text-align: center; cursor: pointer; transition: all 0.2s; }
.drop-zone:hover { border-color: #e94560; background: #fff5f7; }
.drop-zone p { color: #888; font-size: 13px; margin-top: 8px; }
.btn { background: #e94560; color: white; border: none; padding: 12px 28px; border-radius: 8px; font-size: 14px; cursor: pointer; font-weight: 600; margin-top: 14px; transition: background 0.2s; }
.btn:hover { background: #c73652; }
.btn:disabled { background: #ccc; cursor: not-allowed; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.stat-card { background: white; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.stat-card .num { font-size: 30px; font-weight: 700; color: #1a1a2e; }
.stat-card .lbl { font-size: 12px; color: #888; margin-top: 4px; }
.reports-card { background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
.reports-card h2 { padding: 18px 24px; border-bottom: 1px solid #f0f0f0; font-size: 15px; color: #555; }
table { width: 100%; border-collapse: collapse; }
th { background: #f8f9fa; padding: 11px 16px; text-align: left; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
td { padding: 13px 16px; border-bottom: 1px solid #f5f5f5; font-size: 13px; }
tr:hover td { background: #fafafa; }
.sb { display: inline-block; padding: 3px 10px; border-radius: 20px; font-weight: 600; font-size: 12px; }
.sh { background: #e8f5e9; color: #2e7d32; }
.sm { background: #fff8e1; color: #f57f17; }
.sl { background: #fce4ec; color: #c62828; }
.rb { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; }
.re { background: #e8f5e9; color: #2e7d32; }
.rg { background: #e3f2fd; color: #1565c0; }
.rc { background: #fff8e1; color: #f57f17; }
.rr { background: #fce4ec; color: #c62828; }
.cy { color: #2e7d32; font-weight: 600; }
.cn { color: #c62828; font-weight: 600; }
.vb { background: none; border: 1px solid #ddd; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; color: #555; }
.vb:hover { border-color: #e94560; color: #e94560; }
.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; overflow-y: auto; }
.modal.open { display: flex; align-items: flex-start; justify-content: center; padding: 40px 20px; }
.modal-content { background: white; border-radius: 16px; padding: 30px; max-width: 700px; width: 100%; position: relative; }
.close-btn { position: absolute; top: 16px; right: 20px; background: none; border: none; font-size: 22px; cursor: pointer; color: #888; }
.scores-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.score-item { background: #f8f9fa; border-radius: 8px; padding: 14px; text-align: center; }
.score-item .val { font-size: 24px; font-weight: 700; }
.score-item .name { font-size: 12px; color: #888; margin-top: 4px; }
.sec { font-size: 12px; font-weight: 600; color: #555; margin: 16px 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.transcript-box { background: #f8f9fa; border-radius: 8px; padding: 16px; max-height: 250px; overflow-y: auto; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.flag-item { background: #fff3cd; border-left: 3px solid #ffc107; padding: 8px 12px; border-radius: 4px; margin-bottom: 6px; font-size: 13px; }
.str-item  { background: #d4edda; border-left: 3px solid #28a745; padding: 8px 12px; border-radius: 4px; margin-bottom: 6px; font-size: 13px; }
.loading { display: none; padding: 12px 0; color: #888; font-size: 14px; }
.loading.show { display: block; }
.toast { position: fixed; bottom: 30px; right: 30px; background: #1a1a2e; color: white; padding: 14px 20px; border-radius: 10px; font-size: 14px; z-index: 200; transform: translateY(120px); transition: transform 0.3s; max-width: 320px; }
.toast.show { transform: translateY(0); }
/* Login prompt shown to unauthenticated users */
.login-prompt { background: white; border-radius: 16px; padding: 60px 40px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.login-prompt h2 { font-size: 22px; color: #333; margin-bottom: 8px; }
.login-prompt p { color: #888; font-size: 15px; margin-bottom: 28px; }
.login-prompt a { background: #00E5A0; color: #000; padding: 14px 32px; border-radius: 10px; font-weight: 700; text-decoration: none; font-size: 15px; display: inline-block; }
@media (max-width: 768px) {
  .header { padding: 14px 16px; }
  .user-email { display: none; }
  .container { padding: 14px; }
  .form-row { grid-template-columns: 1fr; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  table { font-size: 12px; }
  th, td { padding: 10px 12px; }
  .scores-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="logo">Audit<span>IQ</span></div>
    <span class="badge">Dashboard</span>
  </div>
  <div class="header-right">
    <span class="user-email" id="userEmail"></span>
    <span id="usagePill"></span>
    <button class="logout-btn" onclick="logout()">Sign Out</button>
  </div>
</div>

<div class="container" id="app">
  <!-- Filled by JS -->
</div>

<div class="modal" id="modal">
  <div class="modal-content">
    <button class="close-btn" onclick="closeModal()">✕</button>
    <h2 id="modalTitle">Audit Report</h2>
    <div id="modalBody"></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
let currentUser = null;

//
async function boot() {
  const app = document.getElementById('app');
  try {
    const res = await fetch('/auth/me');
    if (res.ok) {
      currentUser = await res.json();
      document.getElementById('userEmail').textContent = currentUser.email;
      updateUsagePill(currentUser);
      renderMain(app);
      loadReports();
    } else {
      renderLoginPrompt(app);
    }
  } catch(e) {
    renderLoginPrompt(app);
  }
}

function renderLoginPrompt(app) {
  app.innerHTML = `<div class="login-prompt">
    <div style="font-size:52px;margin-bottom:16px">🔐</div>
    <h2>Sign in to access your dashboard</h2>
    <p>Your audit reports are private and linked to your account.</p>
    <a href="/login">Sign In / Sign Up →</a>
  </div>`;
}

function renderMain(app) {
  const used  = currentUser.calls_used  || 0;
  const limit = currentUser.calls_limit || 50;
  const remaining = limit - used;
  const blocked = used >= limit;

  app.innerHTML = `
    <div class="alert yellow" id="alertYellow"></div>

    ${blocked ? `<div class="wall" id="upgradeWall" style="display:block">
      <div style="font-size:48px">🚫</div>
      <h2>Trial Limit Reached</h2>
      <p>You've used all ${limit} free trial calls. Upgrade to continue.</p>
      <a href="https://auditiq.nxtautomation.online/#pricing">Upgrade Now →</a>
    </div>` : ''}

    ${!blocked ? `
    <div class="card" id="singleCard">
      <h2>🎙️ Audit a Call</h2>
      <div class="form-row">
        <div class="fg"><label>Client Name</label><input type="text" id="clientName" placeholder="e.g. HDFC Bank BPO"></div>
        <div class="fg"><label>Agent Name</label><input type="text" id="agentName" placeholder="e.g. Rahul Sharma"></div>
      </div>
      <div class="fg">
        <label>Audio File</label>
        <div class="drop-zone" onclick="document.getElementById('audioFile').click()">
          <div style="font-size:32px">🎵</div>
          <strong id="fileLabel">Click to select audio file</strong>
          <p>Supports MP3, WAV, M4A, OGG</p>
          <input type="file" id="audioFile" accept=".mp3,.wav,.m4a,.ogg,.MP3,.WAV,.M4A,.OGG,audio/*" style="display:none" onchange="updateLabel('fileLabel', this)">
        </div>
      </div>
      <button class="btn" onclick="submitAudit()" id="auditBtn">🔍 Audit Call</button>
      <div class="loading" id="loading">⏳ Transcribing and analyzing... this may take 30–60 seconds.</div>
    </div>
    <div class="card">
      <h2>📦Batch Audit (Multiple Calls)</h2>
      <div class="form-row">
        <div class="fg"><label>Client Name</label><input type="text" id="batchClientName" placeholder="e.g. HDFC Bank BPO"></div>
      </div>
      <div class="fg">
        <label>Audio Files (select multiple)</label>
        <div class="drop-zone" onclick="document.getElementById('batchFiles').click()">
          <div style="font-size:32px">📂</div>
          <strong id="batchLabel">Click to select multiple audio files</strong>
          <p>Hold Ctrl/Cmd to select multiple</p>
          <input type="file" id="batchFiles" accept=".mp3,.wav,.m4a,.ogg,.MP3,.WAV,.M4A,.OGG,audio/*" multiple style="display:none" onchange="updateLabel('batchLabel', this, true)">
        </div>
      </div>
      <button class="btn" onclick="submitBatch()" id="batchBtn">📦 Audit All</button>
      <div class="loading" id="batchLoading">⏳ Processing batch — please wait...</div>
      <div id="batchProgress" style="margin-top:12px;font-size:14px;color:#555"></div>
    </div>
    <div class="stats">
      <div class="stat-card"><div class="num" id="sTotalCalls">-</div><div class="lbl">Total Calls Audited</div></div>
      <div class="stat-card"><div class="num" id="sAvgScore">-</div><div class="lbl">Average Score</div></div>
      <div class="stat-card"><div class="num" id="sFlagged">-</div><div class="lbl">Flagged Calls</div></div>
      <div class="stat-card"><div class="num" id="sCompliance">-</div><div class="lbl">Compliance Rate</div></div>
    </div>

    <div class="reports-card">
      <h2>📋 Audit Reports</h2>
      <div style="overflow-x:auto">
        <table>
          <thead><tr><th>File</th><th>Agent</th><th>Score</th><th>Sentiment</th><th>Compliance</th><th>Recommendation</th><th>Date</th><th></th></tr></thead>
          <tbody id="reportsBody"><tr><td colspan="8" style="text-align:center;color:#888;padding:40px">No audits yet. Upload a call to get started.</td></tr></tbody>
        </table>
      </div>
    </div>
  `;

  // Show warning banner at 40+
  if (!blocked && used >= 40) {
    const el = document.getElementById('alertYellow');
    el.style.display = 'block';
    el.innerHTML = '⚠️ <strong>Warning:</strong> Only ' + remaining + ' trial calls remaining. <a href="https://auditiq.nxtautomation.online/#pricing" style="color:#856404;font-weight:700">Upgrade now →</a>';
  }
}

function updateUsagePill(user) {
  const pill = document.getElementById('usagePill');
  const used = user.calls_used || 0, limit = user.calls_limit || 50;
  pill.style.display = 'inline-block';
  pill.textContent = (limit - used) + ' calls left';
  pill.className = used >= limit ? 'danger' : used >= 40 ? 'warn' : '';
}

function logout() {
  document.cookie = 'session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
  window.location.href = '/login';
}

function updateLabel(id, input, multi = false) {
  document.getElementById(id).textContent = multi
    ? (input.files.length > 0 ? input.files.length + ' file(s) selected' : 'Click to select multiple audio files')
    : (input.files[0]?.name || 'Click to select audio file');
}

//
async function submitAudit() {
  const file = document.getElementById('audioFile')?.files[0];
  if (!file) { showToast('Please select an audio file'); return; }
  const btn = document.getElementById('auditBtn');
  const loading = document.getElementById('loading');
  btn.disabled = true; loading.classList.add('show');
  const fd = new FormData();
  fd.append('file', file);
  fd.append('client_name', document.getElementById('clientName').value);
  fd.append('agent_name', document.getElementById('agentName').value);
  try {
    const res = await fetch('/audit', { method:'POST', body: fd });
    const report = await res.json();
    if (!res.ok) {
      if (res.status === 401) { window.location.href = '/login'; return; }
      if (res.status === 403) {
        // Show upgrade wall, hide upload cards
        document.querySelectorAll('.card').forEach(c => c.style.display = 'none');
        document.getElementById('upgradeWall') && (document.getElementById('upgradeWall').style.display = 'block');
        // Re-render blocked state
        currentUser.calls_used = currentUser.calls_limit;
        renderMain(document.getElementById('app'));
        loadReports();
      }
      throw new Error(report.detail || 'Audit failed');
    }
    // Update usage
    if (report.calls_used !== undefined) {
      currentUser.calls_used = report.calls_used;
      currentUser.calls_limit = report.calls_limit;
      updateUsagePill(currentUser);
      // Check if now blocked
      if (report.calls_used >= report.calls_limit) {
        renderMain(document.getElementById('app'));
        loadReports();
      } else if (report.calls_used >= 40) {
        const el = document.getElementById('alertYellow');
        if (el) {
          el.style.display = 'block';
          el.innerHTML = '⚠️ <strong>Warning:</strong> Only ' + report.calls_remaining + ' trial calls remaining. <a href="https://auditiq.nxtautomation.online/#pricing" style="color:#856404;font-weight:700">Upgrade now →</a>';
        }
      }
    }
    showToast('✅ Audit complete! Score: ' + report.overall_score + '/10');
    loadReports();
    showModal(report);
  } catch(e) { showToast('❌ ' + e.message); }
  finally { btn && (btn.disabled = false); loading.classList.remove('show'); }
}

//
async function submitBatch() {
  const files = document.getElementById('batchFiles')?.files;
  if (!files || !files.length) { showToast('Please select audio files'); return; }
  const btn = document.getElementById('batchBtn');
  const loading = document.getElementById('batchLoading');
  const progress = document.getElementById('batchProgress');
  btn.disabled = true; loading.classList.add('show');
  progress.textContent = 'Uploading ' + files.length + ' files...';
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  fd.append('client_name', document.getElementById('batchClientName').value);
  try {
    const res = await fetch('/audit/batch', { method:'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Batch failed');
    const ok = data.results.filter(r => r.status==='success').length;
    const fail = data.results.filter(r => r.status==='failed').length;
    progress.innerHTML = '✅ <strong>' + ok + ' audited</strong>' + (fail ? ' &nbsp;❌ ' + fail + ' failed' : '');
    showToast('✅ Batch done! ' + ok + '/' + files.length + ' audited');
    loadReports();
  } catch(e) { showToast('❌ ' + e.message); progress.textContent = ''; }
  finally { btn.disabled = false; loading.classList.remove('show'); }
}

//
async function loadReports() {
  const res = await fetch('/reports');
  const data = await res.json();
  const reports = data.reports || [];
  const tbody = document.getElementById('reportsBody');
  if (!tbody) return;

  if (reports.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#888;padding:40px">No audits yet. Upload a call to get started.</td></tr>';
  } else {
    document.getElementById('sTotalCalls').textContent = reports.length;
    const avg = reports.reduce((s, r) => s + (r.overall_score||0), 0) / reports.length;
    document.getElementById('sAvgScore').textContent = avg.toFixed(1);
    document.getElementById('sFlagged').textContent = reports.filter(r => ['critical_review','coaching_needed'].includes(r.recommendation)).length;
    const compliantPct = Math.round(reports.filter(r => r.compliance_passed).length / reports.length * 100);
    document.getElementById('sCompliance').textContent = compliantPct + '%';

    tbody.innerHTML = reports.map(r => {
      const s = r.overall_score || 0;
      const sc = s >= 8 ? 'sh' : s >= 6 ? 'sm' : 'sl';
      const rc = {excellent:'re',good:'rg',coaching_needed:'rc',critical_review:'rr'}[r.recommendation] || '';
      const date = r.audited_at ? new Date(r.audited_at).toLocaleDateString('en-IN') : '-';
      const sent = r.customer_sentiment ? r.customer_sentiment.start + ' → ' + r.customer_sentiment.end : '-';
      return '<tr>' +
        '<td>' + (r.file||'-') + '</td>' +
        '<td>' + (r.agent_name||'-') + '</td>' +
        '<td><span class="sb ' + sc + '">' + s + '/10</span></td>' +
        '<td style="font-size:12px">' + sent + '</td>' +
        '<td class="' + (r.compliance_passed?'cy':'cn') + '">' + (r.compliance_passed?'✅ Pass':'❌ Fail') + '</td>' +
        '<td><span class="rb ' + rc + '">' + (r.recommendation||'').replace('_',' ') + '</span></td>' +
        '<td>' + date + '</td>' +
        '<td><button class="vb" onclick="viewReport(this.dataset.id)" data-id="' + r.audit_id + '">View</button></td>' +
        '</tr>';
    }).join('');
  }
}

async function viewReport(id) {
  const res = await fetch('/reports/' + id);
  if (!res.ok) { showToast('Report not found'); return; }
  showModal(await res.json());
}

function showModal(report) {
  const scores = report.scores || {};
  const sentiment = report.customer_sentiment || {};
  document.getElementById('modalTitle').textContent = 'Audit: ' + (report.file || report.audit_id || '');
  document.getElementById('modalBody').innerHTML =
    '<p style="color:#888;margin-bottom:16px">' + (report.call_summary||'') + '</p>' +
    '<div class="scores-grid">' +
      Object.entries(scores).map(([k,v]) =>
        '<div class="score-item"><div class="val" style="color:' + (v>=8?'#2e7d32':v>=6?'#f57f17':'#c62828') + '">' + v + '/10</div><div class="name">' + k.charAt(0).toUpperCase()+k.slice(1) + '</div></div>'
      ).join('') +
    '</div>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px">' +
      '<div style="background:#f8f9fa;border-radius:8px;padding:12px;text-align:center"><div style="font-weight:600">' + (sentiment.start||'-') + ' &rarr; ' + (sentiment.end||'-') + '</div><div style="font-size:12px;color:#888">Customer Sentiment<List.add('open');
}

function closeModal() { document.getElementById('modal').classList.remove('open'); }

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}

boot();
setInterval(loadReports, 30000);
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/dashboard")

@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("favicon.svg", media_type="image/svg+xml")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return open("login.html").read()

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: str = Cookie(default=None)):
    token = request.query_params.get("token") or request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    if user and user.get("email") in FRANCHISE_CLIENTS:
        redirect_url = "/franchise-dashboard"
        if token:
            redirect_url += f"?token={token}"
        return RedirectResponse(url=redirect_url)
    return open("dashboard.html").read()


@app.get("/franchise-dashboard", response_class=HTMLResponse)
async def franchise_dashboard(request: Request, session: str = Cookie(default=None)):
    # Check franchise password-based session cookie first
    franchise_session = request.cookies.get("franchise_session")
    if franchise_session:
        user_email = verify_franchise_session(franchise_session)
        if user_email:
            return open("franchise_dashboard.html").read()
        return RedirectResponse(url="/franchise/login")
    # Fallback: magic-link token access
    token = request.query_params.get("token") or request.headers.get("X-Session-Token") or session
    if token:
        user = verify_session_token(token)
        if user and user.get("email") in FRANCHISE_CLIENTS:
            return open("franchise_dashboard.html").read()
    return RedirectResponse(url="/franchise/login")

@app.post("/audit/franchise")
async def audit_franchise_call(
    request: Request,
    file: UploadFile = File(...),
    agent_name: str = Form(...),
    session: str = Cookie(default=None),
):
    token = request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    if not user:
        raise HTTPException(401, "Please sign in")
    if user.get("email") not in FRANCHISE_CLIENTS:
        raise HTTPException(403, "Not authorized")
    if not agent_name.strip():
        raise HTTPException(400, "Agent name is required")

    limit = check_call_limit(user["email"])
    if not limit["allowed"]:
        raise HTTPException(403, f"Call limit reached ({limit['used']}/{limit['limit']})")

    if not file.filename.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
        raise HTTPException(400, "Unsupported format. Use MP3, WAV, M4A, or OGG.")

    # Duplicate prevention — check if same file was submitted in last 5 minutes
    import time as _time
    safe_filename_check = file.filename.replace(" ", "_")
    recent_reports = sorted(Path("reports").glob("*.checklist.json"), reverse=True)[:10]
    for rf in recent_reports:
        try:
            age = _time.time() - rf.stat().st_mtime
            if age < 300:  # 5 minutes
                import json as _json
                with open(rf) as _f:
                    _d = _json.load(_f)
                if safe_filename_check in (_d.get("file", "")):
                    raise HTTPException(400, f"This file was already audited recently. Please wait before re-submitting.")
        except HTTPException:
            raise
        except:
            pass

    file_content = await file.read()
    file_id = str(uuid.uuid4())[:8]
    safe_filename = file.filename.replace(" ", "_")
    file_path = UPLOAD_DIR / f"{file_id}_{safe_filename}"
    with open(file_path, "wb") as f:
        f.write(file_content)

    try:
        from auditor import BURGER_SINGH_CRITERIA, score_call_checklist, generate_report_checklist
        from auditor import transcribe_audio, parse_transcript
        dg = await transcribe_audio(str(file_path), user_email=user["email"])
        td = parse_transcript(dg)
        if "error" in td:
            raise HTTPException(500, td["error"])
        scores = score_call_checklist(td, BURGER_SINGH_CRITERIA)
        report = generate_report_checklist(str(file_path), td, scores, BURGER_SINGH_CRITERIA)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Audit failed: {str(e)}")

    updated = increment_call_count(user["email"])
    # Create human-readable display name
    from datetime import datetime as _dt
    date_str = _dt.now().strftime("%d%b%Y")
    display_name = f"{agent_name.strip()}_{date_str}_{file_id}"

    report.update({
        "agent_name": agent_name.strip(),
        "user_email": user["email"],
        "file": safe_filename,
        "display_name": display_name,
        "file_id": file_id,
        "calls_used": updated["calls_used"],
        "calls_limit": updated["calls_limit"],
    })

    report_path = Path(f"reports/{file_id}.checklist.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Move to franchise recordings folder instead of deleting
    recorded_path = None
    try:
        import shutil
        recordings_dir = Path("franchise_recordings")
        recordings_dir.mkdir(exist_ok=True)
        recorded_path = str(recordings_dir / file_path.name)
        shutil.move(str(file_path), recorded_path)
    except:
        pass

    # Send to Telegram
    try:
        if recorded_path:
            asyncio.create_task(send_to_telegram_and_delete(recorded_path, file_id, report, user["email"]))
    except Exception as e:
        print(f"Telegram franchise error: {e}")

    return report

@app.get("/checklist-list", response_class=HTMLResponse)
async def checklist_list():
    return open("checklist_list.html").read()

@app.get("/checklist-reports-list")
async def checklist_reports_list(request: Request, session: str = Cookie(default=None)):
    token = request.headers.get("X-Session-Token") or request.query_params.get("token") or session
    user = verify_session_token(token) if token else None
    print(f"DEBUG /checklist-reports-list called | token={str(token)[:20] if token else None} | user={user.get('email') if user else None}")
    reports = []
    for rf in sorted(Path("reports").glob("*.checklist.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(rf) as f:
                d = json.load(f)
            # Show report if user_email matches OR if admin viewing all
            if user and d.get("user_email") == user.get("email"):
                reports.append(d)
        except Exception:
            continue
    return {"reports": reports}

@app.get("/checklist-report", response_class=HTMLResponse)
async def checklist_report():
    return open("checklist_report.html").read()

from fastapi.responses import FileResponse



# ── Google OAuth ────────────────────────────────────────────────────────────────

@app.get("/auth/google")
async def google_login(request: Request):
    import secrets
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    redirect_uri = BASE_URL + "/auth/google/callback"
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)

@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error or not code:
        return RedirectResponse(url="/login?error=google_failed")
    try:
        import httpx
        redirect_uri = BASE_URL + "/auth/google/callback"
        # Exchange code for token
        async with httpx.AsyncClient() as client:
            token_res = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            token_data = token_res.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise Exception(f"No access token: {token_data}")
            # Get user info
            user_res = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"})
            userinfo = user_res.json()
        email = userinfo.get("email")
        name = userinfo.get("name", email.split("@")[0])
        if not email:
            raise Exception("No email from Google")
        create_or_get_user(email, name, "Google Sign-In", "trial")
        session_token = create_session_token(email)
        print(f"Google OAuth success: {email}, session={session_token[:10]}...")
        return RedirectResponse(url=f"/dashboard?token={session_token}")
    except Exception as e:
        print(f"Google OAuth error: {e}")
        return RedirectResponse(url="/login?error=google_failed")


# ── Magic Link ──────────────────────────────────────────────────────────────────

@app.get("/auth/verify")
async def verify_magic_link(token: str):
    user = get_user_by_token(token)
    if not user:
        return HTMLResponse("""<!DOCTYPE html>
<html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#080C12;color:white">
<h2 style="color:#FF4060">❌ Link expired or already used</h2>
<p style="color:#6B7A99;margin:16px 0">Magic links expire after 24 hours and are single-use.</p>
<a href="/login" style="background:#00E5A0;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700">Get New Link →</a>
</body></html>""")
    session_token = create_session_token(user["email"])
    return RedirectResponse(url=f"/dashboard?token={session_token}", status_code=302)

@app.post("/auth/login")
async def request_magic_link(email: str = Form(...)):
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(404, "No account found with this email. Please sign up first.")
    token = create_magic_token(email)
    await send_magic_link(email, user["name"], token)
    return {"success": True, "message": "Magic link sent to your email"}

@app.get("/auth/me")
async def get_me(request: Request, session: str = Cookie(default=None)):
    token = request.headers.get("X-Session-Token") or session
    if not token:
        raise HTTPException(401, "Not authenticated")
    user = verify_session_token(token)
    if not user:
        raise HTTPException(401, "Session expired")
    return user

async def send_to_telegram_and_delete(file_path: str, file_id: str, report: dict, user_email: str):
    import httpx
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("❌ Telegram not configured, skipping")
        return
    try:
        # Handle both standard and checklist reports
        is_checklist = report.get("mode") == "checklist"
        if is_checklist:
            score_str = report.get("score_display", "N/A")
            result_str = f"{report.get('agent_name', 'Agent')} | Franchise Call"
            compliance_str = "Checklist Mode"
        else:
            score_str = f"{report.get('overall_score', 'N/A')}/10"
            result_str = report.get('recommendation', 'N/A')
            compliance_str = 'Pass' if report.get('compliance_passed') else 'Fail'

        display_name = report.get("display_name") or report.get("agent_name", "") + "_" + report.get("file", "")
        caption = (
            f"🎙️ New Call Audit\n"
            f"👤 User: {user_email}\n"
            f"🏷️ ID: {display_name}\n"
            f"📁 File: {Path(file_path).name}\n"
            f"⭐ Score: {score_str}\n"
            f"📋 Result: {result_str}\n"
            f"✅ Compliance: {compliance_str}"
        )
        # Check if file exists before sending
        if not Path(file_path).exists():
            # Try franchise_recordings folder
            alt_path = Path("franchise_recordings") / Path(file_path).name
            if alt_path.exists():
                file_path = str(alt_path)
            else:
                print(f"❌ Audio file not found: {file_path}")
                # Send text notification only
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        data={"chat_id": chat_id, "text": caption},
                        timeout=30
                    )
                return

        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as audio:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendAudio",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"audio": audio},
                    timeout=60
                )
        print(f"✅ Sent to Telegram: {file_id}")
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")
    finally:
        try:
            Path(file_path).unlink()
            print(f"🗑️ Deleted audio: {file_path}")
        except Exception as e:
            print(f"❌ Delete failed: {e}")

# ── Audit ───────────────────────────────────────────────────────────────────────

@app.post("/audit")
async def audit_single_call(
    request: Request,
    file: UploadFile = File(...),
    client_name: str = Form(default=""),
    agent_name: str = Form(default=""),
    criteria: str = Form(default=DEFAULT_CRITERIA),
    session: str = Cookie(default=None),
):
    token = request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    if not user:
        raise HTTPException(401, "Please sign in to audit calls")

    limit = check_call_limit(user["email"])
    if not limit["allowed"]:
        raise HTTPException(403, f"Trial limit reached ({limit['used']}/{limit['limit']} calls used). Upgrade at auditiq.nxtautomation.online")

    if not file.filename.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
        raise HTTPException(400, "Unsupported format. Use MP3, WAV, M4A, or OGG.")

    file_content = await file.read()
    file_size_mb = len(file_content) / (1024 * 1024)

    # Cap trial users to 1 min audio (~1.5MB)
    if user.get("plan", "trial") == "trial" and file_size_mb > 200:
        raise HTTPException(400, f"Free trial is limited to 1-minute audio files ({file_size_mb:.1f}MB uploaded). Upgrade to audit longer calls.")

    file_id = str(uuid.uuid4())[:8]
    file_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(file_content)

    context = " ".join(filter(None, [f"Client: {client_name}" if client_name else "", f"Agent: {agent_name}" if agent_name else ""])).strip()
    try:
        report = await audit_call(str(file_path), criteria, context, save_report=False, user_email=user["email"])
    except Exception as e:
        raise HTTPException(500, f"Audit failed: {str(e)}")

    updated = increment_call_count(user["email"])
    calls_used = updated["calls_used"]
    calls_limit = updated["calls_limit"]
    report.update({
        "audit_id": file_id,
        "client_name": client_name,
        "agent_name": agent_name,
        "user_email": user["email"],
        "calls_used": calls_used,
        "calls_limit": calls_limit,
        "calls_remaining": calls_limit - calls_used,
    })
    # Send warning email at 45 calls
    if calls_used == 45:
        asyncio.create_task(send_trial_warning_email(user["email"], user.get("name", "there"), calls_used, calls_limit))

    with open(REPORTS_DIR / f"{file_id}.json", "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    # Send to Telegram and delete audio
    asyncio.create_task(send_to_telegram_and_delete(str(file_path), file_id, report, user["email"]))
    return JSONResponse(report)


@app.post("/audit/batch")
async def audit_batch_calls(
    request: Request,
    files: list[UploadFile] = File(...),
    client_name: str = Form(default=""),
    criteria: str = Form(default=DEFAULT_CRITERIA),
    session: str = Cookie(default=None),
):
    token = request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    results = []

    for file in files:
        if user:
            limit = check_call_limit(user["email"])
            if not limit["allowed"]:
                results.append({"file": file.filename, "status": "failed", "error": "Trial limit reached"})
                continue

        file_id = str(uuid.uuid4())[:8]
        file_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())

        try:
            report = await audit_call(str(file_path), criteria, f"Client: {client_name}", save_report=False)
            agent_name = file.filename.rsplit(".", 1)[0]
            report.update({
                "audit_id": file_id,
                "client_name": client_name,
                "agent_name": agent_name,
                "user_email": user["email"] if user else "anonymous",
            })
            if user:
                increment_call_count(user["email"])
            with open(REPORTS_DIR / f"{file_id}.json", "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            asyncio.create_task(send_to_telegram_and_delete(str(file_path), file_id, report, user["email"] if user else "anonymous"))
            results.append({"file": file.filename, "audit_id": file_id, "status": "success", "score": report.get("overall_score")})
        except Exception as e:
            results.append({"file": file.filename, "status": "failed", "error": str(e)})

    return {"total": len(files), "results": results}


# ── Reports ─────────────────────────────────────────────────────────────────────

@app.get("/reports")
async def list_reports(request: Request, session: str = Cookie(default=None)):
    token = request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    user_email = user["email"] if user else None
    print(f"DEBUG /reports called | token={str(token)[:20] if token else None} | user={user_email}")
    reports = []

    for rf in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            with open(rf) as f:
                data = json.load(f)
        except Exception:
            continue

        report_email = data.get("user_email", "anonymous")
        # Authenticated: only own reports. Anonymous: only anonymous reports.
        if user_email and report_email != user_email:
            continue
        if not user_email and report_email != "anonymous":
            continue

        reports.append({
            "audit_id": data.get("audit_id"),
            "file": data.get("file"),
            "audited_at": data.get("audited_at"),
            "overall_score": data.get("overall_score"),
            "recommendation": data.get("recommendation"),
            "compliance_passed": data.get("compliance_passed"),
            "resolution_status": data.get("resolution_status"),
            "customer_sentiment": data.get("customer_sentiment"),
            "client_name": data.get("client_name", ""),
            "agent_name": data.get("agent_name", ""),
        })

    return {"total": len(reports), "reports": reports}


@app.get("/reports/{audit_id}")
async def get_report(audit_id: str, request: Request, session: str = Cookie(default=None)):
    # Try standard report first
    report_path = REPORTS_DIR / f"{audit_id}.json"
    if not report_path.exists():
        # Try checklist report
        report_path = REPORTS_DIR / f"{audit_id}.checklist.json"
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    with open(report_path) as f:
        data = json.load(f)
    token = request.headers.get("X-Session-Token") or session
    user = verify_session_token(token) if token else None
    if user and data.get("user_email") not in (user["email"], "anonymous"):
        raise HTTPException(403, "Access denied")
    return data


# ── Leads ───────────────────────────────────────────────────────────────────────

@app.post("/leads")
async def create_lead(
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(...),
    volume: str = Form(default=""),
    plan: str = Form(default="trial"),
):
    try:
        await handle_new_lead(name, email, company, volume, plan)
        create_or_get_user(email, name, company, plan)
        token = create_magic_token(email)
        await send_magic_link(email, name, token)
        return {"success": True, "message": "Account created! Check your email for dashboard access."}
    except Exception as e:
        raise HTTPException(500, f"Registration failed: {str(e)}")

@app.get("/leads")
async def list_leads():
    leads = get_all_leads()
    return {"total": len(leads), "leads": leads}


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

import psycopg2
import psycopg2.extras

ADMIN_USERS = {
    os.getenv("ADMIN_EMAIL"): os.getenv("ADMIN_PASSWORD")
}

def verify_admin_session(admin_session: str):
    if not admin_session:
        return None
    try:
        conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31")
        cur = conn.cursor()
        from datetime import datetime as _dt
        cur.execute("SELECT email FROM sessions WHERE token=%s AND expires_at > %s", [admin_session, _dt.now().strftime("%Y-%m-%dT%H:%M:%S")])
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] in ADMIN_USERS:
            return {"email": row[0]}
    except Exception:
        pass
    return None

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return open("admin_login.html").read()

@app.post("/admin/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    expected = ADMIN_USERS.get(email)
    if not expected or password != expected:
        raise HTTPException(401, "Invalid admin credentials")
    session_token = create_session_token(email)
    response = JSONResponse({"success": True})
    response.set_cookie(key="admin_session", value=session_token, max_age=86400, httponly=True, samesite="lax")
    return response

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        return RedirectResponse(url="/admin/login")
    return open("admin.html").read()

@app.get("/admin/me")
async def admin_me(admin_session: str = Cookie(default=None)):
    admin = verify_admin_session(admin_session)
    if not admin:
        raise HTTPException(401, "Not authenticated")
    return admin

@app.get("/admin/users")
async def admin_list_users(admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    import psycopg2, psycopg2.extras
    conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31", cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute("SELECT email, name, company, plan, calls_used, calls_limit, is_active, created_at FROM users ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    users = [{"email": r["email"], "name": r["name"], "company": r["company"], "plan": r["plan"], "calls_used": r["calls_used"], "calls_limit": r["calls_limit"], "is_active": bool(r["is_active"]), "created_at": r["created_at"]} for r in rows]
    return {"total": len(users), "users": users}

@app.post("/admin/users/update")
async def admin_update_user(request: Request, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    data = await request.json()
    email = data.get("email")
    if not email:
        raise HTTPException(400, "Email required")
    import psycopg2
    conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31")
    cur = conn.cursor()
    if data.get("reset_usage"):
        cur.execute("UPDATE users SET plan=%s, calls_limit=%s, calls_used=0 WHERE email=%s", [data.get("plan"), data.get("calls_limit"), email])
    else:
        cur.execute("UPDATE users SET plan=%s, calls_limit=%s WHERE email=%s", [data.get("plan"), data.get("calls_limit"), email])
    conn.commit()
    cur.close()
    conn.close()
    return {"success": True}

@app.post("/admin/users/toggle")
async def admin_toggle_user(request: Request, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    data = await request.json()
    email = data.get("email")
    if not email:
        raise HTTPException(400, "Email required")
    import psycopg2
    conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31")
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_active=%s WHERE email=%s", [1 if data.get("is_active") else 0, email])
    conn.commit()
    cur.close()
    conn.close()
    return {"success": True}

@app.get("/admin/reports")
async def admin_list_reports(admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(401, "Not authenticated")
    reports = []
    standard_files = [f for f in REPORTS_DIR.glob("*.json") if not f.name.endswith(".checklist.json")]
    checklist_files = list(REPORTS_DIR.glob("*.checklist.json"))
    all_files = sorted(standard_files + checklist_files, key=lambda x: x.stat().st_mtime, reverse=True)
    for rf in all_files:
        try:
            with open(rf) as f:
                d = json.load(f)
            mode = d.get("mode", "standard")
            if mode == "checklist":
                score_display = d.get("score_display", f"{d.get('total_score',0)}/{d.get('max_score',85)}")
                reports.append({
                    "audit_id": d.get("audit_id"),
                    "user_email": d.get("user_email", "anonymous"),
                    "file": d.get("file"),
                    "agent_name": d.get("agent_name", ""),
                    "overall_score": score_display,
                    "compliance_passed": True,
                    "recommendation": "checklist",
                    "audited_at": d.get("audited_at"),
                    "mode": "checklist"
                })
            else:
                reports.append({
                    "audit_id": d.get("audit_id"),
                    "user_email": d.get("user_email", "anonymous"),
                    "file": d.get("file"),
                    "agent_name": d.get("agent_name", ""),
                    "overall_score": d.get("overall_score"),
                    "compliance_passed": d.get("compliance_passed"),
                    "recommendation": d.get("recommendation"),
                    "audited_at": d.get("audited_at"),
                    "mode": "standard"
                })
        except Exception:
            continue
    return {"total": len(reports), "reports": reports}

@app.get("/admin/report/{audit_id}")
async def get_report_detail(audit_id: str, admin_session: str = Cookie(default=None)):
    if not verify_admin_session(admin_session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Try standard report first
    report_path = Path(f"reports/{audit_id}.json")
    if report_path.exists():
        with open(report_path, "r") as f:
            return json.load(f)
    # Search all checklist reports by audit_id field
    for rf in Path("reports").glob("*.checklist.json"):
        try:
            with open(rf) as f:
                d = json.load(f)
            if d.get("audit_id") == audit_id:
                return d
        except:
            continue
    raise HTTPException(status_code=404, detail="Report not found")
# ══════════════════════════════════════════════════════════════════════════════

# ── Franchise Login ─────────────────────────────────────────────────────────────

def verify_franchise_session(franchise_session: str):
    if not franchise_session:
        return None
    try:
        import psycopg2
        from datetime import datetime as _dt
        conn = psycopg2.connect(host="localhost", port=5434, database="auditiq", user="postgres", password="VPS@31")
        cur = conn.cursor()
        cur.execute("SELECT email FROM sessions WHERE token=%s AND expires_at > %s", [franchise_session, _dt.now().strftime("%Y-%m-%dT%H:%M:%S")])
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] in FRANCHISE_CLIENTS:
            return row[0]
    except Exception as e:
        print(f"franchise session error: {e}")
    return None

@app.get("/franchise/login", response_class=HTMLResponse)
async def franchise_login_page():
    return open("franchise_login.html").read()

@app.post("/franchise/login")
@limiter.limit("5/minute")
async def franchise_login(request: Request, email: str = Form(...), password: str = Form(...)):
    expected = FRANCHISE_USERS.get(email)
    if not expected or password != expected:
        raise HTTPException(401, "Invalid credentials")
    session_token = create_session_token(email)
    response = JSONResponse({"success": True, "token": session_token})
    response.set_cookie(key="franchise_session", value=session_token, max_age=86400, httponly=True, samesite="lax")
    return response

@app.get("/franchise/logout")
async def franchise_logout():
    response = RedirectResponse(url="/franchise/login")
    response.delete_cookie("franchise_session")
    return response
