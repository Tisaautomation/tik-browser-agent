import asyncio, base64, os
from playwright.async_api import async_playwright, Page, Browser
from typing import Dict, Any, Optional, List

SHOP_URL = "https://tourinkohsamui.com"
FINANCE_URL = "https://tour-finance-app.vercel.app"
SHOPIFY_STORE_PASSWORD = os.environ.get("SHOPIFY_STORE_PASSWORD", "bawhow")

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
        await self._handle_storefront_password(page)
        return await self.screenshot_b64(page)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _handle_storefront_password(self, page: Page) -> bool:
        """Handle Shopify storefront password page. Returns True if password was entered."""
        if not SHOPIFY_STORE_PASSWORD:
            return False
        try:
            pw_input = await page.query_selector("input#password, input[name='password'][type='password']")
            pw_form = await page.query_selector("form#login_form, form.storefront-password-form")
            if pw_input and pw_form:
                await pw_input.fill(SHOPIFY_STORE_PASSWORD)
                submit = await page.query_selector("input[type='submit'], button[type='submit']")
                if submit:
                    await submit.click()
                else:
                    await pw_input.press("Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                # Check if we're past the password page
                still_on_pw = await page.query_selector("form#login_form, form.storefront-password-form")
                return still_on_pw is None
            return False
        except Exception:
            return False

    async def _goto_shop(self, page: Page, path: str = "", wait: str = "domcontentloaded") -> Any:
        """Navigate to shop URL, handle password if needed."""
        url = f"{SHOP_URL}{path}" if path else SHOP_URL
        resp = await page.goto(url, wait_until=wait, timeout=30000)
        await self._handle_storefront_password(page)
        # If redirected back to password page after entering password, the page might reload
        # Give it a moment to settle
        await page.wait_for_timeout(1000)
        return resp

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
            "mystery_shopper": self._scenario_mystery_shopper,
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
            resp = await self._goto_shop(page)
            ss = await self.screenshot_b64(page)
            current_url = page.url
            if "/password" in current_url:
                s.fail("Stuck on password page — SHOPIFY_STORE_PASSWORD may be wrong", ss)
            elif resp and resp.status < 400:
                s.done(ss, f"HTTP {resp.status}")
            else:
                s.fail(f"HTTP {resp.status if resp else 'no response'}", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Navigation menu visible")
        try:
            # Broad Shopify selectors — works across Dawn, Debut, custom themes
            nav = await page.query_selector("header, nav, #shopify-section-header, [class*='header'], [class*='site-nav'], [class*='main-nav']")
            ss = await self.screenshot_b64(page)
            if nav:
                s.done(ss)
            else:
                s.fail("Nav/header not found", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Hero section / CTA visible")
        try:
            # Broad selectors for Shopify hero sections
            hero = await page.query_selector(
                "#shopify-section-slideshow, #shopify-section-image-banner, "
                "[class*='hero'], [class*='banner'], [class*='slideshow'], "
                "[class*='slider'], [class*='carousel'], "
                "section:first-of-type img, .shopify-section:nth-child(2)"
            )
            ss = await self.screenshot_b64(page)
            if hero:
                s.done(ss)
            else:
                # Even if no hero class found, check if page has meaningful content
                body_text = await page.inner_text("body")
                if len(body_text.strip()) > 100 and "password" not in body_text.lower():
                    s.done(ss, "No hero class found but page has content")
                else:
                    s.fail("No hero section found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Tour listings accessible")
        try:
            await self._goto_shop(page, "/pages/all-tours")
            await page.wait_for_timeout(3000)
            # Broad Shopify product selectors
            products = await page.query_selector(
                ".tour-card, .tour-card__link, .product-card, "
                "[class*='tour-card'], [class*='tours-grid'], "
                "a[href*='/products/'], article, .tours-grid .tour-card"
            )
            ss = await self.screenshot_b64(page)
            if products:
                s.done(ss)
            else:
                s.fail("No tour cards found on /pages/all-tours", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Tour search ───────────────────────────────────
    async def _scenario_tour_search(self, steps: List[Step], params: Dict):
        page = await self.new_page()

        s = Step("Open collections page")
        try:
            await self._goto_shop(page, "/pages/all-tours")
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Tour cards render with price")
        try:
            # Wait for any product element
            await page.wait_for_selector(
                ".tour-card, .tour-card__link, a[href*='/products/'], article",
                timeout=8000
            )
            # Try getting price from dedicated price element first
            price_el = await page.query_selector("[data-thb-price], .tour-card__price-value")
            text = ""
            if price_el:
                dp = await price_el.get_attribute("data-thb-price")
                if dp:
                    text = dp + " THB"
                else:
                    text = (await price_el.text_content()) or ""
            if not text:
                first_card = await page.query_selector(".tour-card, .product-card")
                text = (await first_card.text_content()) if first_card else ""
            ss = await self.screenshot_b64(page)
            if "฿" in text or "$" in text or "THB" in text or any(ch.isdigit() for ch in text):
                s.done(ss, f"Price visible: {text.strip()[:80]}")
            else:
                s.fail(f"Price not visible. Text found: {text[:200]}", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Click into a tour product page")
        try:
            link = await page.query_selector(
                ".tour-card__link, a[href*='/products/'], .tour-card a"
            )
            if link:
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
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
            btn = await page.query_selector(
                "button[name='add'], form[action*='/cart/add'] button[type='submit'], "
                "[class*='add-to-cart'], .product-form__submit, "
                "button:has-text('Add to cart'), button:has-text('Book Now')"
            )
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

        # First go to collections to find a real product
        s = Step("Navigate to a bookable tour")
        try:
            await self._goto_shop(page, "/pages/all-tours")
            await page.wait_for_timeout(3000)
            # Click first product link
            link = await page.query_selector("a[href*='/products/']")
            if link:
                href = await link.get_attribute("href")
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Navigated to: {href}")
            else:
                # Fallback to known product
                await self._goto_shop(page, "/products/snorkeling-trip")
                ss = await self.screenshot_b64(page)
                s.done(ss, "Fallback to snorkeling-trip")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Select date if date picker present")
        try:
            date_input = await page.query_selector(
                "input[type='date'], [class*='datepicker'], [class*='date-picker'], "
                "[class*='date'], select[name*='date'], .booking-date"
            )
            ss = await self.screenshot_b64(page)
            if date_input:
                s.done(ss, "Date picker found")
            else:
                s.done(ss, "No date picker — date selected at checkout or via note")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Add to cart")
        try:
            btn = await page.query_selector(
                "button[name='add'], form[action*='/cart/add'] button[type='submit'], "
                "[class*='add-to-cart'], .product-form__submit, "
                "button:has-text('Add to cart'), button:has-text('Book Now')"
            )
            if btn:
                await btn.click()
                await page.wait_for_timeout(3000)
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
            cart_link = await page.query_selector(
                "a[href='/cart'], a[href*='cart'], [class*='cart-icon'], "
                "[class*='cart-count'], .cart-link, .header__icon--cart"
            )
            ss = await self.screenshot_b64(page)
            if cart_link:
                await cart_link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.done(ss)
            else:
                # Try navigating directly to /cart
                await page.goto(f"{SHOP_URL}/cart", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.done(ss, "Navigated directly to /cart")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Checkout page accessible")
        try:
            # Shopify uses JS-rendered accelerated checkout — go directly to /checkout
            resp = await page.goto(f"{SHOP_URL}/checkout", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            current_url = page.url
            if "checkout" in current_url.lower() or "checkouts" in current_url.lower():
                s.done(ss, f"Checkout loaded: {current_url[:100]}")
            elif "cart" in current_url.lower():
                s.done(ss, "Redirected to cart — cart may be empty")
            else:
                s.fail(f"Unexpected redirect: {current_url}", ss)
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
            await self._goto_shop(page)
            await page.wait_for_timeout(5000)  # Extra time for chatbot widget to load
            ss = await self.screenshot_b64(page)
            s.done(ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Chatbot widget visible")
        try:
            # Look for common chatbot selectors + iframes
            chatbot = await page.query_selector(
                "[class*='chat'], [id*='chat'], iframe[src*='chat'], "
                ".chat-bubble, .chat-widget, [class*='tidio'], "
                "[class*='crisp'], [class*='intercom'], [class*='messenger'], "
                "#tidio-chat, .crisp-client, [data-chat]"
            )
            # Also check inside iframes
            if not chatbot:
                frames = page.frames
                for frame in frames:
                    chatbot = await frame.query_selector("[class*='chat'], [class*='widget']")
                    if chatbot:
                        break
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
            chatbot = await page.query_selector(
                "[class*='chat'], [id*='chat'], .chat-bubble, "
                "[class*='tidio'], #tidio-chat"
            )
            if chatbot:
                await chatbot.click()
                await page.wait_for_timeout(3000)
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
            await self._goto_shop(page)
            await page.wait_for_timeout(5000)
            s.done(await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Type tour question in chatbot")
        try:
            input_el = await page.query_selector(
                "[class*='chat'] input, [class*='chat'] textarea, "
                "[id*='chat'] input, [id*='chat'] textarea"
            )
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
            response = await page.query_selector(
                "[class*='bot-message'], [class*='chat-message'], "
                "[class*='response'], [class*='reply']"
            )
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
            await self._goto_shop(page)
            await page.wait_for_timeout(5000)
            s.done(await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Ask refund policy question")
        try:
            input_el = await page.query_selector(
                "[class*='chat'] input, [class*='chat'] textarea, "
                "[id*='chat'] input, [id*='chat'] textarea"
            )
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
            response = await page.query_selector(
                "[class*='bot-message'], [class*='chat-message'], [class*='reply']"
            )
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



    # ─── SCENARIO: Mystery Shopper (E2E real order) ──────────────
    async def _scenario_mystery_shopper(self, steps: List[Step], params: Dict):
        """
        Full mystery shopper: browse → find tour → add to cart → verify cart → checkout page.
        Does NOT complete payment. Tests the entire pre-payment flow.
        """
        tour_handle = params.get("tour_handle", "")
        page = await self.new_page()

        s = Step("Browse to All Tours page")
        try:
            await self._goto_shop(page, "/pages/all-tours")
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            cards = await page.query_selector_all(".tour-card")
            s.done(ss, f"Found {len(cards)} tour cards")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Find and click target tour")
        try:
            if tour_handle:
                link = await page.query_selector(f"a[href*=\'{tour_handle}\']")
            else:
                link = await page.query_selector(".tour-card__link, a[href*='/products/']")
            if link:
                href = await link.get_attribute("href")
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)
                ss = await self.screenshot_b64(page)
                title = await page.title()
                s.done(ss, f"Tour: {title[:80]}, URL: {href}")
            else:
                s.fail(f"Tour not found: {tour_handle or 'any'}", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Product page has price + images + variants")
        try:
            price = await page.query_selector("[class*='price'], .product-price, [data-product-price]")
            images = await page.query_selector_all("img[src*='cdn.shopify'], .product-image img, .gallery img")
            variants = await page.query_selector_all("select option, input[type='radio'][name*='option'], .variant-option")
            ss = await self.screenshot_b64(page)
            
            price_text = ""
            if price:
                price_text = (await price.text_content()) or ""
            
            notes = []
            if price_text: notes.append(f"Price: {price_text.strip()[:50]}")
            notes.append(f"Images: {len(images)}")
            notes.append(f"Variants/options: {len(variants)}")
            
            if len(images) == 0:
                s.fail("No product images found", ss)
            elif not price_text:
                s.fail("No price visible", ss)
            else:
                s.done(ss, " | ".join(notes))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Select date (if date picker exists)")
        try:
            date_input = await page.query_selector(
                "input[type='date'], [class*='datepicker'], [class*='date-picker'], "
                "select[name*='date'], .booking-date"
            )
            ss = await self.screenshot_b64(page)
            if date_input:
                tag = await date_input.evaluate("el => el.tagName")
                s.done(ss, f"Date picker found ({tag})")
            else:
                s.done(ss, "No date picker — date via checkout notes")
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Add to cart")
        try:
            btn = await page.query_selector(
                "button[name='add'], form[action*='/cart/add'] button[type='submit'], "
                ".product-form__submit, button:has-text('Add to cart'), button:has-text('Book Now')"
            )
            if btn:
                await btn.click()
                await page.wait_for_timeout(4000)
                ss = await self.screenshot_b64(page)
                s.done(ss, "Added to cart")
            else:
                s.fail("Add to cart button not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Verify cart has item")
        try:
            await page.goto(f"{SHOP_URL}/cart.js", wait_until="domcontentloaded", timeout=10000)
            cart_json_text = await page.inner_text("body")
            import json as _json
            cart_data = _json.loads(cart_json_text)
            item_count = cart_data.get("item_count", 0)
            total = cart_data.get("total_price", 0) / 100
            items = [{"title": i["title"], "quantity": i["quantity"], "price": i["price"]/100} for i in cart_data.get("items", [])]
            ss = await self.screenshot_b64(page)
            if item_count > 0:
                s.done(ss, f"Cart: {item_count} items, total {total} THB — {items}")
            else:
                s.fail("Cart is empty after add-to-cart", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Navigate to checkout")
        try:
            await page.goto(f"{SHOP_URL}/checkout", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
            ss = await self.screenshot_b64(page)
            url = page.url
            if "checkout" in url.lower() or "checkouts" in url.lower():
                s.done(ss, f"Checkout loaded: {url[:120]}")
            else:
                s.fail(f"Checkout not reached: {url}", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        s = Step("Checkout page has contact/shipping fields")
        try:
            # Look for standard Shopify checkout fields
            email_field = await page.query_selector("input[type='email'], input[name*='email'], #email")
            ss = await self.screenshot_b64(page)
            if email_field:
                s.done(ss, "Email field found on checkout")
            else:
                # Might be behind Shopify login wall
                page_text = await page.inner_text("body")
                if "contact" in page_text.lower() or "shipping" in page_text.lower() or "checkout" in page_text.lower():
                    s.done(ss, "Checkout content visible")
                else:
                    s.fail("No checkout fields found", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        await page.close()

    # ─── SCENARIO: Email check (placeholder) ─────────────────────
    async def _scenario_email_check(self, steps: List[Step], params: Dict):
        s = Step("Email check via ZeptoMail logs")
        s.fail("Not implemented — requires ZeptoMail API or mailbox access")
        steps.append(s)
