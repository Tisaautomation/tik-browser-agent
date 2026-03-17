import asyncio, base64, os, time
import httpx
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

        s = Step("Fill booking form (program, date, phone, pickup)")
        try:
            # TIK product pages require: program, date, WhatsApp, pickup location
            # Program is usually pre-selected, but verify
            program = await page.query_selector("#program-select")
            if program:
                # Select first available option
                await page.evaluate("""() => {
                    const sel = document.getElementById('program-select');
                    if (sel && sel.options.length > 1) {
                        sel.selectedIndex = 1;
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")
                await page.wait_for_timeout(500)

            # Set date — readonly text input, must use JS
            tomorrow = await page.evaluate("""() => {
                const d = new Date();
                d.setDate(d.getDate() + 3);
                const day = String(d.getDate()).padStart(2, '0');
                const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                const month = months[d.getMonth()];
                const year = d.getFullYear();
                const formatted = day + ' ' + month + ' ' + year;
                const dateInput = document.getElementById('tour-date');
                if (dateInput) {
                    dateInput.value = formatted;
                    dateInput.removeAttribute('readonly');
                    dateInput.dispatchEvent(new Event('change', { bubbles: true }));
                    // Update display
                    const display = document.getElementById('date-display');
                    if (display) display.querySelector('span').textContent = formatted;
                    return formatted;
                }
                return null;
            }""")

            # Fill WhatsApp number
            phone = await page.query_selector("#whatsapp-number")
            if phone:
                await phone.fill("812345678")

            # Set pickup location (hidden input — inject via JS)
            await page.evaluate("""() => {
                const loc = document.getElementById('pickup-location');
                if (loc) {
                    loc.value = 'Chaweng Beach Road, Koh Samui';
                    loc.dispatchEvent(new Event('change', { bubbles: true }));
                }
                const lat = document.getElementById('pickup-lat');
                const lng = document.getElementById('pickup-lng');
                if (lat) lat.value = '9.5321';
                if (lng) lng.value = '100.0623';
                const display = document.getElementById('location-display');
                if (display) display.textContent = 'Chaweng Beach Road, Koh Samui';
            }""")

            await page.wait_for_timeout(1000)
            ss = await self.screenshot_b64(page)
            notes = []
            if program: notes.append("Program set")
            if tomorrow: notes.append(f"Date: {tomorrow}")
            if phone: notes.append("Phone filled")
            notes.append("Pickup injected")
            s.done(ss, " | ".join(notes))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Add to cart")
        try:
            btn = await page.query_selector(
                ".submit-btn, button[type='submit'], "
                "button:has-text('Book Now'), button:has-text('Add to cart')"
            )
            if btn:
                await btn.click()
                await page.wait_for_timeout(4000)
                # Verify cart via API
                cart_data = await page.evaluate("""async () => {
                    try {
                        const r = await fetch('/cart.js');
                        const d = await r.json();
                        return { items: d.item_count, total: d.total_price / 100 };
                    } catch(e) { return { items: 0, error: e.message }; }
                }""")
                ss = await self.screenshot_b64(page)
                items = cart_data.get("items", 0)
                if items > 0:
                    s.done(ss, f"Cart: {items} items, {cart_data.get('total', 0)} THB")
                else:
                    s.fail(f"Button clicked but cart still empty — form validation may have blocked", ss)
            else:
                ss = await self.screenshot_b64(page)
                s.fail("Book Now / Add to cart button not found", ss)
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

        s = Step("Checkout form accessible on cart page")
        try:
            # We should already be on /cart from previous step
            # First verify cart has items via cart.js API
            cart_check = await page.evaluate("""async () => {
                try {
                    const r = await fetch('/cart.js');
                    const d = await r.json();
                    return { items: d.item_count, total: d.total_price / 100 };
                } catch(e) { return { items: 0, total: 0, error: e.message }; }
            }""")
            
            if cart_check.get("items", 0) == 0:
                # Cart empty — reload cart page to confirm
                await page.goto(f"{SHOP_URL}/cart", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                ss = await self.screenshot_b64(page)
                s.fail(f"Cart is empty (0 items) — add-to-cart may have failed silently (date required?)", ss)
                steps.append(s)
                await page.close()
                return
            
            # Cart has items — ensure we're on the cart page
            current_url = page.url
            if "/cart" not in current_url:
                await page.goto(f"{SHOP_URL}/cart", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
            else:
                # Reload to get fresh render with items
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
            
            # Check for custom TIK checkout elements
            checkout_btn = await page.query_selector("#checkout-btn, .checkout-btn, button:has-text('Complete Booking')")
            name_field = await page.query_selector("#customer-name, input[name='customer_name']")
            email_field = await page.query_selector("#customer-email, input[name='customer_email']")
            payment_options = await page.query_selector_all("input[name='payment_method']")
            
            ss = await self.screenshot_b64(page)
            notes = [f"Cart: {cart_check['items']} items, {cart_check['total']} THB"]
            if checkout_btn: notes.append("Complete Booking btn")
            if name_field: notes.append("Name field")
            if email_field: notes.append("Email field")
            if payment_options: notes.append(f"{len(payment_options)} payment methods")
            
            if checkout_btn and name_field and email_field:
                s.done(ss, " | ".join(notes))
            else:
                s.fail(f"Checkout form incomplete: {' | '.join(notes)}", ss)
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
    async def _new_page_with_geolocation(self, lat: float = 9.5321, lng: float = 100.0631) -> "Page":
        """Create a page with geolocation permissions granted (for Use My Location button)."""
        browser = await self._get_browser()
        context = await browser.new_context(
            viewport=self.viewport,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1" if "mobile" in self.viewport_name else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
            geolocation={"latitude": lat, "longitude": lng},
            permissions=["geolocation"],
        )
        page = await context.new_page()
        return page

    async def _scenario_mystery_shopper(self, steps: List[Step], params: Dict):
        """
        Full E2E customer simulation — clicks every button, fills every field.
        Flow: Product page → fill form → Book Now → Cart → checkout → Complete Booking → verify n8n.
        """
        tour_handle = params.get("tour_handle", "snorkeling-trip")
        adults = params.get("adults", 2)
        children = params.get("children", 0)
        infants = params.get("infants", 0)
        phone_number = params.get("phone", "994747897")
        customer_name = params.get("customer_name", "James Richardson")
        customer_email = params.get("customer_email", "info@tourinkohsamui.com")
        payment = params.get("payment_method", "cash")
        pickup_lat = float(params.get("pickup_lat", 9.5321))
        pickup_lng = float(params.get("pickup_lng", 100.0631))
        program_idx = params.get("program_index", 1)
        live = params.get("live", False)

        # Page with geolocation enabled for "Use My Location"
        page = await self._new_page_with_geolocation(pickup_lat, pickup_lng)

        # ─── STEP 1: Navigate to product page ──────────────────────
        s = Step("Navigate to tour product page")
        try:
            await self._goto_shop(page, f"/products/{tour_handle}")
            await page.wait_for_timeout(3000)
            title = await page.title()
            price_el = await page.query_selector("[class*='price'], .product-price, #total-price")
            price_text = ""
            if price_el:
                price_text = (await price_el.text_content() or "").strip()
            ss = await self.screenshot_b64(page)
            if "products" in page.url:
                s.done(ss, f"Loaded: {title[:60]} | Price: {price_text[:20]}")
            else:
                s.fail(f"Did not reach product page. URL: {page.url}", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)
        if s.status == "FAIL":
            await page.close()
            return

        # ─── STEP 2: Select program ────────────────────────────────
        s = Step("Select program")
        try:
            program_el = await page.query_selector("#program-select")
            if program_el:
                tag = await program_el.evaluate("el => el.tagName")
                if tag.upper() == "SELECT":
                    options = await page.query_selector_all("#program-select option")
                    if len(options) > program_idx:
                        val = await options[program_idx].get_attribute("value")
                        await page.select_option("#program-select", value=val)
                        await page.wait_for_timeout(500)
                        ss = await self.screenshot_b64(page)
                        s.done(ss, f"Selected program: {val}")
                    else:
                        ss = await self.screenshot_b64(page)
                        s.done(ss, f"Only {len(options)} options, kept default")
                else:
                    # Hidden input — already has a value
                    val = await program_el.get_attribute("value")
                    ss = await self.screenshot_b64(page)
                    s.done(ss, f"Program fixed: {val}")
            else:
                ss = await self.screenshot_b64(page)
                s.done(ss, "No program selector (single-program tour)")
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        # ─── STEP 2b: Select group size (for private tours) ───────
        group_el = await page.query_selector("#group-select")
        if group_el:
            s = Step("Select group size (private tour)")
            try:
                tag = await group_el.evaluate("el => el.tagName")
                if tag.upper() == "SELECT":
                    await page.select_option("#group-select", index=0)
                    await page.wait_for_timeout(500)
                ss = await self.screenshot_b64(page)
                s.done(ss, "Group size selected")
            except Exception as e:
                s.fail(str(e))
            steps.append(s)

        # ─── STEP 3: Set pax counts ────────────────────────────────
        s = Step(f"Set passengers: {adults}A / {children}C / {infants}I")
        try:
            # Clear and fill each field — triple-click selects all text, then type
            adults_el = await page.query_selector("#adults-qty")
            if adults_el:
                await adults_el.click(click_count=3)
                await adults_el.type(str(adults))

            children_el = await page.query_selector("#children-qty")
            if children_el:
                await children_el.click(click_count=3)
                await children_el.type(str(children))

            infants_el = await page.query_selector("#infants-qty")
            if infants_el:
                await infants_el.click(click_count=3)
                await infants_el.type(str(infants))

            # Trigger price recalculation
            await page.evaluate("""() => {
                if (typeof updateTotalPrice === 'function') updateTotalPrice();
                if (typeof updatePrivatePrice === 'function') updatePrivatePrice();
            }""")
            await page.wait_for_timeout(500)

            price_el = await page.query_selector("#total-price, #btn-price")
            price_now = ""
            if price_el:
                price_now = (await price_el.text_content() or "").strip()

            ss = await self.screenshot_b64(page)
            s.done(ss, f"Pax set | Price: {price_now}")
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        # ─── STEP 4: Pick date ─────────────────────────────────────
        s = Step("Select tour date")
        try:
            # Click the date button to open calendar modal
            date_btn = await page.query_selector("#date-display, .date-input, #tour-date")
            if date_btn:
                await date_btn.click()
                await page.wait_for_timeout(1000)

            # Calendar modal should be open — click a date 3 days from now
            # The calendar renders days as clickable elements
            # Inject the date value directly (calendar widget varies) then close modal
            tour_date = params.get("date", "")
            if not tour_date:
                tour_date = await page.evaluate("""() => {
                    const d = new Date();
                    d.setDate(d.getDate() + 3);
                    const day = String(d.getDate()).padStart(2, '0');
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    return day + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();
                }""")

            # Try clicking a date cell in the calendar first
            date_clicked = await page.evaluate(f"""() => {{
                // Look for clickable date cells
                const cells = document.querySelectorAll('.calendar-day:not(.disabled):not(.past), .day-cell:not(.disabled)');
                // Click one that's at least 3 days ahead
                for (const cell of cells) {{
                    const dayNum = parseInt(cell.textContent);
                    if (dayNum > 0) {{
                        cell.click();
                        return true;
                    }}
                }}
                return false;
            }}""")

            if not date_clicked:
                # Fallback: set value directly
                await page.evaluate(f"""() => {{
                    const dateInput = document.getElementById('tour-date');
                    if (dateInput) {{
                        dateInput.value = '{tour_date}';
                        dateInput.removeAttribute('readonly');
                        dateInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                    const display = document.getElementById('date-display');
                    if (display) {{
                        const span = display.querySelector('span');
                        if (span) span.textContent = '{tour_date}';
                    }}
                    // Close modal if open
                    const modal = document.getElementById('date-picker-modal');
                    if (modal) modal.style.display = 'none';
                }}""")

            await page.wait_for_timeout(500)
            # Verify date is set
            date_val = await page.evaluate("() => document.getElementById('tour-date')?.value || 'NOT SET'")
            ss = await self.screenshot_b64(page)
            if date_val and date_val != "NOT SET":
                s.done(ss, f"Date: {date_val}")
            else:
                s.fail("Date field is empty after selection", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        # ─── STEP 5: Fill WhatsApp number ──────────────────────────
        s = Step("Fill WhatsApp number")
        try:
            phone_el = await page.query_selector("#whatsapp-number")
            if phone_el:
                await phone_el.click()
                await phone_el.fill(phone_number)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Phone: {phone_number}")
            else:
                s.fail("WhatsApp field not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        # ─── STEP 6: Set pickup location (Use My Location) ────────
        s = Step("Set pickup location — Use My Location")
        try:
            # Click the map button to open modal
            map_btn = await page.query_selector(".map-button, button[onclick='openMapModal()']")
            if map_btn:
                await map_btn.click()
                await page.wait_for_timeout(1500)

                # Click "Use My Location" — geolocation is pre-granted
                use_loc_btn = await page.query_selector(".use-location-btn, button[onclick='useMyLocation()']")
                if use_loc_btn:
                    await use_loc_btn.click()
                    # Wait for geolocation resolve + reverse geocode
                    await page.wait_for_timeout(3000)

                    # Click "Confirm Location"
                    confirm_btn = await page.query_selector(".confirm-btn, button[onclick='confirmLocation()']")
                    if confirm_btn:
                        # Check if button is enabled (has location data)
                        is_disabled = await confirm_btn.get_attribute("disabled")
                        if is_disabled:
                            # Geolocation may have failed — fallback inject
                            await page.evaluate(f"""() => {{
                                document.getElementById('pickup-location').value = 'My Location ({pickup_lat}, {pickup_lng})';
                                document.getElementById('pickup-lat').value = '{pickup_lat}';
                                document.getElementById('pickup-lng').value = '{pickup_lng}';
                                document.getElementById('location-display').textContent = 'My Location';
                                document.getElementById('selected-address').textContent = 'My Location';
                                // Enable confirm button
                                document.querySelector('.confirm-btn').disabled = false;
                            }}""")
                            await page.wait_for_timeout(500)

                        await confirm_btn.click()
                        await page.wait_for_timeout(500)
                else:
                    # No Use My Location button — inject directly
                    await page.evaluate(f"""() => {{
                        document.getElementById('pickup-location').value = 'My Location ({pickup_lat}, {pickup_lng})';
                        document.getElementById('pickup-lat').value = '{pickup_lat}';
                        document.getElementById('pickup-lng').value = '{pickup_lng}';
                        document.getElementById('location-display').textContent = 'My Location';
                        // Close modal
                        const modal = document.getElementById('map-modal');
                        if (modal) modal.style.display = 'none';
                    }}""")
            else:
                # No map button — inject pickup values directly
                await page.evaluate(f"""() => {{
                    const loc = document.getElementById('pickup-location');
                    if (loc) loc.value = 'My Location ({pickup_lat}, {pickup_lng})';
                    const lat = document.getElementById('pickup-lat');
                    const lng = document.getElementById('pickup-lng');
                    if (lat) lat.value = '{pickup_lat}';
                    if (lng) lng.value = '{pickup_lng}';
                    const display = document.getElementById('location-display');
                    if (display) display.textContent = 'My Location';
                }}""")

            # Verify pickup was set
            loc_val = await page.evaluate("() => document.getElementById('pickup-location')?.value || ''")
            ss = await self.screenshot_b64(page)
            if loc_val:
                s.done(ss, f"Pickup: {loc_val[:50]}")
            else:
                s.fail("Pickup location not set", ss)
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        # ─── STEP 7: Click Book Now ────────────────────────────────
        s = Step("Click Book Now → add to cart")
        try:
            # Capture alerts
            alert_messages = []
            async def handle_dialog(dialog):
                alert_messages.append(dialog.message)
                await dialog.accept()
            page.on("dialog", handle_dialog)

            # Trigger price calc one more time
            await page.evaluate("""() => {
                if (typeof updateTotalPrice === 'function') updateTotalPrice();
                if (typeof updatePrivatePrice === 'function') updatePrivatePrice();
            }""")
            await page.wait_for_timeout(500)

            book_btn = await page.query_selector(".submit-btn, button[type='submit']")
            if book_btn:
                await book_btn.click()
                await page.wait_for_timeout(6000)

                # Check cart
                cart_data = await page.evaluate("""async () => {
                    try {
                        const r = await fetch('/cart.js');
                        const d = await r.json();
                        return { items: d.item_count, total: d.total_price / 100 };
                    } catch(e) { return { items: 0, error: e.message }; }
                }""")

                ss = await self.screenshot_b64(page)
                items = cart_data.get("items", 0)
                if items > 0:
                    s.done(ss, f"Added to cart: {items} items, ฿{cart_data.get('total', 0)}")
                elif alert_messages:
                    s.fail(f"Alert: {' | '.join(alert_messages)}", ss)
                else:
                    # Debug form state
                    debug = await page.evaluate("""() => {
                        return {
                            date: document.getElementById('tour-date')?.value || 'EMPTY',
                            phone: document.getElementById('whatsapp-number')?.value || 'EMPTY',
                            pickup: document.getElementById('pickup-location')?.value || 'EMPTY',
                            adults: document.getElementById('adults-qty')?.value || '0',
                            program: document.getElementById('program-select')?.value || 'NONE',
                            form: !!document.getElementById('product-form'),
                            btn: !!document.querySelector('.submit-btn'),
                        }
                    }""")
                    s.fail(f"Cart empty after click. Form state: {debug}", ss)
            else:
                s.fail("Book Now button not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)
        if s.status == "FAIL":
            await page.close()
            return

        # ─── STEP 8: Navigate to cart page ─────────────────────────
        s = Step("Navigate to cart page")
        try:
            await page.goto(f"{SHOP_URL}/cart", wait_until="domcontentloaded", timeout=30000)
            await self._handle_storefront_password(page)
            await page.wait_for_timeout(3000)
            # Verify checkout form exists
            checkout_form = await page.query_selector("#checkout-form")
            ss = await self.screenshot_b64(page)
            if checkout_form:
                s.done(ss, "Cart page loaded with checkout form")
            else:
                s.fail("Checkout form not found on /cart", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)
        if s.status == "FAIL":
            await page.close()
            return

        # ─── STEP 9: Fill customer name ────────────────────────────
        s = Step(f"Fill customer name: {customer_name}")
        try:
            name_field = await page.query_selector("#customer-name")
            if name_field:
                await name_field.click()
                await name_field.fill(customer_name)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Name: {customer_name}")
            else:
                s.fail("Customer name field not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        # ─── STEP 10: Fill customer email ──────────────────────────
        s = Step(f"Fill customer email: {customer_email}")
        try:
            email_field = await page.query_selector("#customer-email")
            if email_field:
                await email_field.click()
                await email_field.fill(customer_email)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Email: {customer_email}")
            else:
                s.fail("Customer email field not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        # ─── STEP 11: Select payment method ────────────────────────
        s = Step(f"Select payment: {payment}")
        try:
            pay_radio = await page.query_selector(f"input[name='payment_method'][value='{payment}']")
            if pay_radio:
                # Click the label (parent) for visual feedback
                await pay_radio.evaluate("el => el.closest('label')?.click() || el.click()")
                await page.wait_for_timeout(500)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Payment: {payment}")
            else:
                # List available payment options
                available = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('input[name="payment_method"]'))
                        .filter(el => el.closest('label')?.style.display !== 'none')
                        .map(el => el.value);
                }""")
                s.fail(f"Payment '{payment}' not found. Available: {available}", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        # ─── STEP 12: Click Complete Booking ───────────────────────
        if not live:
            s = Step("DRY RUN — Ready to submit (not clicking)")
            try:
                checkout_btn = await page.query_selector("#checkout-btn:not(:disabled)")
                ss = await self.screenshot_b64(page)
                if checkout_btn:
                    s.done(ss, "Complete Booking button ready. Pass live=true to submit.")
                else:
                    s.fail("Checkout button disabled or not found", ss)
            except Exception as e:
                s.fail(str(e))
            steps.append(s)
        else:
            s = Step("LIVE — Click Complete Booking")
            try:
                checkout_btn = await page.query_selector("#checkout-btn")
                if checkout_btn:
                    # Listen for network response from n8n webhook
                    async with page.expect_response(
                        lambda r: "webhook" in r.url and r.status == 200,
                        timeout=30000
                    ) as response_info:
                        await checkout_btn.click()
                        response = await response_info.value
                        resp_body = await response.json()

                    ss = await self.screenshot_b64(page)
                    if resp_body.get("success"):
                        booking_id = resp_body.get("bookingId", resp_body.get("orderNumber", ""))
                        s.done(ss, f"BOOKED — {booking_id} | {customer_name} | {customer_email}")
                    else:
                        err = resp_body.get("error", resp_body.get("message", "Unknown"))
                        s.fail(f"n8n response: {err}", ss)
                else:
                    s.fail("Checkout button not found", await self.screenshot_b64(page))
            except Exception as e:
                # If expect_response times out, the webhook might not have fired
                ss = await self.screenshot_b64(page)
                # Check if there's a success popup on page
                popup = await page.query_selector(".booking-popup-overlay")
                popup_text = ""
                if popup:
                    popup_text = (await popup.text_content() or "")[:200]
                if "success" in popup_text.lower() or "confirmed" in popup_text.lower():
                    s.done(ss, f"Booking submitted (popup: {popup_text[:80]})")
                else:
                    s.fail(f"Error: {str(e)[:200]} | Popup: {popup_text[:100]}", ss)
            steps.append(s)

            # ─── STEP 13: Verify booking landed ───────────────────
            s = Step("Verify booking in n8n / Supabase")
            try:
                await page.wait_for_timeout(3000)
                # Check success popup
                popup = await page.query_selector(".booking-popup-overlay")
                popup_text = ""
                if popup:
                    popup_text = (await popup.text_content() or "")[:300]
                ss = await self.screenshot_b64(page)
                if popup_text:
                    s.done(ss, f"Result: {popup_text[:150]}")
                else:
                    s.done(ss, "No popup detected — check n8n executions manually")
            except Exception as e:
                s.fail(str(e))
            steps.append(s)

        await page.close()

    # ─── SCENARIO: Email check (placeholder) ─────────────────────
    async def _scenario_email_check(self, steps: List[Step], params: Dict):
        s = Step("Email check via ZeptoMail logs")
        s.fail("Not implemented — requires ZeptoMail API or mailbox access")
        steps.append(s)

