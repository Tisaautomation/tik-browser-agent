import os, json
import httpx
from typing import Dict, Any, List

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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

OUTPUT FORMAT: Always respond ONLY with a valid JSON object, no markdown fences:
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

Respond ONLY with a valid JSON object, no markdown fences:
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

    async def _call_gemini(self, prompt_text: str, system: str, image_b64: str = None) -> str:
        if not GEMINI_API_KEY:
            return json.dumps({"error": "GEMINI_API_KEY not set"})

        parts = []

        # Add system instruction as first text part
        parts.append({"text": f"{system}\n\n{prompt_text}"})

        # Add image if provided
        if image_b64:
            parts.insert(0, {
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": image_b64
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
                "responseMimeType": "text/plain"
            }
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload
            )
            data = resp.json()

            # Extract text from Gemini response
            try:
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    text_parts = content.get("parts", [])
                    if text_parts:
                        return text_parts[0].get("text", json.dumps({"error": "empty response"}))
                return json.dumps({"error": str(data)})
            except Exception as e:
                return json.dumps({"error": f"parse error: {str(e)}", "raw": str(data)[:500]})

    async def analyze(self, test_result: Dict[str, Any]) -> Dict:
        steps = test_result.get("steps", [])
        scenario = test_result.get("scenario", "unknown")
        status = test_result.get("status", "UNKNOWN")
        score = test_result.get("score", 0)

        # Build text summary
        steps_summary = []
        fail_screenshot = None
        for step in steps:
            step_info = {
                "step": step["name"],
                "status": step["status"],
                "error": step.get("error"),
                "notes": step.get("notes", [])
            }
            steps_summary.append(step_info)
            # Grab first failed screenshot for vision analysis
            if step.get("screenshot") and step["status"] == "FAIL" and not fail_screenshot:
                fail_screenshot = step["screenshot"]

        prompt = f"""Scenario: {scenario}
Overall status: {status}
Score: {score}/10
Steps: {json.dumps(steps_summary, indent=2)}

Analyze this test result as a real tourist customer. Be brutal and specific."""

        try:
            raw = await self._call_gemini(prompt, CUSTOMER_PERSONA, fail_screenshot)
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
                raw_clean = raw_clean.strip()
            return json.loads(raw_clean)
        except Exception as e:
            return {"error": str(e), "raw": raw if 'raw' in locals() else "no response"}

    async def analyze_screenshot(self, screenshot_b64: str, url: str) -> Dict:
        prompt = f"URL: {url}\n\nAnalyze this page as a tourist wanting to book a tour. Be specific about what you see."
        try:
            raw = await self._call_gemini(prompt, CUSTOMER_PERSONA, screenshot_b64)
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
                raw_clean = raw_clean.strip()
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

        prompt = f"Full audit results:\n{json.dumps(summary_data, indent=2)}\n\nGive me the final audit report."

        try:
            raw = await self._call_gemini(prompt, AUDIT_SUMMARY_PROMPT)
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
                raw_clean = raw_clean.strip()
            return json.loads(raw_clean)
        except Exception as e:
            return {"error": str(e)}
