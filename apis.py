"""
WAR MACHINE APIs — All TIK system integrations.
Claude in chat is the brain. This module is the nervous system.
"""
import os, json
from typing import Dict, Any, List, Optional
import httpx

# ─── ENV VARS ───────────────────────────────────────────────────
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "")
SHOPIFY_STOREFRONT_TOKEN = os.environ.get("SHOPIFY_STOREFRONT_TOKEN", "")
SHOPIFY_STORE_URL = os.environ.get("SHOPIFY_STORE_URL", "bymjqm-dy.myshopify.com")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
N8N_API_URL = os.environ.get("N8N_API_URL", "")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
GSHEETS_ID = os.environ.get("GSHEETS_ID", "")
ZEPTOMAIL_KEY = os.environ.get("ZEPTOMAIL_KEY", "")
FULL_ACCESS_WEBHOOK = os.environ.get("FULL_ACCESS_WEBHOOK", "")

SHOPIFY_ADMIN = f"https://{SHOPIFY_STORE_URL}/admin/api/2024-01"
SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN, "Content-Type": "application/json"}
SUPABASE_HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
N8N_HEADERS = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}


class ShopifyAPI:
    """Shopify Admin + Storefront API"""

    @staticmethod
    async def get_products(limit: int = 50) -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/products.json?limit={limit}", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def get_product(product_id: str) -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/products/{product_id}.json", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def get_orders(limit: int = 20, status: str = "any") -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/orders.json?limit={limit}&status={status}", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def get_order(order_id: str) -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/orders/{order_id}.json", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def search_orders(query: str) -> Dict:
        """Search orders by name, email, etc."""
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/orders.json?status=any&name={query}", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def count_products() -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/products/count.json", headers=SHOPIFY_HEADERS)
            return r.json()

    @staticmethod
    async def get_collections() -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SHOPIFY_ADMIN}/custom_collections.json", headers=SHOPIFY_HEADERS)
            return r.json()


class SupabaseAPI:
    """Supabase REST API"""

    @staticmethod
    async def query(table: str, filters: str = "", select: str = "*", limit: int = 50) -> list:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}&limit={limit}"
        if filters:
            url += f"&{filters}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=SUPABASE_HEADERS)
            return r.json()

    @staticmethod
    async def get_order(order_number: str) -> list:
        """Get order from shopify_orders by order number"""
        return await SupabaseAPI.query("shopify_orders", f"shopify_order_number=eq.{order_number}")

    @staticmethod
    async def get_bookings(limit: int = 20) -> list:
        return await SupabaseAPI.query("shopify_orders", "", "*", limit)

    @staticmethod
    async def get_config(key: str) -> Any:
        rows = await SupabaseAPI.query("system_config", f"key=eq.{key}", "key,value")
        return rows[0]["value"] if rows else None

    @staticmethod
    async def check_tables() -> Dict:
        """Check all critical tables exist and have data"""
        tables = ["shopify_orders", "customers", "payments", "system_config", "app_users"]
        results = {}
        for t in tables:
            try:
                rows = await SupabaseAPI.query(t, "", "count", 1)
                results[t] = {"status": "ok", "sample": len(rows)}
            except Exception as e:
                results[t] = {"status": "error", "error": str(e)}
        return results


class N8nAPI:
    """n8n workflow API"""

    @staticmethod
    async def get_workflows() -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{N8N_API_URL}/api/v1/workflows?limit=20", headers=N8N_HEADERS)
            return r.json()

    @staticmethod
    async def get_executions(workflow_id: str = "", limit: int = 10, status: str = "") -> Dict:
        url = f"{N8N_API_URL}/api/v1/executions?limit={limit}"
        if workflow_id:
            url += f"&workflowId={workflow_id}"
        if status:
            url += f"&status={status}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=N8N_HEADERS)
            return r.json()

    @staticmethod
    async def get_execution(execution_id: str) -> Dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{N8N_API_URL}/api/v1/executions/{execution_id}", headers=N8N_HEADERS)
            return r.json()

    @staticmethod
    async def check_health() -> Dict:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{N8N_API_URL}/healthz")
            return {"status": "ok" if r.status_code == 200 else "down", "code": r.status_code}


class GSheetsAPI:
    """Google Sheets via Full Access Controller webhook"""

    @staticmethod
    async def read_sheet(sheet_name: str, range_str: str = "A1:Z1000") -> Dict:
        payload = {
            "action": "sheets_read",
            "params": {
                "spreadsheetId": GSHEETS_ID,
                "sheetName": sheet_name,
                "range": range_str
            }
        }
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(FULL_ACCESS_WEBHOOK, json=payload)
            return r.json()

    @staticmethod
    async def get_bookings() -> Dict:
        return await GSheetsAPI.read_sheet("Bookings")

    @staticmethod
    async def get_tours() -> Dict:
        return await GSheetsAPI.read_sheet("Tours")

    @staticmethod
    async def get_providers() -> Dict:
        return await GSheetsAPI.read_sheet("Providers")


