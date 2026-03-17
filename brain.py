import json
from typing import Dict, Any, List


class WarMachineBrain:
    """
    No AI calls. The brain is Claude in the chat session.
    This class just structures raw data for Claude to analyze.
    """

    async def analyze(self, test_result: Dict[str, Any]) -> Dict:
        """Return structured raw results — Claude in chat analyzes."""
        return {
            "note": "Raw data — analyze in Claude chat session",
            "scenario": test_result.get("scenario"),
            "status": test_result.get("status"),
            "score": test_result.get("score"),
            "failed_steps": [
                {"step": s["name"], "error": s.get("error")}
                for s in test_result.get("steps", [])
                if s["status"] == "FAIL"
            ],
            "passed_steps": [
                s["name"]
                for s in test_result.get("steps", [])
                if s["status"] == "PASS"
            ]
        }

    async def analyze_screenshot(self, screenshot_b64: str, url: str) -> Dict:
        """Return screenshot data — Claude in chat analyzes."""
        return {
            "note": "Screenshot captured — analyze in Claude chat session",
            "url": url,
            "screenshot_size": len(screenshot_b64) if screenshot_b64 else 0
        }

    async def summarize_audit(self, all_results: List[Dict]) -> Dict:
        """Return all results — Claude in chat gives final report."""
        summary = []
        for r in all_results:
            summary.append({
                "scenario": r.get("scenario"),
                "status": r.get("status"),
                "score": r.get("score"),
                "failed_steps": [s["name"] for s in r.get("steps", []) if s["status"] == "FAIL"],
                "passed_steps": [s["name"] for s in r.get("steps", []) if s["status"] == "PASS"]
            })
        total_score = sum(r.get("score", 0) for r in all_results)
        max_score = len(all_results) * 10
        return {
            "note": "Full audit data — analyze in Claude chat session",
            "scenarios_tested": len(all_results),
            "total_score": f"{total_score}/{max_score}",
            "results": summary
        }
