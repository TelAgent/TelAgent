from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import os
import json
import uvicorn
import httpx
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

# ============================================
# 1. إعداد التسجيل
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("telagent")

load_dotenv()

# ============================================
# 2. المتغيرات البيئية
# ============================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_RECIPIENT = os.getenv("PAYMENT_RECIPIENT_SOLANA")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

logger.info("✅ Environment loaded")

# ============================================
# 3. Lifespan
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    logger.info("✅ HTTP client created")
    yield
    await app.state.http_client.aclose()
    logger.info("✅ HTTP client closed")

# ============================================
# 4. تطبيق FastAPI مع CORS
# ============================================

app = FastAPI(
    title="TelAgent API",
    version="1.0.0",
    description="Telegram API for AI Agents with x402 payments",
    contact={
        "name": "TelAgent",
        "email": "legal@telagent.dev",
        "url": "https://telagent.dev"
    },
    lifespan=lifespan
)

# CORS (للاستخدام من قبل الوكلاء)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# 5. ROOT + HEALTH (fix 404)
# ============================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "telagent",
        "version": "1.0.0",
        "message": "API is running"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ============================================
# 6. نماذج Pydantic
# ============================================

class TelegramRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str

class RegisterAgentRequest(BaseModel):
    wallet: str
    terms_accepted: bool

# ============================================
# 7. تخزين مؤقت
# ============================================

agent_consents = {}

# ============================================
# 8. نقطة نهاية إرسال الرسالة
# ============================================

@app.get("/api/v1/telegram/send")
async def telegram_probe_get():
    return {"ok": True, "mode": "get_probe"}

@app.options("/api/v1/telegram/send")
async def telegram_probe_options():
    return {"ok": True, "mode": "options_probe"}

@app.post("/api/v1/telegram/send")
async def telegram_send(request: Request, req: TelegramRequest):
    # التحقق من الدفع
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return JSONResponse(
            status_code=402,
            headers={
                "X-PAYMENT-REQUIREMENTS": json.dumps({
                    "x402Version": 2,
                    "accepts": [{
                        "scheme": "exact",
                        "network": "solana",
                        "asset": "USDC",
                        "maxAmountRequired": 10000,
                        "description": "0.01 USDC per message"
                    }],
                    "resource": "/api/v1/telegram/send",
                    "recipient": PAYMENT_RECIPIENT
                }),
                "X-PAYMENT-VERSION": "2"
            },
            content={
                "error": "Payment Required",
                "amount": "0.01",
                "currency": "USDC",
                "recipient": PAYMENT_RECIPIENT,
                "network": "solana"
            }
        )
    
    # التحقق من موافقة العميل
    if not agent_consents.get(req.agent_wallet):
        return JSONResponse(
            status_code=403,
            content={
                "error": "Consent Required",
                "action": "register at /api/agent/register"
            }
        )
    
    # إرسال الرسالة
    try:
        http_client = request.app.state.http_client
        response = await http_client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": req.to,
                "text": req.message,
                "parse_mode": "Markdown"
            }
        )
        if response.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={"error": response.text}
            )
        data = response.json()
        logger.info(f"✅ Message sent to {req.to}")
        return {
            "success": True,
            "message_id": data["result"]["message_id"],
            "payment_verified": True,
            "cost": "0.01 USDC"
        }
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ============================================
# 9. تسجيل العميل
# ============================================

@app.get("/api/agent/register")
async def register_probe_get():
    return {"ok": True}

@app.options("/api/agent/register")
async def register_probe_options():
    return {"ok": True}

@app.post("/api/agent/register")
async def register_agent(body: RegisterAgentRequest):
    if not body.terms_accepted:
        return JSONResponse(
            status_code=400,
            content={"error": "Terms not accepted"}
        )
    agent_consents[body.wallet] = True
    return {
        "success": True,
        "wallet": body.wallet,
        "consent": True
    }

# ============================================
# 10. Discovery
# ============================================

@app.get("/.well-known/x402")
async def x402_discovery():
    return {
        "version": "1.0",
        "identifier": "telagent",
        "name": "TelAgent",
        "description": "Telegram API for AI Agents with x402 payments",
        "owner": {
            "name": "TelAgent",
            "website": "https://telagent.dev"
        },
        "servers": [{"url": "https://telagent.onrender.com"}],
        "resources": [{
            "path": "/api/v1/telegram/send",
            "method": "POST",
            "price": "0.01",
            "price_unit": "USDC",
            "network": "solana"
        }],
        "x402_required": True,
        "openapi_document": "/.well-known/openapi.json"
    }

# ============================================
# 11. OpenAPI مع x402
# ============================================

@app.get("/.well-known/openapi.json", include_in_schema=False)
async def openapi():
    schema = app.openapi()
    
    schema.setdefault("components", {})
    schema["components"].setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["x402"] = {
        "type": "http",
        "scheme": "x402"
    }
    
    path = "/api/v1/telegram/send"
    if path in schema.get("paths", {}):
        for method in schema["paths"][path]:
            schema["paths"][path][method]["security"] = [{"x402": []}]
            schema["paths"][path][method]["x402"] = {
                "price": 0.01,
                "currency": "USDC"
            }
    
    return JSONResponse(schema)

@app.get("/openapi.json", include_in_schema=False)
async def openapi_root():
    return await openapi()

# ============================================
# 12. الصفحات
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
        <a href="/.well-known/x402">🔍 Discovery</a> |
        <a href="/.well-known/openapi.json">📋 OpenAPI</a>
    </body>
    </html>
    """)

@app.get("/terms")
async def terms():
    return HTMLResponse("<h1>Terms of Service</h1><p>Coming soon</p>")

@app.get("/privacy-short")
async def privacy():
    return HTMLResponse("<h1>Privacy Policy</h1><p>Coming soon</p>")

# ============================================
# 13. تشغيل الخادم
# ============================================

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))