import os, json, base64
import httpx
from typing import Dict, Any, List

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"

CUSTOMER_PERSONA = """You are a WAR MACHINE tester for Tour In Koh Samui (TIK), a tour booking website in Koh Samui, Thailand.

Your job is to think EXACTLY like a real tourist customer — confused, impatient, on a phone, maybe not fluent in English. You are brutal and honest.

CUSTOMER PROFILE:
- Tourist arriving in Koh Samui in 2-3 days, wants to book a tour
- Using a mobile phone, maybe slow internet
- Has credit card, willing to pay if the site is trustworthy
- Will immediately leave if anything is confusing, broken, or sketchy
- Does not read long paragraphs — scans for price, date, photos, trust signals

WHAT YOU CHECK:
1. Can a real tourist find what they want in under 10 seconds?
2. Is the price clear BEFORE checkout?
3. Are the tour photos good enough to trust?
4. Is the booking flow obvious (no hidden steps)?
5. Does it feel safe to enter credit card details?
6. Are confirmation/cancellation policies visible?
7. Does it work perfectly on mobile (360px-390px)?
8. Is any copy confusing, broken, or missing?

OUTPUT FORMAT: Always respond with a JSON object:
{
  "customer_verdict": "PASS | PARTIAL | FAIL",
  "first_impression": "What a real tourist would feel in the first 3 seconds",
  "issues_found": ["issue 1", "issue 2"],
  "what_works": ["thing 1", "thing 2"],
  "blocking_issues": ["issues that would stop a booking"],
  "score": 0-10,
  "recommendation": "One sentence: fix X first"
}
"""

AUDIT_SUMMARY_PROMPT = """You are the War Machine brain for Tour In Koh Samui. 
You just ran a full site audit with multiple test scenarios.
Analyze ALL results together and give a FINAL REPORT.

FORMAT (JSON):
{
  "overall_status": "READY | NEEDS_WORK | CRITICAL",
  "overall_score": 0-10,
  "critical_blockers": ["issues that prevent any booking"],
  "high_priority_fixes": ["fix before launch"],
  "what_works_well": ["strengths"],
  "launch_recommendation": "LAUNCH | FIX_FIRST | DO_NOT_LAUNCH",
  "summary": "2-3 sentence executive summary for the owner"
}
"""

class WarMachineBrain:

    async def _call_claude(self, messages: list, system: str) -> str:
        if not ANTHROPIC_API_KEY:
            return json.dumps({"error": "ANTHROPIC_API_KEY not set"})
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": messages,
                }
            )
            data = resp.json()
            return data["content"][0]["text"] if "content" in data else json.dumps({"error": str(data)})

    async def analyze(self, test_result: Dict[str, Any]) -> Dict:
        steps = test_result.get("steps", [])
        scenario = test_result.get("scenario", "unknown")
        status = test_result.get("status", "UNKNOWN")
        score = test_result.get("score", 0)

        content = []

        # Build message with screenshots
        steps_summary = []
        for step in steps:
            step_info = {
                "step": step["name"],
                "status": step["status"],
                "error": step.get("error"),
                "notes": step.get("notes", [])
            }
            steps_summary.append(step_info)

            # Add last screenshot as image if available
            if step.get("screenshot") and step["status"] == "FAIL":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": step["screenshot"]
                    }
                })
                content.append({
                    "type": "text",
                    "text": f"Screenshot from FAILED step: {step['name']}"
                })

        content.append({
            "type": "text",
            "text": f"""Scenario: {scenario}
Overall status: {status}
Score: {score}/10
Steps: {json.dumps(steps_summary, indent=2)}

Analyze this test result as a real tourist customer. Be brutal and specific."""
        })

        try:
            raw = await self._call_claude(
                [{"role": "user", "content": content}],
                system=CUSTOMER_PERSONA
            )
            # Try to parse as JSON
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
            return json.loads(raw_clean)
        except Exception as e:
            return {"error": str(e), "raw": raw if 'raw' in locals() else "no response"}

    async def analyze_screenshot(self, screenshot_b64: str, url: str) -> Dict:
        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": screenshot_b64
                    }
                },
                {
                    "type": "text",
                    "text": f"URL: {url}\n\nAnalyze this page as a tourist wanting to book a tour. Be specific about what you see."
                }
            ]
        }]
        try:
            raw = await self._call_claude(messages, system=CUSTOMER_PERSONA)
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
            return json.loads(raw_clean)
        except Exception as e:
            return {"error": str(e)}

    async def summarize_audit(self, all_results: List[Dict]) -> Dict:
        summary_data = []
        for r in all_results:
            summary_data.append({
                "scenario": r.get("scenario"),
                "status": r.get("status"),
                "score": r.get("score"),
                "ai_analysis": r.get("ai_analysis", {}),
                "failed_steps": [s["name"] for s in r.get("steps", []) if s["status"] == "FAIL"]
            })

        messages = [{
            "role": "user",
            "content": f"Full audit results:\n{json.dumps(summary_data, indent=2)}\n\nGive me the final audit report."
        }]

        try:
            raw = await self._call_claude(messages, system=AUDIT_SUMMARY_PROMPT)
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
            return json.loads(raw_clean)
        except Exception as e:
            return {"error": str(e)}
