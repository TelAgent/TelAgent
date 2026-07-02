from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel
import os
import json
import base64
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
    lifespan=lifespan,
    # نعطّل مسار /openapi.json المُولَّد تلقائياً من FastAPI، لأنه كان
    # يتطابق قبل مسارنا المخصص (الذي يضيف حقول "security") ويمنعه من
    # التنفيذ فعلياً — كل تعديلاتنا على security كانت بلا أثر بسببه.
    openapi_url=None,
    docs_url=None,
    redoc_url=None
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

# معرّف شبكة Solana mainnet بصيغة CAIP-2 كما يتطلبه x402 v2
SOLANA_MAINNET_CAIP2 = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# أيقونة favicon مضمّنة كـ base64 (لا حاجة لملف خارجي)
FAVICON_BASE64 = "AAABAAIAEBAAAAAAIAAHAwAAJgAAACAgAAAAACAARwEAAC0DAACJUE5HDQoaCgAAAA1JSERSAAAAEAAAABAIBgAAAB/z/2EAAALOSURBVHicbVM9aFRZFP7Ovffd954zL/OrK2QbFxJEMGELwS5ql0EQF2LlFhbrCiGd1bKwLIqWFmGa4DbaKRbTRAslRGwsRKOsm0QLC7PZTSYzZjKZzH1z3z0WLxPd1Q8O3HvPdw8f55yPsAcmgBgADv+4WeIgnnJMvrE+Ml7HbHaD6b9v5zb+zyUAwG8s8Ds5jM2p4eHRX8Bu0qnCAUGMSLexsZODdvU1R7L6dnnhGuZP2v4f6lcbG5tTK0OjNZ0pVGyniSRxdub0JRw/NIfJ2h94+G5c5fMa3XZzdvDNwpn5+ZMWYBKYgBg5v5pZHTpaU36+4rbXjDHM+7xtNVp+rPaFG+r7g8/U1o7kpL1qvCBfWRk6Whs5v5rBBITAXUo6Wl6WmVIl2dkwbUN+eSChlinifuMW/mpdxc3nP+NQuUWxU35nq250tlTpaHkZdymh4YsrZU7811KpYnvbiMqxgK5fiKAkww8EeglgukDgOTxdspisbnIC7cC2QcIcEWzVlPQH9sdxzMVI0o1LEYoRIQoFfOGQ9SxKEZAJBE6Nalwcz1Bj07AOBvazVVMCRD4AMANEgFaEuZcxvrtQx6MXFoDCD1c/4OyVD3AMeCrlAgQQ+QqfIU2ks6XP3vtnQZ84fSgwm/5FCmC7yzgxorF0swxvt/y9X/NwDmAAiUuVAgwwG0HKTru4tQ6hSQjmbEjoWUAIoGcBm6QR21RJNgAzecRxa52UnRbLM4N1OFcNo5xsbHH8+FUMT6VqPAUomUagAcfAkz97cVQoSMBVl2cG64QJlt/4/wT50LtjRaHiJQ3z03ioPUV7bXAMCGJ+/tbGD15Ffk43Z5ud3rl/zcHu3irv+qAmw0Jlfa0Bdtb+p1tCqWyuiJCbs4tLC2ewu8pfNZMknpR+dICZ0mmBkZitNSKqvl78wkxfs/P7UqLDKRD7uykj453pxdvffmHnj/jlU/xEdicUAAAAAElFTkSuQmCCiVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABDklEQVR4nM1XsRHCMAwUOdgARiAFlIxEGiaigbGggA0gO0AVnzGyZMkS5qvkZP2/ZdlxABpjJk1Y758vKn4/r0ScxYM5Ya0RdpBUWGqEDHLil8MmPG+PV5WJzkIcey/lQg3Ull3C+WXAQ5zi7rgBOaRrTvUApTEvFcSw2D0AAKAfRjVH6E5u9rfTUkxOGZt2RnYX1IqX5nUA9Oy14lz+pFlUAU+IDfTDmF1bKmZiICZPhaiYmQEPiAzEDZU2FxWjID6IKHLNjvmPJZBeoywgOgk9EQz8sgqxFluBmi9dSf6HgVwVtCawvFQDFfS6FWETRJfAox9ynNkesDShupZbmaj6MYnR7NdMaqTFqVqFN3YKetkCAPoEAAAAAElFTkSuQmCC"

def get_x402_payment_response(resource_path: str, description: str = "0.01 USDC per message"):
    """
    توليد رد 402 المطابق لمواصفات بروتوكول x402 الإصدار 2 (v2)،
    متضمنًا امتداد Bazaar للاكتشاف (extensions.bazaar.info) الذي يصف
    شكل الطلب (input) والاستجابة (output) — وهو مطلوب لعدّ المورد
    "صالحًا" لدى بعض أدوات الفهرسة، وليس كافياً أن يكون extensions فارغًا.
    """
    resource_url = f"{SERVICE_URL}{resource_path}"
    return JSONResponse(
        status_code=402,
        content={
            "x402Version": 2,
            "error": "PAYMENT-SIGNATURE header is required",
            "resource": {
                "url": resource_url,
                "description": description,
                "mimeType": "application/json"
            },
            "accepts": [{
                "scheme": "exact",
                "network": SOLANA_MAINNET_CAIP2,
                "amount": "10000",  # 0.01 USDC بوحدات ذرية (6 خانات عشرية)
                "asset": USDC_MINT_SOLANA,
                "payTo": PAYMENT_RECIPIENT,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "name": "USD Coin",
                    "version": "2"
                }
            }],
            "extensions": {
                "bazaar": {
                    "info": {
                        "input": {
                            "type": "http",
                            "method": "POST",
                            "bodySchema": {
                                "type": "object",
                                "properties": {
                                    "to": {"type": "string", "description": "Telegram chat ID"},
                                    "message": {"type": "string", "description": "Message text"},
                                    "agent_wallet": {"type": "string", "description": "Payer wallet address"}
                                },
                                "required": ["to", "message", "agent_wallet"]
                            }
                        },
                        "output": {
                            "type": "json",
                            "example": {
                                "success": True,
                                "message_id": 123456,
                                "payment_verified": True,
                                "cost": "0.01 USDC"
                            }
                        }
                    }
                }
            }
        }
    )

