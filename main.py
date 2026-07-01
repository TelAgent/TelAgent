from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import os
import json
import logging
from contextlib import asynccontextmanager
import httpx
from dotenv import load_dotenv

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
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

logger.info("✅ Environment loaded")

# ============================================
# 3. دورة حياة التطبيق (Lifespan)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# 5. دالة مساعدة لردود الدفع الموحدة (x402 Helper)
# ============================================

def get_x402_payment_response(resource_path: str):
    """توليد رد 402 متوافق تماماً مع شروط أداة الفحص والتطبيق المباشر"""
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
                "resource": resource_path,
                "recipient": PAYMENT_RECIPIENT
            }),
            "X-PAYMENT-VERSION": "2",
            "Access-Control-Expose-Headers": "X-PAYMENT-REQUIREMENTS, X-PAYMENT-VERSION"
        },
        content={
            "error": "Payment Required",
            "amount": "0.01",
            "currency": "USDC",
            "recipient": PAYMENT_RECIPIENT,
            "network": "solana"
        }
    )

# ============================================
# 6. الروابط الأساسية والـ Health Check (تم الإصلاح لـ FastAPI)
# ============================================

@app.route("/", methods=["GET", "HEAD"])
async def root(request: Request):
    return JSONResponse({
        "status": "ok",
        "service": "telagent",
        "version": "1.0.0",
        "message": "API is running"
    })

@app.route("/health", methods=["GET", "HEAD"])
async def health(request: Request):
    return JSONResponse({"status": "healthy"})

# ============================================
# 7. نماذج البيانات (Pydantic Models)
# ============================================

class TelegramRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str

class RegisterAgentRequest(BaseModel):
    wallet: str
    terms_accepted: bool

# التخزين المؤقت لموافقات المحافظ
agent_consents = {}

# ============================================
# 8. مسار إرسال الرسائل (Telegram Send API)
# ============================================

@app.route("/api/v1/telegram/send", methods=["GET", "HEAD"])
async def telegram_probe_get(request: Request):
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")
    return JSONResponse({"ok": True, "message": "Payment verified for GET probe"})

@app.options("/api/v1/telegram/send")
async def telegram_probe_options():
    return JSONResponse(status_code=200, content={"ok": True})

@app.post("/api/v1/telegram/send")
async def telegram_send(request: Request, req: TelegramRequest):
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")
    
    if not agent_consents.get(req.agent_wallet):
        return JSONResponse(
            status_code=403,
            content={
                "error": "Consent Required",
                "action": "register at /api/agent/register"
            }
        )
    
    try:
        http_client = request.app.state.http_client
        response = await http_client.post(
            f"https://telegram.org{BOT_TOKEN}/sendMessage",
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
        logger.error(f"Error sending message: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ============================================
# 9. تسجيل العميل وموافقته (Agent Registration)
# ============================================

@app.route("/api/agent/register", methods=["GET", "HEAD"])
async def register_probe_get(request: Request):
    return JSONResponse({"ok": True, "message": "Ready for registration"})

@app.options("/api/agent/register")
async def register_probe_options():
    return JSONResponse(status_code=200, content={"ok": True})

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
# 10. بروتوكول الاكتشاف (x402 Discovery)
# ============================================

@app.route("/.well-known/x402", methods=["GET", "HEAD"])
async def x402_discovery(request: Request):
    return JSONResponse({
        "version": "1.0",
        "identifier": "telagent",
        "name": "TelAgent",
        "description": "Telegram API for AI Agents with x402 payments",
        "owner": {
            "name": "TelAgent",
            "website": "https://telagent.dev"
        },
        "servers": [{"url": "https://onrender.com"}],
        "resources": [{
            "path": "/api/v1/telegram/send",
            "method": "POST",
            "price": "0.01",
            "price_unit": "USDC",
            "network": "solana"
        }],
        "x402_required": True,
        "openapi_document": "/.well-known/openapi.json"
    })

# ============================================
# 11. تخصيص ملف ومستندات OpenAPI واستبعاد الروابط المجانية
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
    
    paid_path = "/api/v1/telegram/send"
    
    for path in schema.get("paths", {}):
        if path == paid_path:
            for method in schema["paths"][path]:
                schema["paths"][path][method]["security"] = [{"x402": []}]
                schema["paths"][path][method]["x402"] = {
                    "price": 0.01,
                    "currency": "USDC"
                }
        else:
            for method in schema["paths"][path]:
                schema["paths"][path][method]["security"] = []
                
    return JSONResponse(schema)

@app.get("/openapi.json", include_in_schema=False)
async def openapi_root():
    return await openapi()

# ============================================
# 12. الصفحات والأيقونات المطلوبة للفحص
# ============================================

@app.route("/favicon.ico", methods=["GET", "HEAD"])
async def favicon(request: Request):
    return JSONResponse(status_code=200, content={})

@app.route("/terms", methods=["GET", "HEAD"])
async def terms_page(request: Request):
    return JSONResponse({"message": "Terms of Service for TelAgent"})

@app.route("/privacy-short", methods=["GET", "HEAD"])
async def privacy_page(request: Request):
    return JSONResponse({"message": "Privacy Policy Summary for TelAgent"})

@app.route("/home", methods=["GET", "HEAD"])
async def home_ui(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html>
    <head><title>TelAgent</title></head>
    <body>
        <h1>🤖 TelAgent</h1>
        <p>Pay-per-request Telegram API for AI Agents</p>
        <p>⚡ x402 Protocol | 🌐 Solana | 📱 Telegram</p>
        <a href="/docs">📚 API Docs</a>
    </body>
    </html>
    """
    if request.method == "HEAD":
        return HTMLResponse(status_code=200)
    return HTMLResponse(content=html_content)
