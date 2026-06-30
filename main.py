from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import os
import httpx
import json
import datetime
import uvicorn
import redis.asyncio as redis
from dotenv import load_dotenv
import logging

# ============================================
# Logging
# ============================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telagent")

load_dotenv()

# ============================================
# ENV
# ============================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_RECIPIENT = os.getenv("PAYMENT_RECIPIENT_SOLANA")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
if not PAYMENT_RECIPIENT:
    raise RuntimeError("Missing PAYMENT_RECIPIENT_SOLANA")

logger.info("✅ Environment loaded")

# ============================================
# APP
# ============================================
app = FastAPI(
    title="TelAgent",
    version="1.0.0",
    contact={
        "name": "TelAgent",
        "email": "legal@telagent.dev"
    }
)

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
http_client = httpx.AsyncClient(timeout=10.0)

# ============================================
# MODELS
# ============================================
class SendMessage(BaseModel):
    to: str
    message: str
    agent_wallet: str

class RegisterAgent(BaseModel):
    wallet: str
    terms_accepted: bool

# ============================================
# X402 RESPONSE
# ============================================
def x402_response():
    payload = {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "solana",
                "asset": "USDC",
                "maxAmountRequired": 10000,
                "description": "0.01 USDC per Telegram message"
            }
        ],
        "resource": "/api/v1/telegram/send",
        "recipient": PAYMENT_RECIPIENT
    }

    return JSONResponse(
        status_code=402,
        headers={
            "X-PAYMENT-REQUIREMENTS": json.dumps(payload),
            "X-PAYMENT-VERSION": "2"
        },
        content={
            "error": "Payment Required",
            "amount": "0.01 USDC",
            "recipient": PAYMENT_RECIPIENT,
            "network": "solana"
        }
    )

# ============================================
# CONSENT
# ============================================
async def get_consent(wallet: str) -> bool:
    value = await redis_client.get(f"consent:{wallet}")
    return value == "true"

async def set_consent(wallet: str):
    await redis_client.set(f"consent:{wallet}", "true")

# ============================================
# PAYMENT CHECK
# ============================================
def verify_payment(header: str | None) -> bool:
    """التحقق من وجود توقيع الدفع"""
    if not header:
        return False
    # في الإنتاج: تحقق من التوقيع على Solana
    return header.startswith("0x") and len(header) > 10

# ============================================
# MIDDLEWARE
# ============================================
@app.middleware("http")
async def middleware(request: Request, call_next):
    path = request.url.path

    free_paths = {
        "/",
        "/terms",
        "/privacy",
        "/.well-known/x402",
        "/.well-known/openapi.json",
        "/docs",
        "/openapi.json"
    }

    protected = "/api/v1/telegram/send"

    if path in free_paths:
        return await call_next(request)

    if path == protected:
        if not request.headers.get("X-PAYMENT"):
            logger.info(f"⛔ Payment required for {path}")
            return x402_response()

    return await call_next(request)

# ============================================
# TELEGRAM SEND
# ============================================
@app.post("/api/v1/telegram/send")
async def send_message(request: Request, body: SendMessage):
    # Consent check
    consent = await get_consent(body.agent_wallet)
    if not consent:
        logger.warning(f"⚠️ No consent for wallet {body.agent_wallet[:10]}...")
        return JSONResponse(
            status_code=403,
            content={
                "error": "Consent required",
                "action": "register at /api/agent/register"
            }
        )

    # Payment check
    if not verify_payment(request.headers.get("X-PAYMENT")):
        return x402_response()

    logger.info(f"📨 Sending message to {body.to} from {body.agent_wallet[:10]}...")

    # Send Telegram message
    try:
        r = await http_client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": body.to,
                "text": body.message,
                "parse_mode": "Markdown"
            }
        )

        if r.status_code != 200:
            logger.error(f"❌ Telegram error: {r.text}")
            raise HTTPException(status_code=500, detail=r.text)

        data = r.json()
        logger.info(f"✅ Message sent, ID: {data['result']['message_id']}")

        return {
            "success": True,
            "message_id": data["result"]["message_id"],
            "paid": True
        }

    except httpx.TimeoutException:
        logger.error("⏰ Telegram timeout")
        raise HTTPException(status_code=504, detail="Telegram timeout")

    except Exception as e:
        logger.error(f"❌ Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# REGISTER AGENT
# ============================================
@app.post("/api/agent/register")
async def register(body: RegisterAgent):
    if not body.terms_accepted:
        return JSONResponse(
            status_code=400,
            content={"error": "Terms not accepted"}
        )

    await set_consent(body.wallet)
    logger.info(f"✅ Agent registered: {body.wallet[:10]}...")

    return {
        "success": True,
        "wallet": body.wallet,
        "consent": True,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

# ============================================
# DISCOVERY (X402)
# ============================================
@app.get("/.well-known/x402")
async def discovery():
    return {
        "version": "1.0",
        "identifier": "telagent",
        "name": "TelAgent",
        "description": "Telegram API for AI Agents with x402 payments",
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
                "price": "0.01",
                "price_unit": "USDC",
                "network": "solana"
            }
        ],
        "x402_required": True,
        "openapi_document": "/.well-known/openapi.json"
    }

# ============================================
# OPENAPI DISCOVERY
# ============================================
@app.get("/.well-known/openapi.json")
async def openapi_discovery():
    schema = app.openapi()
    # إضافة security: [] للنقاط المجانية
    free_paths = ["/", "/terms", "/privacy", "/.well-known/x402", "/api/agent/register"]
    for path, methods in schema.get("paths", {}).items():
        if path in free_paths:
            for method in methods.values():
                method["security"] = []
    # إضافة security للنقطة المدفوعة
    if "/api/v1/telegram/send" in schema.get("paths", {}):
        schema["paths"]["/api/v1/telegram/send"]["post"]["security"] = [{"x402": []}]
    
    return JSONResponse(schema)

# ============================================
# HOME PAGE
# ============================================
@app.get("/")
async def home():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head><title>TelAgent</title></head>
    <body>
        <h1>🤖 TelAgent</h1>
        <p>Pay-per-request Telegram API for AI Agents</p>
        <p>⚡ x402 Protocol | 🌐 Solana | 📱 Telegram</p>
        <a href="/docs">📚 API Docs</a> |
        <a href="/.well-known/x402">🔍 Discovery</a>
    </body>
    </html>
    """)

# ============================================
# TERMS & PRIVACY
# ============================================
@app.get("/terms")
async def terms():
    return HTMLResponse("<h1>Terms of Service</h1><p>Coming soon</p>")

@app.get("/privacy")
async def privacy():
    return HTMLResponse("<h1>Privacy Policy</h1><p>Coming soon</p>")

# ============================================
# STARTUP & SHUTDOWN
# ============================================
@app.on_event("startup")
async def startup():
    logger.info("🚀 TelAgent running...")

@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()
    await redis_client.close()
    logger.info("🛑 TelAgent shutting down...")

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)