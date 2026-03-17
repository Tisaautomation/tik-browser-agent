import os, json, asyncio
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from browser import BrowserAgent
from brain import WarMachineBrain

app = FastAPI(title="TIK Browser Agent", version="1.0.0")

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

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "TIK War Machine Browser Agent v1.0"}

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
                await asyncio.sleep(1)
            except Exception as e:
                all_results.append({"scenario": scenario, "status": "ERROR", "error": str(e)})
    finally:
        await agent.close()
    summary = await brain.summarize_audit(all_results)
    return JSONResponse(content={"audit_target": req.target, "results": all_results, "summary": summary})

@app.post("/screenshot")
async def take_screenshot(body: Dict[str, Any], x_agent_token: str = Header(...)):
    verify_token(x_agent_token)
    url = body.get("url")
    viewport = body.get("viewport", "desktop")
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    agent = BrowserAgent(viewport=viewport)
    try:
        screenshot_b64 = await agent.screenshot_url(url)
        brain = WarMachineBrain()
        analysis = await brain.analyze_screenshot(screenshot_b64, url)
        return JSONResponse(content={"url": url, "screenshot": screenshot_b64, "analysis": analysis})
    finally:
        await agent.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
