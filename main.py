from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import os
import httpx
from dotenv import load_dotenv
import uvicorn
from decimal import Decimal
import json
import datetime

load_dotenv()

# ============================================
# 1. إنشاء تطبيق FastAPI
# ============================================

app = FastAPI(title="TelAgent")

# ============================================
# 2. المتغيرات البيئية
# ============================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_RECIPIENT = os.getenv("PAYMENT_RECIPIENT_SOLANA")

if not BOT_TOKEN:
    raise Exception("❌ TELEGRAM_BOT_TOKEN not found!")
if not PAYMENT_RECIPIENT:
    raise Exception("❌ PAYMENT_RECIPIENT_SOLANA not found!")

# ============================================
# 3. دالة توليد استجابة x402
# ============================================

def x402_response():
    """توليد استجابة 402 Payment Required مع Headers الصحيحة"""
    payment_requirements = {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "solana",
                "maxAmountRequired": 10000,
                "asset": "USDC",
                "description": "Pay 0.01 USDC for one Telegram message"
            }
        ],
        "resource": "/api/v1/telegram/send",
        "recipient": PAYMENT_RECIPIENT
    }
    
    return JSONResponse(
        status_code=402,
        headers={
            "X-PAYMENT-REQUIREMENTS": json.dumps(payment_requirements),
            "X-PAYMENT-VERSION": "2"
        },
        content={
            "error": "Payment Required",
            "message": "Please pay 0.01 USDC to send this message",
            "amount": "0.01",
            "currency": "USDC",
            "recipient": PAYMENT_RECIPIENT,
            "network": "solana",
            "resource": "/api/v1/telegram/send"
        }
    )

# ============================================
# 4. Middleware (معدل - لا يعترض Discovery)
# ============================================

@app.middleware("http")
async def x402_middleware(request: Request, call_next):
    """اعتراض الطلبات فقط لنقطة النهاية المدفوعة"""
    
    # المسارات المستثناة تماماً (تعمل بشكل طبيعي)
    excluded_paths = [
        "/",
        "/terms",
        "/privacy-short",
        "/.well-known/x402",
        "/docs",
        "/openapi.json"
    ]
    
    # إذا كان المسار مستثنى، استمر كالمعتاد
    if request.url.path in excluded_paths:
        return await call_next(request)
    
    # المسارات المحمية (تتطلب دفع x402)
    protected_paths = ["/api/v1/telegram/send"]
    
    # إذا كان المسار محمياً والطريقة GET أو OPTIONS -> طلب دفع
    if request.url.path in protected_paths and request.method in ["GET", "OPTIONS"]:
        return x402_response()
    
    # للطلبات العادية (POST, PUT, إلخ) أو المسارات الأخرى
    response = await call_next(request)
    return response

# ============================================
# 5. نماذج الطلب
# ============================================

class SendMessageRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str

class RegisterAgentRequest(BaseModel):
    wallet: str
    terms_accepted: bool

# ============================================
# 6. تخزين مؤقت للموافقات
# ============================================

agent_consents = {}

def check_agent_consent(wallet: str) -> bool:
    return agent_consents.get(wallet, {}).get("consent", False)

# ============================================
# 7. نقطة نهاية إرسال الرسالة (POST)
# ============================================

@app.post("/api/v1/telegram/send")
async def send_telegram_message(request: Request, body: SendMessageRequest):
    # التحقق من موافقة العميل
    if not check_agent_consent(body.agent_wallet):
        return JSONResponse(
            status_code=403,
            content={
                "error": "Consent Required",
                "message": "You must accept the Terms of Service and Privacy Policy before using this API.",
                "action": "Please register at /api/agent/register with terms_accepted=true"
            }
        )
    
    x_payment = request.headers.get("X-PAYMENT")
    
    # إذا لم يكن هناك توقيع دفع -> طلب الدفع
    if not x_payment:
        return x402_response()
    
    print(f"📨 Payment signature received: {x_payment[:20]}...")
    
    # إرسال الرسالة عبر تيلغرام
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": body.to,
                "text": body.message,
                "parse_mode": "Markdown"
            },
            timeout=10.0
        )
        
        if response.status_code != 200:
            error_detail = response.json().get("description", "Unknown error")
            raise HTTPException(
                status_code=500,
                detail=f"Telegram API error: {error_detail}"
            )
        
        data = response.json()
        return {
            "success": True,
            "message_id": data["result"]["message_id"],
            "payment_verified": True,
            "cost": "0.01 USDC"
        }

