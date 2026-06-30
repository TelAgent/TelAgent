from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TelAgent API", version="1.0.0")


# =====================================================
# CORS (fixes OPTIONS 405 everywhere)
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
# ROOT (fixes 404 / probe failure)
# =====================================================
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "telagent",
        "message": "API running"
    }


# =====================================================
# HEALTH CHECK (optional but useful)
# =====================================================
@app.get("/health")
def health():
    return {"status": "healthy"}


# =====================================================
# REQUEST MODEL (POST ONLY)
# =====================================================
class TelegramRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str


# =====================================================
# TELEGRAM ENDPOINT (PROBE SAFE + POST EXECUTION)
# =====================================================

@app.get("/api/v1/telegram/send")
def telegram_probe_get():
    return {"ok": True, "mode": "get_probe"}


@app.options("/api/v1/telegram/send")
def telegram_probe_options():
    return {"ok": True, "mode": "options_probe"}


@app.post("/api/v1/telegram/send")
def telegram_send(req: TelegramRequest):
    return {
        "ok": True,
        "to": req.to,
        "message": req.message,
        "x402": {
            "required": True,
            "price": 0.01,
            "currency": "USD"
        }
    }


# =====================================================
# AGENT REGISTER ENDPOINT
# =====================================================

@app.get("/api/agent/register")
def register_probe_get():
    return {"ok": True}


@app.options("/api/agent/register")
def register_probe_options():
    return {"ok": True}


@app.post("/api/agent/register")
def register_agent():
    return {"status": "registered"}


# =====================================================
# x402 DISCOVERY (REQUIRED BY agentcash)
# =====================================================
@app.get("/.well-known/x402")
def x402():
    return {
        "version": "1.0",
        "resources": [
            "/api/v1/telegram/send"
        ]
    }


# =====================================================
# OPENAPI (agentcash REQUIRED + x402 MARKING)
# =====================================================
@app.get("/.well-known/openapi.json", include_in_schema=False)
def openapi():
    schema = app.openapi()

    schema.setdefault("components", {})
    schema["components"].setdefault("securitySchemes", {})

    schema["components"]["securitySchemes"]["x402"] = {
        "type": "http",
        "scheme": "x402"
    }

    # Mark paid endpoint properly
    path = "/api/v1/telegram/send"
    if path in schema["paths"]:
        for method in schema["paths"][path]:
            schema["paths"][path][method]["security"] = [{"x402": []}]
            schema["paths"][path][method]["x402"] = {
                "price": 0.01,
                "currency": "USD"
            }

    return schema


# =====================================================
# OPTIONAL: standard openapi route (fallback)
# =====================================================
@app.get("/openapi.json", include_in_schema=False)
def openapi_fallback():
    return app.openapi()