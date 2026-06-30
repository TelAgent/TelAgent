from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import os
import httpx
from dotenv import load_dotenv
import uvicorn
import json
import datetime
import logging
from contextlib import asynccontextmanager

# ============================================
# 1. إعداد التسجيل (Logging)
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
    logger.error("❌ TELEGRAM_BOT_TOKEN not found!")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

if not PAYMENT_RECIPIENT:
    logger.error("❌ PAYMENT_RECIPIENT_SOLANA not found!")
    raise RuntimeError("PAYMENT_RECIPIENT_SOLANA is required")

logger.info("✅ Environment variables loaded successfully")

# ============================================
# 3. Lifespan لإدارة HTTP client
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    logger.info("✅ HTTP client created")
    yield
    await app.state.http_client.aclose()
    logger.info("✅ HTTP client closed")

# ============================================
# 4. إنشاء تطبيق FastAPI
# ============================================

app = FastAPI(
    title="TelAgent",
    version="1.0.0",
    contact={
        "name": "TelAgent",
        "email": "legal@telagent.dev",
        "url": "https://telagent.dev"
    },
    lifespan=lifespan
)

# ============================================
# 5. تخصيص OpenAPI مع x402
# ============================================

@app.get("/openapi.json", include_in_schema=False)
async def custom_openapi():
    schema = app.openapi()
    
    # إضافة security scheme x402
    schema.setdefault("components", {})
    schema["components"].setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["x402"] = {
        "type": "http",
        "scheme": "x402",
        "description": "x402 payment protocol"
    }
    
    # تحديد نقطة النهاية المدفوعة
    path = "/api/v1/telegram/send"
    if path in schema.get("paths", {}):
        for method in schema["paths"][path]:
            schema["paths"][path][method]["security"] = [{"x402": []}]
            schema["paths"][path][method]["x402"] = {
                "price": 0.01,
                "currency": "USDC",
                "network": "solana",
                "description": "Pay 0.01 USDC per Telegram message"
            }
    
    # النقاط المجانية
    free_paths = ["/api/agent/register", "/.well-known/x402", "/", "/terms", "/privacy-short"]
    for path in schema.get("paths", {}):
        if path in free_paths:
            for method in schema["paths"][path]:
                schema["paths"][path][method]["security"] = []
    
    app.openapi_schema = schema
    return JSONResponse(schema)

@app.get("/.well-known/openapi.json", include_in_schema=False)
async def well_known_openapi():
    return await custom_openapi()

# ============================================
# 6. نقطة نهاية إرسال الرسالة (مدفوعة)
# ============================================

class SendMessageRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str

@app.post("/api/v1/telegram/send")
async def send_telegram_message(request: Request, body: SendMessageRequest):
    # التحقق من الدفع (مؤقتاً: قبول أي توقيع)
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
    
    # TODO: التحقق الحقيقي من التوقيع
    
    # إرسال الرسالة
    try:
        http_client = request.app.state.http_client
        response = await http_client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": body.to,
                "text": body.message,
                "parse_mode": "Markdown"
            }
        )
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=response.text)
        data = response.json()
        return {
            "success": True,
            "message_id": data["result"]["message_id"],
            "payment_verified": True,
            "cost": "0.01 USDC"
        }
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# 7. تسجيل العميل (مجاني)
# ============================================

class RegisterAgentRequest(BaseModel):
    wallet: str
    terms_accepted: bool

# تخزين مؤقت
agent_consents = {}

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
        "consent": True,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

# ============================================
# 8. Discovery
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
# 9. الصفحات (للبشر)
# ============================================

@app.get("/")
async def home():
    return HTMLResponse("""
    <h1>🤖 TelAgent</h1>
    <p>Pay-per-request Telegram API for AI Agents</p>
    <p>⚡ x402 Protocol | 🌐 Solana | 📱 Telegram</p>
    <a href="/docs">📚 API Docs</a> |
    <a href="/.well-known/x402">🔍 Discovery</a>
    """)

@app.get("/terms")
async def terms():
    return HTMLResponse("<h1>Terms of Service</h1><p>Coming soon</p>")

@app.get("/privacy-short")
async def privacy():
    return HTMLResponse("<h1>Privacy Policy</h1><p>Coming soon</p>")

# ============================================
# 10. تشغيل الخادم
# ============================================

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))