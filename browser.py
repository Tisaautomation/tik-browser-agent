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

        # Get booking params
        adults = params.get("adults", 1)
        children = params.get("children", 0)
        infants = params.get("infants", 0)
        tour_date = params.get("date", "")
        phone_number = params.get("phone", "812345678")
        pickup = params.get("pickup", "Chaweng Beach Road, Koh Samui")
        pickup_lat = params.get("pickup_lat", "9.5321")
        pickup_lng = params.get("pickup_lng", "100.0623")
        program_idx = params.get("program_index", 1)

        s = Step("Fill booking form (program, pax, date, phone, pickup)")
        try:
            # Select program
            program = await page.query_selector("#program-select")
            if program:
                await page.evaluate(f"""() => {{
                    const sel = document.getElementById('program-select');
                    if (sel && sel.options.length > {program_idx}) {{
                        sel.selectedIndex = {program_idx};
                        sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}""")
                await page.wait_for_timeout(500)

            # Also handle group-select for private tours (first option is valid — just trigger change)
            group_select = await page.query_selector("#group-select")
            if group_select:
                await page.evaluate("""() => {
                    const sel = document.getElementById('group-select');
                    if (sel && sel.options.length > 0) {
                        // First option is already the correct group size
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    // Trigger price calc
                    if (typeof updatePrivatePrice === 'function') updatePrivatePrice();
                }""")
                await page.wait_for_timeout(500)

            # Set pax counts
            await page.evaluate(f"""() => {{
                const setQty = (id, val) => {{
                    const el = document.getElementById(id);
                    if (el) {{ el.value = val; el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}
                }};
                setQty('adults-qty', {adults});
                setQty('children-qty', {children});
                setQty('infants-qty', {infants});
                // Trigger price recalculation
                if (typeof updateTotalPrice === 'function') updateTotalPrice();
                if (typeof updatePrivatePrice === 'function') updatePrivatePrice();
            }}""")
            await page.wait_for_timeout(500)

            # Set date
            if not tour_date:
                tour_date = await page.evaluate("""() => {
                    const d = new Date();
                    d.setDate(d.getDate() + 3);
                    const day = String(d.getDate()).padStart(2, '0');
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    return day + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();
                }""")
            
            await page.evaluate(f"""() => {{
                const dateInput = document.getElementById('tour-date');
                if (dateInput) {{
                    dateInput.value = '{tour_date}';
                    dateInput.removeAttribute('readonly');
                    dateInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    const display = document.getElementById('date-display');
                    if (display) {{
                        const span = display.querySelector('span');
                        if (span) span.textContent = '{tour_date}';
                    }}
                }}
            }}""")

            # Fill WhatsApp via JS (type="tel" input needs direct value set)
            await page.evaluate(f"""() => {{
                const phone = document.getElementById('whatsapp-number') || document.querySelector('input[name="properties[WhatsApp Number]"]');
                if (phone) {{
                    phone.value = '{phone_number}';
                    phone.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    phone.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}""")

            # Set pickup location
            await page.evaluate(f"""() => {{
                const loc = document.getElementById('pickup-location');
                if (loc) loc.value = '{pickup}';
                const lat = document.getElementById('pickup-lat');
                const lng = document.getElementById('pickup-lng');
                if (lat) lat.value = '{pickup_lat}';
                if (lng) lng.value = '{pickup_lng}';
                const display = document.getElementById('location-display');
                if (display) display.textContent = '{pickup}';
            }}""")

            await page.wait_for_timeout(1000)
            ss = await self.screenshot_b64(page)
            s.done(ss, f"{adults}A/{children}C/{infants}I | {tour_date} | {pickup[:30]}")
        except Exception as e:
            s.fail(str(e), await self.screenshot_b64(page))
        steps.append(s)

        s = Step("Add to cart")
        try:
            # Capture alerts
            alert_messages = []
            async def handle_dialog(dialog):
                alert_messages.append(dialog.message)
                await dialog.accept()
            page.on("dialog", handle_dialog)
            
            # Debug: check page state before submitting
            try:
                debug = await page.evaluate("""() => {
                    try {
                        const info = {};
                        info.isGroupMode = typeof isGroupMode !== 'undefined' ? isGroupMode : 'undefined';
                        info.program = document.getElementById('program-select')?.value || 'none';
                        info.group = document.getElementById('group-select')?.value || 'none';
                        info.date = document.getElementById('tour-date')?.value || 'none';
                        info.phone = document.querySelector('input[name="properties[WhatsApp Number]"]')?.value || 'none';
                        info.location = document.getElementById('pickup-location')?.value || 'none';
                        info.adults = document.getElementById('adults-qty')?.value || '0';
                        info.children = document.getElementById('children-qty')?.value || '0';
                        info.infants = document.getElementById('infants-qty')?.value || '0';
                        info.form = !!document.getElementById('product-form');
                        info.btn = !!document.querySelector('.submit-btn');
                        return info;
                    } catch(e) { return { error: e.message }; }
                }""")
            except Exception:
                debug = {"error": "debug eval failed"}
            
            # Trigger price calc
            await page.evaluate("""() => {
                if (typeof updatePrivatePrice === 'function') updatePrivatePrice();
                else if (typeof updateTotalPrice === 'function') updateTotalPrice();
            }""")
            await page.wait_for_timeout(1000)
            
            btn = await page.query_selector(".submit-btn, button[type='submit']")
            if btn:
                # Use form submit instead of button click for proper event handling
                form = await page.query_selector("#product-form, form[action*='cart']")
                if form:
                    await page.evaluate("""() => {
                        const form = document.getElementById('product-form') || document.querySelector('form');
                        if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                    }""")
                else:
                    await btn.click()
                
                await page.wait_for_timeout(8000)
                
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
                elif alert_messages:
                    s.fail(f"Alert: {' | '.join(alert_messages)} | Debug: {str(debug)[:300]}", ss)
                else:
                    s.fail(f"Cart empty, no alerts. Debug: {str(debug)[:400]}", ss)
            else:
                s.fail(f"No submit btn. Debug: {str(debug)[:300]}", await self.screenshot_b64(page))
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

        s = Step("Checkout form visible on cart page")
        try:
            # TIK checkout form is embedded in /cart page — NOT Shopify /checkout
            await page.goto(f"{SHOP_URL}/cart", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            
            checkout_btn = await page.query_selector("#checkout-btn, .checkout-btn, button:has-text('Complete Booking')")
            name_field = await page.query_selector("#customer-name, input[name='customer_name']")
            email_field = await page.query_selector("#customer-email, input[name='customer_email']")
            
            ss = await self.screenshot_b64(page)
            if checkout_btn and name_field and email_field:
                s.done(ss, "Full TIK checkout form found on /cart")
            else:
                parts = []
                if not checkout_btn: parts.append("no checkout button")
                if not name_field: parts.append("no name field")
                if not email_field: parts.append("no email field")
                s.fail(f"Checkout form incomplete: {', '.join(parts)}", ss)
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        # Get params for customer info
        customer_name = params.get("customer_name", "Mystery Shopper Test")
        customer_email = params.get("customer_email", "info@tourinkohsamui.com")
        payment = params.get("payment_method", "cash")
        live = params.get("live", False)

        s = Step("Fill customer info on checkout form")
        try:
            name_field = await page.query_selector("#customer-name")
            email_field = await page.query_selector("#customer-email")
            
            if name_field and email_field:
                await name_field.fill(customer_name)
                await email_field.fill(customer_email)
                
                # Select payment method
                pay_radio = await page.query_selector(f"input[name='payment_method'][value='{payment}']")
                if pay_radio:
                    await pay_radio.evaluate("el => el.click()")
                
                await page.wait_for_timeout(1000)
                ss = await self.screenshot_b64(page)
                s.done(ss, f"Name: {customer_name} | Email: {customer_email} | Payment: {payment}")
            else:
                s.fail("Customer form fields not found", await self.screenshot_b64(page))
        except Exception as e:
            s.fail(str(e))
        steps.append(s)

        if live:
            s = Step("LIVE — Submit booking to n8n")
            try:
                # Collect cart data from browser
                cart_and_form = await page.evaluate("""async () => {
                    try {
                        const cartResp = await fetch('/cart.js');
                        const cart = await cartResp.json();
                        const name = document.getElementById('customer-name')?.value || '';
                        const email = document.getElementById('customer-email')?.value || '';
                        const pay = document.querySelector('input[name="payment_method"]:checked')?.value || 'cash';
                        return { cart, name, email, pay };
                    } catch(e) { return { error: e.message }; }
                }""")
                
                if cart_and_form.get("error"):
                    s.fail(f"Cart read error: {cart_and_form['error']}", await self.screenshot_b64(page))
                    steps.append(s)
                else:
                    cart = cart_and_form["cart"]
                    items = cart.get("items", [])
                    if not items:
                        s.fail("Cart is empty — cannot submit", await self.screenshot_b64(page))
                        steps.append(s)
                    else:
                        # Build payload same as submitBooking() JS
                        item = items[0]
                        props = item.get("properties", {})
                        payload = {
                            "variant_id": str(item.get("variant_id", "")),
                            "quantity": 1,
                            "cartGroupId": f"CG-agent-{int(time.time())}",
                            "cartIndex": 1,
                            "cartTotal": 1,
                            "customerName": cart_and_form["name"],
                            "customerEmail": cart_and_form["email"],
                            "customerPhone": props.get("WhatsApp Number", ""),
                            "whatsapp": props.get("WhatsApp Number", ""),
                            "countryCode": props.get("Country Code", "+66"),
                            "tourDate": props.get("Date", ""),
                            "program": props.get("Program", ""),
                            "pickupLocation": props.get("Pick-up Location", ""),
                            "pickupLat": props.get("Pickup Lat", ""),
                            "pickupLng": props.get("Pickup Lng", ""),
                            "specialRequests": props.get("Special Requests", ""),
                            "adults": int(props.get("Adults", adults)),
                            "children": int(props.get("Children", children)),
                            "infants": int(props.get("Infants", infants)),
                            "bookingType": props.get("Booking Type", "Private"),
                            "numberOfPersons": int(props.get("Total People", adults + children + infants)),
                            "paymentMethod": cart_and_form["pay"],
                            "productId": item.get("product_id", 0),
                            "productTitle": item.get("product_title", ""),
                            "price": item.get("final_line_price", 0) / 100,
                        }
                        
                        # POST directly to n8n (bypass browser CORS issues)
                        N8N_URL = os.environ.get("N8N_DEV_URL", "https://n8n-production-6ffa.up.railway.app")
                        async with httpx.AsyncClient(timeout=30) as client:
                            resp = await client.post(
                                f"{N8N_URL}/webhook/cart-booking",
                                json=payload
                            )
                            result = resp.json()
                        
                        ss = await self.screenshot_b64(page)
                        if result.get("success"):
                            booking_id = result.get("bookingId", result.get("orderNumber", ""))
                            # Clear cart in browser
                            await page.evaluate("fetch('/cart/clear.js', {method:'POST'})")
                            s.done(ss, f"BOOKED — {booking_id} | {cart_and_form['name']} | {cart_and_form['email']} | {payload['tourDate']} | ฿{payload['price']}")
                        else:
                            err = result.get("error", "Unknown error")
                            s.fail(f"n8n rejected: {err}", ss)
                        steps.append(s)

            except Exception as e:
                s.fail(str(e), await self.screenshot_b64(page))
                steps.append(s)
        else:
            s = Step("DRY RUN — Complete Booking button ready (not clicking)")
            try:
                checkout_btn = await page.query_selector("#checkout-btn:not(:disabled)")
                ss = await self.screenshot_b64(page)
                if checkout_btn:
                    s.done(ss, "Ready to submit — pass live=true to actually book")
                else:
                    s.fail("Button disabled or not found", ss)
            except Exception as e:
                s.fail(str(e))
            steps.append(s)

        await page.close()

    # ─── SCENARIO: Email check (placeholder) ─────────────────────
    async def _scenario_email_check(self, steps: List[Step], params: Dict):
        s = Step("Email check via ZeptoMail logs")
        s.fail("Not implemented — requires ZeptoMail API or mailbox access")
        steps.append(s)