class ZeptoMailAPI:
    """ZeptoMail email verification"""

    @staticmethod
    async def check_status() -> Dict:
        """Check if ZeptoMail API is accessible"""
        async with httpx.AsyncClient(timeout=15) as c:
            try:
                r = await c.get(
                    "https://api.zeptomail.com/v1.1/",
                    headers={"Authorization": ZEPTOMAIL_KEY, "Accept": "application/json"}
                )
                return {"status": "accessible", "code": r.status_code}
            except Exception as e:
                return {"status": "error", "error": str(e)}


class WarMachineOps:
    """High-level operations that combine multiple APIs"""

    @staticmethod
    async def full_system_health() -> Dict:
        """Check all systems at once"""
        results = {}

        # n8n
        try:
            results["n8n"] = await N8nAPI.check_health()
        except Exception as e:
            results["n8n"] = {"status": "error", "error": str(e)}

        # Supabase
        try:
            tables = await SupabaseAPI.check_tables()
            results["supabase"] = {"status": "ok", "tables": tables}
        except Exception as e:
            results["supabase"] = {"status": "error", "error": str(e)}

        # Shopify
        try:
            count = await ShopifyAPI.count_products()
            results["shopify"] = {"status": "ok", "product_count": count.get("count", 0)}
        except Exception as e:
            results["shopify"] = {"status": "error", "error": str(e)}

        # ZeptoMail
        try:
            results["zeptomail"] = await ZeptoMailAPI.check_status()
        except Exception as e:
            results["zeptomail"] = {"status": "error", "error": str(e)}

        return results

    @staticmethod
    async def verify_order_e2e(order_number: str) -> Dict:
        """Verify an order exists across all systems"""
        results = {}

        # 1. Shopify
        try:
            orders = await ShopifyAPI.search_orders(order_number)
            shopify_orders = orders.get("orders", [])
            results["shopify"] = {
                "found": len(shopify_orders) > 0,
                "count": len(shopify_orders),
                "details": {
                    "name": shopify_orders[0]["name"] if shopify_orders else None,
                    "email": shopify_orders[0].get("email") if shopify_orders else None,
                    "total": shopify_orders[0].get("total_price") if shopify_orders else None,
                    "status": shopify_orders[0].get("financial_status") if shopify_orders else None,
                } if shopify_orders else {}
            }
        except Exception as e:
            results["shopify"] = {"found": False, "error": str(e)}

        # 2. Supabase
        try:
            clean_num = order_number.replace("#TIK", "").replace("#", "")
            sb_orders = await SupabaseAPI.get_order(clean_num)
            results["supabase"] = {
                "found": len(sb_orders) > 0,
                "count": len(sb_orders),
                "details": sb_orders[0] if sb_orders else {}
            }
        except Exception as e:
            results["supabase"] = {"found": False, "error": str(e)}

        # 3. n8n executions (recent)
        try:
            execs = await N8nAPI.get_executions(limit=20)
            related = []
            for ex in execs.get("data", []):
                if order_number in str(ex.get("data", "")):
                    related.append({"id": ex["id"], "status": ex.get("status"), "finished": ex.get("stoppedAt")})
            results["n8n_executions"] = {"found": len(related) > 0, "count": len(related), "executions": related[:5]}
        except Exception as e:
            results["n8n_executions"] = {"found": False, "error": str(e)}

        return results

    @staticmethod
    async def get_product_catalog_summary() -> Dict:
        """Get a summary of all products for verification"""
        try:
            products = await ShopifyAPI.get_products(limit=250)
            prods = products.get("products", [])
            summary = []
            for p in prods:
                summary.append({
                    "id": p["id"],
                    "title": p["title"],
                    "handle": p["handle"],
                    "status": p["status"],
                    "variants": len(p.get("variants", [])),
                    "images": len(p.get("images", [])),
                    "has_price": any(float(v.get("price", 0)) > 0 for v in p.get("variants", [])),
                })
            return {
                "total": len(prods),
                "active": sum(1 for p in summary if p["status"] == "active"),
                "missing_images": [p["title"] for p in summary if p["images"] == 0],
                "missing_price": [p["title"] for p in summary if not p["has_price"]],
                "products": summary
            }
        except Exception as e:
            return {"error": str(e)}