# ============================================
# 8. تسجيل العميل
# ============================================

@app.post("/api/agent/register")
async def register_agent(body: RegisterAgentRequest):
    if not body.terms_accepted:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Terms Not Accepted",
                "message": "You must accept the Terms of Service and Privacy Policy."
            }
        )
    
    agent_consents[body.wallet] = {
        "consent": True,
        "timestamp": datetime.datetime.now().isoformat(),
        "ip": "recorded"
    }
    
    return {
        "success": True,
        "message": "Agent registered successfully. You can now use the API.",
        "wallet": body.wallet,
        "consent_given": True,
        "timestamp": agent_consents[body.wallet]["timestamp"]
    }

# ============================================
# 9. ملف Discovery (JSON) - متوافق مع x402
# ============================================

@app.get("/.well-known/x402")
async def discovery():
    return JSONResponse(
        content={
            "version": "1.0",
            "identifier": "telagent",
            "name": "TelAgent - Telegram API",
            "description": "Send Telegram messages for AI Agents with x402 payments",
            "owner": {
                "name": "TelAgent",
                "website": "https://telagent.dev"
            },
            "servers": [
                {
                    "url": "https://telagent.onrender.com"
                }
            ],
            "resources": [
                {
                    "path": "/api/v1/telegram/send",
                    "method": "POST",
                    "description": "Send a Telegram message",
                    "price": "0.01",
                    "price_unit": "per message"
                }
            ],
            "x402_required": True
        },
        media_type="application/json"
    )

# ============================================
# 10. شعارات SVG
# ============================================

LOGO_ICON_HTML = """
<div style="width:44px;height:44px;border-radius:14px;overflow:hidden;flex-shrink:0;">
    <svg width="44" height="44" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" rx="22" fill="url(#g3)"/>
        <rect x="2" y="2" width="96" height="96" rx="20" stroke="white" stroke-width="0.5" opacity="0.2"/>
        <path d="M32 28H68V38H54V72H46V38H32V28Z" fill="white" opacity="0.95"/>
        <defs><linearGradient id="g3" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f46e5"/><stop offset="50%" stop-color="#7c3aed"/><stop offset="100%" stop-color="#a78bfa"/></linearGradient></defs>
    </svg>
</div>
"""

LOGO_MINI_HTML = """
<div style="width:24px;height:24px;border-radius:8px;overflow:hidden;flex-shrink:0;">
    <svg width="24" height="24" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" rx="16" fill="url(#g4)"/>
        <path d="M30 25H70V35H55V75H45V35H30V25Z" fill="white" opacity="0.95"/>
        <defs><linearGradient id="g4" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f46e5"/><stop offset="50%" stop-color="#7c3aed"/><stop offset="100%" stop-color="#a78bfa"/></linearGradient></defs>
    </svg>
</div>
"""

# ============================================
# 11. الصفحة الرئيسية (HTML)
# ============================================

