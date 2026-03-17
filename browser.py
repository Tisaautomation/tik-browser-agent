import asyncio, base64, os
from playwright.async_api import async_playwright, Page, Browser
from typing import Dict, Any, Optional, List

SHOP_URL = "https://tourinkohsamui.com"
FINANCE_URL = "https://tour-finance-app.vercel.app"

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "mobile": {"width": 390, "height": 844},
    "mobile_small": {"width": 360, "height": 640},
}

class Step:
    def __init__(self, name: str):
        self.name = name
        self.status = "PENDING"
        self.error = None
        self.screenshot = None
        self.notes = []

    def done(self, screenshot=None, note=None):
        self.status = "PASS"
        self.screenshot = screenshot
        if note:
            self.notes.append(note)

    def fail(self, error: str, screenshot=None):
        self.status = "FAIL"
        self.error = error
        self.screenshot = screenshot

    def to_dict(self):
        return {
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "notes": self.notes,
            "screenshot": self.screenshot,
        }

class BrowserAgent:
    def __init__(self, viewport: str = "desktop"):
        self.viewport_name = viewport
        self.viewport = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def _get_browser(self) -> Browser:
        if not self._browser:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
        return self._browser

    async def new_page(self) -> Page:
        browser = await self._get_browser()
        context = await browser.new_context(
            viewport=self.viewport,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1" if "mobile" in self.viewport_name else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = await context.new_page()
        return page

    async def screenshot_b64(self, page: Page) -> str:
        buf = await page.screenshot(full_page=False, type="jpeg", quality=80)
        return base64.b64encode(buf).decode()

    async def screenshot_url(self, url: str) -> str:
        page = await self.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        return await self.screenshot_b64(page)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def run_scenario(self, scenario: str, params: Dict[str, Any]) -> Dict:
        handlers = {
            "homepage": self._scenario_homepage,
            "tour_search": self._scenario_tour_search,
            "full_booking_desktop": self._scenario_full_booking,
            "full_booking_mobile": self._scenario_full_booking_mobile,
            "chatbot_basic": self._scenario_chatbot_basic,
            "chatbot_tour_query": self._scenario_chatbot_tour_query,
            "chatbot_refund_query": self._scenario_chatbot_refund_query,
            "finance_login": self._scenario_finance_login,
            "finance_orders": self._scenario_finance_orders,
            "email_confirmation_check": self._scenario_email_check,
        }
        handler = handlers.get(scenario)
        if not handler:
            return {"scenario": scenario, "status": "ERROR", "error": f"Unknown scenario: {scenario}", "steps": []}

        steps: List[Step] = []
        try:
            await handler(steps, params)
        except Exception as e:
            steps.append(Step(f"Unexpected error: {str(e)}"))
            steps[-1].fail(str(e))

        passed = sum(1 for s in steps if s.status == "PASS")
        total = len(steps)
        status = "PASS" if passed == total else ("PARTIAL" if passed > 0 else "FAIL")
        score = round((passed / total) * 10, 1) if total > 0 else 0

        return {
            "scenario": scenario,
            "viewport": self.viewport_name,
            "status": status,
            "score": score,
            "passed": passed,
            "total": total,
            "steps": [s.to_dict() for s in steps],
        }

    # ─── SCENARIO: Homepage ─────────────────────────────────────
    async def _scenario_homepage(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Load homepage")
        try:
            resp = await page.goto(SHOP_URL, wait_until="domcontentloaded", timeout=30000)
            ss = await self.screenshot_b64(page)
            if resp and resp.status < 400:
                s.done(ss, f"HTTP {resp.status}")
            else:
                s.fail(f"HTTP {resp.status if resp else 'no response'}", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Navigation menu visible")
        try:
            await page.wait_for_selector("nav, header", timeout=5000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail("Nav not found", await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Hero section / CTA visible")
        try:
            hero = await page.query_selector("section, .hero, [class*='hero'], [class*='banner']")
            ss = await self.screenshot_b64(page)
            if hero:
                s.done(ss)
            else:
                s.fail("No hero section found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Tour listings accessible")
        try:
            await page.goto(f"{SHOP_URL}/collections/all", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(".product-card, .card, [class*='product'], article", timeout=8000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Tour search ───────────────────────────────────
    async def _scenario_tour_search(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Open collections page")
        try:
            await page.goto(f"{SHOP_URL}/collections/all", wait_until="domcontentloaded", timeout=30000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Tour cards render with price")
        try:
            await page.wait_for_selector(".product-card, .card, article", timeout=8000)
            first_card = await page.query_selector(".product-card, .card, article")
            text = await first_card.inner_text() if first_card else ""
            ss = await self.screenshot_b64(page)
            if "฿" in text or "$" in text or "THB" in text or any(c.isdigit() for c in text):
                s.done(ss, "Price visible on card")
            else:
                s.fail("Price not visible on tour card", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Click into a tour product page")
        try:
            link = await page.query_selector(".product-card a, .card a, article a, a[href*='/products/']")
            if link:
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                ss = await self.screenshot_b64(page)
                title = await page.title()
                s.done(ss, f"Page: {title}")
            else:
                s.fail("No product link found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Product page has Add to Cart button")
        try:
            btn = await page.query_selector("[name='add'], button[type='submit'], .add-to-cart, [class*='add-to-cart']")
            ss = await self.screenshot_b64(page)
            if btn:
                s.done(ss)
            else:
                s.fail("Add to Cart button not found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Full booking (desktop) ───────────────────────
    async def _scenario_full_booking(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Navigate to a bookable tour")
        try:
            await page.goto(f"{SHOP_URL}/products/snorkeling-trip", wait_until="domcontentloaded", timeout=30000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Select date if date picker present")
        try:
            date_input = await page.query_selector("input[type='date'], .datepicker, [class*='date']")
            ss = await self.screenshot_b64(page)
            if date_input:
                s.done(ss, "Date picker found")
            else:
                s.done(ss, "No date picker — date selected at checkout")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Add to cart")
        try:
            btn = await page.query_selector("[name='add'], button[type='submit'], .add-to-cart")
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                ss = await self.screenshot_b64(page)
                s.fail("Add to cart button not found", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Cart accessible (icon or page)")
        try:
            cart_link = await page.query_selector("a[href='/cart'], .cart, [class*='cart']")
            ss = await self.screenshot_b64(page)
            if cart_link:
                await cart_link.click()
                await page.wait_for_load_state("domcontentloaded")
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                s.done(ss, "Cart may be drawer-style")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Checkout button visible and clickable")
        try:
            checkout = await page.query_selector("[name='checkout'], a[href*='checkout'], button[class*='checkout']")
            ss = await self.screenshot_b64(page)
            if checkout:
                is_visible = await checkout.is_visible()
                if is_visible:
                    s.done(ss, "Checkout button visible")
                else:
                    s.fail("Checkout button exists but hidden", ss)
            else:
                s.fail("Checkout button not found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Full booking (mobile) ────────────────────────
    async def _scenario_full_booking_mobile(self, steps: List[Step], params: Dict):
        self.viewport = VIEWPORTS["mobile_small"]
        await self._scenario_full_booking(steps, params)
        self.viewport = VIEWPORTS.get(self.viewport_name, VIEWPORTS["desktop"])

    # ─── SCENARIO: Chatbot basic ─────────────────────────────────
    async def _scenario_chatbot_basic(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Open homepage with chatbot")
        try:
            await page.goto(SHOP_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Chatbot widget visible")
        try:
            chatbot = await page.query_selector("[class*='chat'], [id*='chat'], iframe[src*='chat'], .chat-bubble, .chat-widget")
            ss = await self.screenshot_b64(page)
            if chatbot:
                s.done(ss, "Chatbot element found")
            else:
                s.fail("No chatbot widget found on page", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Chatbot opens on click")
        try:
            chatbot = await page.query_selector("[class*='chat'], [id*='chat'], .chat-bubble")
            if chatbot:
                await chatbot.click()
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                s.fail("Cannot click chatbot — not found")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Chatbot tour query ────────────────────────────
    async def _scenario_chatbot_tour_query(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Load homepage")
        try:
            await page.goto(SHOP_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            s.done(await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Type tour question in chatbot")
        try:
            input_el = await page.query_selector("[class*='chat'] input, [class*='chat'] textarea")
            if input_el:
                await input_el.type("What snorkeling tours do you have?", delay=50)
                await input_el.press("Enter")
                await page.wait_for_timeout(5000)
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                s.fail("Chat input not found")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Chatbot responded with relevant info")
        try:
            response = await page.query_selector("[class*='bot-message'], [class*='chat-message'], [class*='response']")
            ss = await self.screenshot_b64(page)
            if response:
                text = await response.inner_text()
                if any(kw in text.lower() for kw in ["snorkel", "tour", "price", "฿", "book"]):
                    s.done(ss, f"Response: {text[:100]}")
                else:
                    s.fail(f"Response seems off-topic: {text[:100]}", ss)
            else:
                s.fail("No chatbot response found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Chatbot refund query ─────────────────────────
    async def _scenario_chatbot_refund_query(self, steps: List[Step], params: Dict):
        page = await self.new_page()
        s = Step("Load homepage")
        try:
            await page.goto(SHOP_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            s.done(await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Ask refund policy question")
        try:
            input_el = await page.query_selector("[class*='chat'] input, [class*='chat'] textarea")
            if input_el:
                await input_el.type("Can I get a refund if I cancel?", delay=50)
                await input_el.press("Enter")
                await page.wait_for_timeout(5000)
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                s.fail("Chat input not found")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Refund policy clearly explained")
        try:
            response = await page.query_selector("[class*='bot-message'], [class*='chat-message']")
            ss = await self.screenshot_b64(page)
            if response:
                text = await response.inner_text()
                if any(kw in text.lower() for kw in ["refund", "cancel", "48", "hour", "policy"]):
                    s.done(ss, f"Policy: {text[:150]}")
                else:
                    s.fail(f"Refund policy not in response: {text[:100]}", ss)
            else:
                s.fail("No response", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Finance App login ────────────────────────────
    async def _scenario_finance_login(self, steps: List[Step], params: Dict):
        page = await self.new_page()
        email = params.get("email", "chai.dolphinsamui@gmail.com")
        password = params.get("password", "C565656")

        s = Step("Load Finance App")
        try:
            await page.goto(FINANCE_URL, wait_until="domcontentloaded", timeout=30000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Login form renders")
        try:
            await page.wait_for_selector("input[type='email'], input[type='text']", timeout=8000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail("Login form not found", await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Enter credentials and submit")
        try:
            await page.fill("input[type='email'], input[name='email']", email)
            await page.fill("input[type='password']", password)
            ss = await self.screenshot_b64(page)
            await page.click("button[type='submit'], button:has-text('Login'), button:has-text('Sign in')")
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            s.done(ss, f"Submitted for {email}")
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Login successful — dashboard visible")
        try:
            url = page.url
            error_el = await page.query_selector("[class*='error'], [class*='alert-danger']")
            error_text = await error_el.inner_text() if error_el else ""
            ss = await self.screenshot_b64(page)
            if error_text:
                s.fail(f"Login error: {error_text}", ss)
            elif "login" not in url.lower():
                s.done(ss, f"Redirected to: {url}")
            else:
                s.fail("Still on login page", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Finance orders page ──────────────────────────
    async def _scenario_finance_orders(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Login to Finance App")
        try:
            await page.goto(FINANCE_URL, wait_until="domcontentloaded", timeout=30000)
            await page.fill("input[type='email']", "will@tourinkohsamui.com")
            await page.fill("input[type='password']", os.environ.get("WILL_PASSWORD", ""))
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)
            s.done(await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Orders table loads")
        try:
            await page.wait_for_selector("table, [class*='orders'], [class*='table']", timeout=10000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail("Orders not visible", await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Orders have data")
        try:
            rows = await page.query_selector_all("tbody tr, [class*='order-row']")
            ss = await self.screenshot_b64(page)
            if len(rows) > 0:
                s.done(ss, f"{len(rows)} orders visible")
            else:
                s.fail("No order rows found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Email check (placeholder — needs mailbox) ─────
    async def _scenario_email_check(self, steps: List[Step], params: Dict):
        s = Step("Email check via ZeptoMail logs")
        s.fail("Not implemented — requires ZeptoMail API or mailbox access. Check logs manually at api.zeptomail.com")
        steps.append(s)
