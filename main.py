"""
TIK WAR MACHINE — Browser Agent + Full API Access
Claude in chat is the brain. This is the body.
"""
import os, json, asyncio
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from browser import BrowserAgent
from brain import WarMachineBrain
from apis import (
    ShopifyAPI, SupabaseAPI, N8nAPI, GSheetsAPI,
    ZeptoMailAPI, WarMachineOps
)

app = FastAPI(title="TIK War Machine", version="2.0.0")

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")

def verify_token(x_agent_token: str = Header(...)):
    if AGENT_TOKEN and x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

class RunRequest(BaseModel):
    scenario: str
    params: Optional[Dict[str, Any]] = {}
    viewport: Optional[str] = "desktop"

class AuditRequest(BaseModel):
    target: Optional[str] = "full"

class OrderCheckRequest(BaseModel):
    order_number: str

class QueryRequest(BaseModel):
    table: str
    filters: Optional[str] = ""
    select: Optional[str] = "*"
    limit: Optional[int] = 50

class SheetRequest(BaseModel):
    sheet_name: str
    range: Optional[str] = "A1:Z1000"


# ─── HEALTH ──────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "agent": "TIK War Machine v2.0", "capabilities": [
        "browser", "shopify", "supabase", "n8n", "gsheets", "zeptomail"
    ]}


# ─── SYSTEM HEALTH (all systems at once) ────────────────────────
@app.get("/systems")
async def systems_health(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await WarMachineOps.full_system_health())


# ─── BROWSER SCENARIOS ──────────────────────────────────────────
@app.post("/run")
async def run_scenario(req: RunRequest, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    agent = BrowserAgent(viewport=req.viewport)
    brain = WarMachineBrain()
    try:
        result = await agent.run_scenario(req.scenario, req.params)
        analysis = await brain.analyze(result)
        result["ai_analysis"] = analysis
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        await agent.close()


@app.post("/audit")
async def full_audit(req: AuditRequest, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    scenarios = {
        "full": ["homepage", "tour_search", "full_booking_mobile", "full_booking_desktop", "chatbot_basic", "finance_login"],
        "booking": ["homepage", "tour_search", "full_booking_mobile", "full_booking_desktop"],
        "chatbot": ["chatbot_basic", "chatbot_tour_query", "chatbot_refund_query"],
        "finance": ["finance_login", "finance_orders"],
        "quick": ["homepage", "tour_search"],
    }.get(req.target, ["homepage"])
    agent = BrowserAgent()
    brain = WarMachineBrain()
    all_results = []
    try:
        for scenario in scenarios:
            try:
                result = await agent.run_scenario(scenario, {})
                analysis = await brain.analyze(result)
                result["ai_analysis"] = analysis
                all_results.append(result)
            except Exception as e:
                all_results.append({"scenario": scenario, "status": "ERROR", "error": str(e), "steps": []})
        summary = await brain.summarize_audit(all_results)
        return JSONResponse(content={"audit_target": req.target, "results": all_results, "summary": summary})
    finally:
        await agent.close()


@app.post("/screenshot")
async def take_screenshot(body: Dict[str, Any], x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    agent = BrowserAgent(viewport=body.get("viewport", "desktop"))
    try:
        screenshot_b64 = await agent.screenshot_url(url)
        brain = WarMachineBrain()
        analysis = await brain.analyze_screenshot(screenshot_b64, url)
        return JSONResponse(content={"url": url, "screenshot": screenshot_b64, "analysis": analysis})
    finally:
        await agent.close()


# ─── SHOPIFY ─────────────────────────────────────────────────────
@app.get("/shopify/products")
async def shopify_products(x_agent_token: str = Header(...), limit: int = 50):
    verify_token(x_agent_token)
    return JSONResponse(content=await ShopifyAPI.get_products(limit))

@app.get("/shopify/products/{product_id}")
async def shopify_product(product_id: str, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await ShopifyAPI.get_product(product_id))

@app.get("/shopify/orders")
async def shopify_orders(x_agent_token: str = Header(...), limit: int = 20):
    verify_token(x_agent_token)
    return JSONResponse(content=await ShopifyAPI.get_orders(limit))

@app.get("/shopify/orders/{order_id}")
async def shopify_order(order_id: str, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await ShopifyAPI.get_order(order_id))

@app.get("/shopify/catalog")
async def shopify_catalog(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await WarMachineOps.get_product_catalog_summary())

@app.get("/shopify/collections")
async def shopify_collections(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await ShopifyAPI.get_collections())


# ─── SUPABASE ────────────────────────────────────────────────────
@app.post("/supabase/query")
async def supabase_query(req: QueryRequest, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await SupabaseAPI.query(req.table, req.filters, req.select, req.limit))

@app.get("/supabase/tables")
async def supabase_tables(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await SupabaseAPI.check_tables())

@app.get("/supabase/orders")
async def supabase_orders(x_agent_token: str = Header(...), limit: int = 20):
    verify_token(x_agent_token)
    return JSONResponse(content=await SupabaseAPI.get_bookings(limit))


# ─── N8N ─────────────────────────────────────────────────────────
@app.get("/n8n/workflows")
async def n8n_workflows(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await N8nAPI.get_workflows())

@app.get("/n8n/executions")
async def n8n_executions(x_agent_token: str = Header(...), limit: int = 10, workflow_id: str = "", status: str = ""):
    verify_token(x_agent_token)
    return JSONResponse(content=await N8nAPI.get_executions(workflow_id, limit, status))

@app.get("/n8n/executions/{execution_id}")
async def n8n_execution(execution_id: str, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await N8nAPI.get_execution(execution_id))


# ─── GOOGLE SHEETS ───────────────────────────────────────────────
@app.post("/gsheets/read")
async def gsheets_read(req: SheetRequest, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await GSheetsAPI.read_sheet(req.sheet_name, req.range))

@app.get("/gsheets/bookings")
async def gsheets_bookings(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await GSheetsAPI.get_bookings())

@app.get("/gsheets/tours")
async def gsheets_tours(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await GSheetsAPI.get_tours())

@app.get("/gsheets/providers")
async def gsheets_providers(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await GSheetsAPI.get_providers())


# ─── ZEPTOMAIL ───────────────────────────────────────────────────
@app.get("/zeptomail/status")
async def zeptomail_status(x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await ZeptoMailAPI.check_status())


# ─── E2E ORDER VERIFICATION ─────────────────────────────────────
@app.post("/verify-order")
async def verify_order(req: OrderCheckRequest, x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    return JSONResponse(content=await WarMachineOps.verify_order_e2e(req.order_number))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