@app.get("/")
async def root():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TelAgent — Enterprise Telegram API for AI Agents</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #070a14; min-height: 100vh; display: flex; align-items: center; justify-content: center; color: #e8edf5; padding: 24px; background-image: radial-gradient(ellipse at 20% 50%, rgba(79,70,229,0.1) 0%, transparent 60%), radial-gradient(ellipse at 80% 50%, rgba(124,58,237,0.08) 0%, transparent 60%); }
        .container { max-width: 1000px; width: 100%; background: rgba(255,255,255,0.02); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.06); border-radius: 60px; padding: 60px 56px; box-shadow: 0 40px 120px rgba(0,0,0,0.8); }
        .nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 48px; flex-wrap: wrap; gap: 16px; }
        .nav-logo { display: flex; align-items: center; gap: 12px; }
        .nav-links { display: flex; gap: 28px; font-size: 14px; font-weight: 500; flex-wrap: wrap; }
        .nav-links a { color: #94a3b8; text-decoration: none; transition: color 0.2s; }
        .nav-links a:hover { color: #e8edf5; }
        .nav-links .btn { background: linear-gradient(135deg, #4f46e5, #7c3aed); padding: 8px 20px; border-radius: 40px; color: white !important; }
        .nav-links .btn:hover { opacity: 0.85; }
        .badge-group { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 32px; }
        .badge { font-size: 11px; font-weight: 600; padding: 6px 16px; border-radius: 40px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); color: #94a3b8; letter-spacing: 0.4px; text-transform: uppercase; }
        .badge.green { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.2); color: #6ee7b7; }
        .badge.purple { background: rgba(167,139,250,0.08); border-color: rgba(167,139,250,0.2); color: #c4b5fd; }
        .badge.blue { background: rgba(96,165,250,0.08); border-color: rgba(96,165,250,0.2); color: #90b4f0; }
        .hero { margin-bottom: 48px; }
        .hero h1 { font-size: 48px; font-weight: 700; line-height: 1.2; margin-bottom: 16px; background: linear-gradient(to right, #f8fafc, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; letter-spacing: -1px; }
        .hero p { font-size: 18px; color: #94a3b8; max-width: 600px; line-height: 1.6; }
        .hero p .highlight { color: #a78bfa; font-weight: 500; }
        .endpoint-box { background: rgba(0,0,0,0.4); border-radius: 24px; padding: 28px 32px; margin-bottom: 40px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; }
        .endpoint-left .label { font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; }
        .endpoint-left .code { font-family: 'JetBrains Mono', monospace; font-size: 20px; color: #86efac; }
        .endpoint-left .code .method { color: #fcd34d; }
        .endpoint-right { display: flex; align-items: center; gap: 16px; }
        .price-tag { background: linear-gradient(135deg, #4f46e5, #7c3aed); padding: 6px 20px; border-radius: 40px; font-size: 14px; font-weight: 600; color: white; }
        .status-badge { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #6ee7b7; }
        .status-badge .dot { width: 8px; height: 8px; background: #6ee7b7; border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 20px; }
        .info-card { background: rgba(255,255,255,0.03); border-radius: 20px; padding: 20px 24px; border: 1px solid rgba(255,255,255,0.04); transition: background 0.2s; }
        .info-card:hover { background: rgba(255,255,255,0.06); }
        .info-card .icon { font-size: 24px; margin-bottom: 12px; display: block; }
        .info-card .icon.bot-icon { font-size: 28px; line-height: 1; }
        .info-card .label { font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.4px; color: #64748b; margin-bottom: 4px; }
        .info-card .value { font-size: 16px; font-weight: 500; color: #e8edf5; }
        .info-card .value a { color: #90b4f0; text-decoration: none; }
        .info-card .value a:hover { text-decoration: underline; }
        .consent-box { background: rgba(167,139,250,0.08); border: 1px solid rgba(167,139,250,0.15); border-radius: 16px; padding: 20px 24px; margin-top: 24px; }
        .consent-box .title { color: #a78bfa; font-weight: 600; font-size: 14px; margin-bottom: 8px; }
        .consent-box .text { color: #94a3b8; font-size: 13px; line-height: 1.6; }
        .consent-box .text strong { color: #e8edf5; }
        .footer { margin-top: 48px; padding-top: 24px; border-top: 1px solid rgba(255,255,255,0.04); display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #64748b; flex-wrap: wrap; gap: 16px; }
        .footer a { color: #64748b; text-decoration: none; margin-left: 20px; }
        .footer a:hover { color: #e8edf5; }
        .footer .consent-notice { font-size: 11px; color: #64748b; max-width: 600px; line-height: 1.5; }
        @media (max-width: 768px) { .container { padding: 32px 20px; border-radius: 32px; } .hero h1 { font-size: 32px; } .nav { flex-direction: column; align-items: flex-start; } .nav-links { gap: 16px; } .endpoint-box { flex-direction: column; align-items: flex-start; gap: 16px; } .endpoint-left .code { font-size: 16px; } .grid-3 { grid-template-columns: 1fr; } .footer { flex-direction: column; align-items: flex-start; } .footer a { margin-left: 0; margin-right: 16px; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <div class="nav-logo">
                """ + LOGO_ICON_HTML + """
                <span style="font-size:22px;font-weight:600;">TelAgent</span>
            </div>
            <div class="nav-links">
                <a href="/docs">Docs</a>
                <a href="/.well-known/x402">Discovery</a>
                <a href="https://x402scan.com" target="_blank" class="btn">x402scan</a>
            </div>
        </div>
        <div class="badge-group">
            <span class="badge green">● Operational</span>
            <span class="badge">⚡ x402 Protocol</span>
            <span class="badge purple">🧠 AI Agents</span>
            <span class="badge blue">📱 Telegram</span>
        </div>
        <div class="hero">
            <h1>Communication API<br>for the Agentic Economy</h1>
            <p>Pay‑per‑request <span class="highlight">Telegram API</span> built for AI Agents. Powered by <span class="highlight">x402</span> micro‑payments on Solana.</p>
        </div>

        <div class="consent-box">
            <div class="title">📋 By using this service, you agree to the following:</div>
            <div class="text">
                <strong>1. You are fully responsible</strong> for all content, messages, and communications sent via this API.<br>
                <strong>2. You agree to indemnify</strong> TelAgent from any claims, fines, or damages arising from your use.<br>
                <strong>3. Prohibited uses:</strong> No spam, illegal content, harassment, or violation of GDPR/EU AI Act.<br>
                <strong>4. Data Privacy:</strong> We process minimal data (wallet address, message logs) solely for service operation and security. No data is shared with third parties.<br>
                <strong>5. Your consent</strong> is required before using the API. Register your wallet via <code>POST /api/agent/register</code> with <code>terms_accepted: true</code>.
            </div>
        </div>

        <div class="endpoint-box">
            <div class="endpoint-left">
                <div class="label">▶ API Endpoint</div>
                <div class="code"><span class="method">POST</span> /api/v1/telegram/send</div>
            </div>
            <div class="endpoint-right">
                <span class="price-tag">$0.01 per message</span>
                <span class="status-badge"><span class="dot"></span> Ready</span>
            </div>
        </div>
        <div class="grid-3">
            <div class="info-card">
                <span class="icon bot-icon">🤖</span>
                <div class="label">Bot</div>
                <div class="value"><a href="https://t.me/TelAgentCommBot" target="_blank">@TelAgentCommBot</a></div>
            </div>
            <div class="info-card">
                <span class="icon">🔗</span>
                <div class="label">Discovery</div>
                <div class="value"><a href="/.well-known/x402">/.well-known/x402</a></div>
            </div>
            <div class="info-card">
                <span class="icon">📘</span>
                <div class="label">Documentation</div>
                <div class="value"><a href="/docs">Swagger UI</a></div>
            </div>
        </div>
        <div class="footer">
            <span style="display:flex;align-items:center;gap:8px;">
                """ + LOGO_MINI_HTML + """
                © 2026 TelAgent — Telegram API for AI Agents
            </span>
            <span class="consent-notice">
                By using this service you accept our <a href="/privacy-short" style="color:#90b4f0;">Privacy Policy</a> and <a href="/terms" style="color:#90b4f0;">Terms of Service</a>.
            </span>
        </div>
    </div>
</body>
</html>
    """)

# ============================================
# 12. صفحة شروط الخدمة (Terms)
# ============================================

@app.get("/terms")
async def terms():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Terms of Service — TelAgent</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Inter',sans-serif; background:#070a14; min-height:100vh; display:flex; align-items:center; justify-content:center; color:#e8edf5; padding:24px; background-image:radial-gradient(ellipse at 20% 50%, rgba(79,70,229,0.1) 0%, transparent 60%), radial-gradient(ellipse at 80% 50%, rgba(124,58,237,0.08) 0%, transparent 60%); }
.container { max-width:800px; width:100%; background:rgba(255,255,255,0.02); backdrop-filter:blur(20px); border:1px solid rgba(255,255,255,0.06); border-radius:60px; padding:48px 52px; box-shadow:0 40px 120px rgba(0,0,0,0.8); }
.header { display:flex; align-items:center; gap:14px; margin-bottom:32px; }
.header h1 { font-size:28px; font-weight:700; background:linear-gradient(to right, #f8fafc, #94a3b8); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
.subtitle { color:#94a3b8; font-size:15px; margin-bottom:32px; }
.section { margin-bottom:24px; }
.section h2 { font-size:16px; font-weight:600; color:#a78bfa; margin-bottom:6px; }
.section p, .section .text { color:#c8d0dc; font-size:15px; line-height:1.6; }
.section ul { color:#c8d0dc; font-size:15px; line-height:1.8; padding-left:20px; }
.footer { margin-top:40px; padding-top:20px; border-top:1px solid rgba(255,255,255,0.04); display:flex; justify-content:space-between; font-size:13px; color:#64748b; }
.footer a { color:#64748b; text-decoration:none; }
.footer a:hover { color:#e8edf5; }
@media (max-width:640px) { .container { padding:32px 20px; border-radius:32px; } .footer { flex-direction:column; gap:8px; } }
</style>
</head>
<body>
<div class="container">
    <div class="header">""" + LOGO_MINI_HTML + """<h1>Terms of Service</h1></div>
    <p class="subtitle">Last Updated: June 2026</p>
    <div class="section"><h2>1. Acceptance of Terms</h2><p class="text">By using the TelAgent API ("Service"), you agree to these Terms of Service ("Terms").</p></div>
    <div class="section"><h2>2. Service Description</h2><p class="text">TelAgent provides a pay-per-request API for sending Telegram messages via AI Agents.</p></div>
    <div class="section"><h2>3. User Responsibility</h2><p class="text">You are solely responsible for all content, messages, and communications sent via the Service.</p><p class="text"><strong>Prohibited Uses:</strong></p><ul><li>Spam or unsolicited messages</li><li>Illegal, defamatory, or threatening content</li><li>Violation of GDPR, EU AI Act, or applicable laws</li><li>Social scoring, predictive policing, or manipulative AI practices</li></ul></div>
    <div class="section"><h2>4. Indemnification</h2><p class="text">You agree to indemnify TelAgent from any claims, fines, or damages arising from your use of the Service.</p></div>
    <div class="section"><h2>5. Payment</h2><p class="text">The Service is pay-per-request. Payment is processed via x402 protocol.</p></div>
    <div class="section"><h2>6. No Warranty</h2><p class="text">THE SERVICE IS PROVIDED "AS IS" WITHOUT ANY WARRANTIES.</p></div>
    <div class="section"><h2>7. Governing Law</h2><p class="text">These Terms are governed by German law. Jurisdiction: Berlin, Germany.</p></div>
    <div class="footer"><span><a href="/">← Back to Home</a></span><span><a href="/privacy-short">Privacy Policy</a> • <a href="https://x402scan.com" target="_blank">x402scan</a></span></div>
</div>
</body>
</html>
    """)

# ============================================
# 13. صفحة سياسة الخصوصية (Privacy)
# ============================================

@app.get("/privacy-short")
async def privacy_short():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Privacy Policy — TelAgent</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Inter',sans-serif; background:#070a14; min-height:100vh; display:flex; align-items:center; justify-content:center; color:#e8edf5; padding:24px; background-image:radial-gradient(ellipse at 20% 50%, rgba(79,70,229,0.1) 0%, transparent 60%), radial-gradient(ellipse at 80% 50%, rgba(124,58,237,0.08) 0%, transparent 60%); }
.container { max-width:700px; width:100%; background:rgba(255,255,255,0.02); backdrop-filter:blur(20px); border:1px solid rgba(255,255,255,0.06); border-radius:60px; padding:48px 52px; box-shadow:0 40px 120px rgba(0,0,0,0.8); }
.header { display:flex; align-items:center; gap:14px; margin-bottom:24px; }
.header h1 { font-size:28px; font-weight:700; background:linear-gradient(to right, #f8fafc, #94a3b8); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
.subtitle { color:#94a3b8; font-size:15px; margin-bottom:24px; }
.section { margin-bottom:20px; }
.section h2 { font-size:16px; font-weight:600; color:#a78bfa; margin-bottom:4px; }
.section p { color:#c8d0dc; font-size:14px; line-height:1.6; }
.footer { margin-top:32px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.04); display:flex; justify-content:space-between; font-size:13px; color:#64748b; }
.footer a { color:#64748b; text-decoration:none; }
.footer a:hover { color:#e8edf5; }
</style>
</head>
<body>
<div class="container">
    <div class="header">""" + LOGO_MINI_HTML + """<h1>Privacy Policy</h1></div>
    <p class="subtitle">Simple and transparent data protection (DSGVO/GDPR compliant).</p>
    
    <div class="section"><h2>1. Data We Process</h2><p>• Wallet address (for payment and identification)<br>• Message content (temporarily for delivery)<br>• Timestamps and basic usage logs</p></div>
    
    <div class="section"><h2>2. Purpose</h2><p>We process data solely to operate the Telegram API service, process x402 payments, and ensure security.</p></div>
    
    <div class="section"><h2>3. Data Sharing</h2><p>We do NOT share any data with third parties. All data is stored securely within the EU.</p></div>
    
    <div class="section"><h2>4. Your Rights</h2><p>You have the right to access, correct, or delete your data at any time. Contact: <a href="mailto:legal@telagent.dev" style="color:#90b4f0;">legal@telagent.dev</a></p></div>
    
    <div class="section"><h2>5. Contact</h2><p>Email: <a href="mailto:legal@telagent.dev" style="color:#90b4f0;">legal@telagent.dev</a></p></div>
    
    <div class="footer"><span><a href="/">← Back to Home</a></span><span><a href="/terms">Terms</a> • <a href="https://x402scan.com" target="_blank">x402scan</a></span></div>
</div>
</body>
</html>
    """)

# ============================================
# 14. تشغيل الخادم
# ============================================

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)