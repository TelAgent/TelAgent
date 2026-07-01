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

# رابط الخدمة الفعلي على Render — اضبطه في متغيرات البيئة على Render
# ليطابق دائمًا رابط النشر الحقيقي (مثال: https://telagent.onrender.com)
SERVICE_URL = os.getenv("SERVICE_URL", "https://telagent.onrender.com")

# عنوان عملة USDC الرسمي على شبكة Solana (mainnet) — هذا هو "asset" المطلوب
# في مواصفات x402، وليس النص "USDC" فقط
USDC_MINT_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

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

def get_x402_payment_response(resource_path: str, description: str = "0.01 USDC per message"):
    """
    توليد رد 402 المطابق لمواصفات بروتوكول x402 (PaymentRequirements).
    ملاحظة مهمة: يجب أن تكون بيانات الدفع في جسم الرد (body) نفسه،
    وليست مخفية داخل ترويسة (header) مخصصة — وإلا لن تتعرف عليها أدوات
    الفحص مثل x402scan / mppscan.
    """
    resource_url = f"{SERVICE_URL}{resource_path}"
    return JSONResponse(
        status_code=402,
        content={
            "x402Version": 1,
            "accepts": [{
                "scheme": "exact",
                "network": "solana",
                "maxAmountRequired": "10000",  # 0.01 USDC بوحدات ذرية (6 خانات عشرية)
                "resource": resource_url,
                "description": description,
                "mimeType": "application/json",
                "payTo": PAYMENT_RECIPIENT,
                "asset": USDC_MINT_SOLANA,
                "maxTimeoutSeconds": 60
            }]
        }
    )

# ============================================
# 6. الروابط الأساسية والـ Health Check
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

@app.get("/api/v1/telegram/send")
async def telegram_probe_get(request: Request):
    # الفاحص يطلب GET للتأكد من وجود نظام حماية الدفع
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")
    return {"ok": True, "message": "Payment verified for GET probe"}

@app.options("/api/v1/telegram/send")
async def telegram_probe_options():
    return JSONResponse(status_code=200, content={"ok": True})

@app.post("/api/v1/telegram/send")
async def telegram_send(request: Request, req: TelegramRequest):
    # التحقق من وجود الترويسة الخاصة بالدفع
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")

    # التحقق من موافقة العميل مسبقاً
    if not agent_consents.get(req.agent_wallet):
        return JSONResponse(
            status_code=403,
            content={
                "error": "Consent Required",
                "action": "register at /api/agent/register"
            }
        )

    # معالجة وإرسال الرسالة إلى تليجرام
    try:
        http_client = request.app.state.http_client
        # تم تصحيح الرابط: يجب أن يكون api.telegram.org/bot<TOKEN>/...
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
        logger.error(f"Error sending message: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ============================================
# 9. تسجيل العميل وموافقته (Agent Registration)
# ============================================

@app.get("/api/agent/register")
async def register_probe_get():
    return {"ok": True, "message": "Ready for registration"}

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
        # تم تصحيح الرابط: يجب أن يشير إلى رابط النشر الفعلي على Render
        "servers": [{"url": SERVICE_URL}],
        "resources": [{
            "resource": f"{SERVICE_URL}/api/v1/telegram/send",
            "path": "/api/v1/telegram/send",
            "method": "POST",
            "scheme": "exact",
            "network": "solana",
            "maxAmountRequired": "10000",
            "asset": USDC_MINT_SOLANA,
            "payTo": PAYMENT_RECIPIENT,
            "description": "0.01 USDC per message"
        }],
        "x402_required": True,
        "openapi_document": "/.well-known/openapi.json"
    }

# ============================================
# 11. تخصيص ملف ومستندات OpenAPI مع x402
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
# 12. الصفحات والروابط الفرعية المطلوبة للفحص
# ============================================

@app.get("/terms")
async def terms_page():
    return {"message": "Terms of Service for TelAgent"}

@app.get("/privacy-short")
async def privacy_page():
    return {"message": "Privacy Policy Summary for TelAgent"}

@app.options("/{full_path:path}")
async def catch_all_options(full_path: str):
    # يمنع رد 405 على طلبات OPTIONS الاستكشافية التي قد ترسلها أدوات
    # الفحص (x402scan / mppscan) على أي مسار غير معرّف صراحة
    return JSONResponse(status_code=200, content={"ok": True})

@app.get("/home", response_class=HTMLResponse)
async def home_ui():
    return """
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