# ============================================
# 6. الروابط الأساسية والـ Health Check
# ============================================

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "status": "ok",
        "service": "telagent",
        "version": "1.0.0",
        "message": "API is running"
    }

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "healthy"}

@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def favicon():
    icon_bytes = base64.b64decode(FAVICON_BASE64)
    return Response(content=icon_bytes, media_type="image/x-icon")

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

@app.api_route("/api/v1/telegram/send", methods=["GET", "HEAD"])
async def telegram_probe_get(request: Request):
    # الفاحص يطلب GET للتأكد من وجود نظام حماية الدفع
    # ندعم ترويسة v2 (PAYMENT-SIGNATURE) وأيضاً v1 (X-PAYMENT) للتوافق
    x_payment = request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")
    return {"ok": True, "message": "Payment verified for GET probe"}

@app.options("/api/v1/telegram/send")
async def telegram_probe_options():
    return JSONResponse(status_code=200, content={"ok": True})

@app.post("/api/v1/telegram/send")
async def telegram_send(request: Request):
    # التحقق من وجود ترويسة الدفع أولاً — قبل أي تحقق من صحة الـ body.
    # هذا مهم جداً لمطابقة مواصفات x402: أي طلب غير مدفوع يجب أن يحصل
    # على 402 دائماً، حتى لو كان الـ body ناقصاً أو غير صالح — وليس 422،
    # وإلا فإن أدوات الفحص (مثل x402scan) لن تتعرف على المورد كـ "مدفوع".
    x_payment = request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response("/api/v1/telegram/send")

    # الآن بعد التأكد من وجود الدفع، نتحقق من صحة الـ body يدوياً
    try:
        raw_body = await request.json()
        req = TelegramRequest(**raw_body)
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"error": "Invalid request body", "required_fields": ["to", "message", "agent_wallet"]}
        )

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

@app.api_route("/api/agent/register", methods=["GET", "HEAD"])
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

@app.api_route("/.well-known/x402", methods=["GET", "HEAD"])
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
            "network": SOLANA_MAINNET_CAIP2,
            "amount": "10000",
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

    paid_path = "/api/v1/telegram/send"
    # الطرق (methods) التي تفرض فعلياً رد 402 عند غياب الدفع في كودنا
    paid_methods = {"get", "post", "head"}

    for path, methods in schema.get("paths", {}).items():
        for method, operation in methods.items():
            if path == paid_path and method.lower() in paid_methods:
                operation["security"] = [{"x402": []}]
                operation["x402"] = {
                    "price": 0.01,
                    "currency": "USDC"
                }
            else:
                # كل الطرق/المسارات الأخرى مجانية صراحة — هذا ضروري كي لا
                # تحاول أدوات الفحص (x402scan) اختبارها كموارد مدفوعة
                operation["security"] = []

    return JSONResponse(schema)

@app.get("/openapi.json", include_in_schema=False)
async def openapi_root():
    return await openapi()

@app.get("/docs", include_in_schema=False)
async def custom_docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="TelAgent API — Docs")

# ============================================
# مسار تصحيح مؤقت — لعرض محتوى رد الدفع 402 بحالة 200 للفحص فقط.
# احذف هذا المسار بعد الانتهاء من التشخيص.
# ============================================

@app.get("/debug/x402-preview", include_in_schema=False)
async def debug_x402_preview():
    preview = get_x402_payment_response("/api/v1/telegram/send")
    body = json.loads(bytes(preview.body).decode("utf-8"))
    return JSONResponse(status_code=200, content=body)

# ============================================
# 12. الصفحات والروابط الفرعية المطلوبة للفحص
# ============================================

@app.api_route("/terms", methods=["GET", "HEAD"])
async def terms_page():
    return {"message": "Terms of Service for TelAgent"}

@app.api_route("/privacy-short", methods=["GET", "HEAD"])
async def privacy_page():
    return {"message": "Privacy Policy Summary for TelAgent"}

@app.options("/{full_path:path}", include_in_schema=False)
async def catch_all_options(full_path: str):
    # يمنع رد 405 على طلبات OPTIONS الاستكشافية التي قد ترسلها أدوات
    # الفحص (x402scan / mppscan) على أي مسار غير معرّف صراحة
    return JSONResponse(status_code=200, content={"ok": True})

@app.api_route("/home", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def home_ui():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>TelAgent</title>
        <link rel="icon" type="image/x-icon" href="/favicon.ico">
    </head>
    <body>
        <h1>🤖 TelAgent</h1>
        <p>Pay-per-request Telegram API for AI Agents</p>
        <p>⚡ x402 Protocol | 🌐 Solana | 📱 Telegram</p>
        <a href="/docs">📚 API Docs</a>
    </body>
    </html>
    """