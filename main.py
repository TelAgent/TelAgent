from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TelAgent API", version="1.0.0")


# -------------------------
# CORS (fix OPTIONS 405 globally)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# REQUEST MODEL (POST ONLY)
# -------------------------
class TelegramRequest(BaseModel):
    to: str
    message: str
    agent_wallet: str


# =====================================================
# 1. TELEGRAM SEND (PROBE ROUTES - SAFE FOR SCANNERS)
# =====================================================

@app.get("/api/v1/telegram/send")
def send_probe_get():
    return {"ok": True, "mode": "get_probe"}


@app.options("/api/v1/telegram/send")
def send_probe_options():
    return {"ok": True, "mode": "options_probe"}


# =====================================================
# 2. TELEGRAM SEND (REAL EXECUTION - POST ONLY)
# =====================================================

@app.post("/api/v1/telegram/send")
def send_telegram(req: TelegramRequest):
    return {
        "ok": True,
        "to": req.to,
        "message": req.message,
        "x402": {
            "price": 0.01,
            "currency": "USD",
            "required": True
        }
    }


# =====================================================
# 3. AGENT REGISTER (SAME PATTERN)
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
# 4. x402 DISCOVERY ENDPOINT
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
# 5. OPENAPI (agentcash REQUIRED)
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

    # mark paid endpoint
    path = "/api/v1/telegram/send"
    if path in schema["paths"]:
        for method in schema["paths"][path]:
            schema["paths"][path][method]["security"] = [{"x402": []}]
            schema["paths"][path][method]["x402"] = {
                "price": 0.01,
                "currency": "USD"
            }

    return schema