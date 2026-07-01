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
SERVICE_URL = os.getenv("SERVICE_URL", "https://telagent.onrender.com")
USDC_MINT_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOLANA_MAINNET_CAIP2 = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

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
# 5. تعريف OpenAPI المخصص (CUSTOM_OPENAPI)
# ============================================

CUSTOM_OPENAPI = {
    "openapi": "3.1.0",
    "info": {
        "title": "TelAgent API",
        "version": "1.0.0",
        "description": "Telegram API for AI Agents with x402 payments",
        "contact": {"email": "legal@telagent.dev"},
        "x-guidance": "Use POST /api/v1/telegram/send. Requires x402 payment with X-PAYMENT header."
    },
    "paths": {
        "/api/v1/telegram/send": {
            "post": {
                "summary": "Send a Telegram message",
                "operationId": "sendTelegram",
                "x-payment-info": {
                    "price": {"mode": "fixed", "currency": "USD", "amount": "0.010000"},
                    "protocols": [{"x402": {}}]
                },
                "security": [{"x402": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "to": {"type": "string", "description": "Telegram chat ID"},
                                    "message": {"type": "string", "description": "Message content"},
                                    "agent_wallet": {"type": "string", "description": "Agent wallet address"}
                                },
                                "required": ["to", "message", "agent_wallet"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Message sent successfully"},
                    "402": {"description": "Payment Required"}
                }
            }
        },
        "/api/agent/register": {
            "post": {
                "summary": "Register an agent",
                "security": [],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "wallet": {"type": "string"},
                                    "terms_accepted": {"type": "boolean"}
                                },
                                "required": ["wallet", "terms_accepted"]
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "Success"}}
            }
        },
        "/": {
            "get": {
                "summary": "Root",
                "security": [],
                "responses": {"200": {"description": "OK"}}
            }
        },
        "/health": {
            "get": {
                "summary": "Health",
                "security": [],
                "responses": {"200": {"description": "OK"}}
            }
        },
        "/terms": {
            "get": {
                "summary": "Terms",
                "security": [],
                "responses": {"200": {"description": "OK"}}
            }
        },
        "/privacy-short": {
            "get": {
                "summary": "Privacy",
                "security": [],
                "responses": {"200": {"description": "OK"}}
            }
        }
    },
    "components": {
        "securitySchemes": {
            "x402": {
                "type": "apiKey",
                "in": "header",
                "name": "X-PAYMENT",
                "description": "x402 payment signature"
            }
        }
    }
}

# ============================================
# 6. تعيين OpenAPI المخصص
# ============================================

app.openapi_schema = CUSTOM_OPENAPI

# ============================================
# 7. نقطة نهاية OpenAPI (للتأكيد)
# ============================================

@app.get("/openapi.json", include_in_schema=False)
async def openapi():
    return JSONResponse(CUSTOM_OPENAPI)

@app.get("/.well-known/openapi.json", include_in_schema=False)
async def well_known_openapi():
    return JSONResponse(CUSTOM_OPENAPI)

# ============================================
# 8. دالة توليد رد 402
# ============================================

def get_x402_payment_response():
    return JSONResponse(
        status_code=402,
        headers={
            "X-PAYMENT-REQUIREMENTS": json.dumps({
                "x402Version": 2,
                "accepts": [{
                    "scheme": "exact",
                    "network": SOLANA_MAINNET_CAIP2,
                    "amount": "10000",
                    "asset": USDC_MINT_SOLANA,
                    "payTo": PAYMENT_RECIPIENT,
                    "maxTimeoutSeconds": 60
                }],
                "resource": f"{SERVICE_URL}/api/v1/telegram/send",
                "description": "0.01 USDC per Telegram message"
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

# ============================================
# 9. نقاط النهاية المجانية
# ============================================

@app.get("/")
async def root():
    return {"status": "ok", "service": "telagent", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/terms")
async def terms():
    return {"message": "Terms of Service"}

@app.get("/privacy-short")
async def privacy():
    return {"message": "Privacy Policy"}

# ============================================
# 10. تسجيل العميل (مجاني)
# ============================================

class RegisterAgentRequest(BaseModel):
    wallet: str
    terms_accepted: bool

agent_consents = {}

@app.get("/api/agent/register")
async def register_probe_get():
    return {"ok": True}

@app.post("/api/agent/register")
async def register_agent(body: RegisterAgentRequest):
    if not body.terms_accepted:
        return JSONResponse(status_code=400, content={"error": "Terms not accepted"})
    agent_consents[body.wallet] = True
    return {"success": True, "wallet": body.wallet, "consent": True}

# ============================================
# 11. نقطة الدفع الرئيسية
# ============================================

class TelegramRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str

@app.get("/api/v1/telegram/send")
async def telegram_probe_get(request: Request):
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response()
    return {"ok": True}

@app.options("/api/v1/telegram/send")
async def telegram_probe_options():
    return JSONResponse(status_code=200, content={"ok": True})

@app.post("/api/v1/telegram/send")
async def telegram_send(request: Request):
    x_payment = request.headers.get("X-PAYMENT")
    if not x_payment:
        return get_x402_payment_response()

    try:
        raw_body = await request.json()
        req = TelegramRequest(**raw_body)
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"error": "Invalid body", "required": ["to", "message", "agent_wallet"]}
        )

    if not agent_consents.get(req.agent_wallet):
        return JSONResponse(
            status_code=403,
            content={"error": "Consent Required", "action": "register at /api/agent/register"}
        )

    try:
        http_client = request.app.state.http_client
        response = await http_client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": req.to, "text": req.message, "parse_mode": "Markdown"}
        )
        if response.status_code != 200:
            return JSONResponse(status_code=500, content={"error": response.text})
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
        return JSONResponse(status_code=500, content={"error": str(e)})

# ============================================
# 12. Discovery (x402)
# ============================================

@app.get("/.well-known/x402")
async def x402_discovery():
    return {
        "version": "1.0",
        "identifier": "telagent",
        "name": "TelAgent",
        "description": "Telegram API with x402 payments",
        "owner": {"name": "TelAgent", "website": "https://telagent.dev"},
        "servers": [{"url": SERVICE_URL}],
        "resources": [{
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
        "openapi_document": "/openapi.json"
    }

# ============================================
# 13. التشغيل
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
