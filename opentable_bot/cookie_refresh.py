"""
Automated cookie refresh for OpenTable using Playwright.

Launches headless Chromium, logs into OpenTable, navigates to the
favorites page to trigger Akamai cookie generation, then extracts
all cookies and the CSRF token.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple


def refresh_cookies(
    email: str,
    password: str,
    cookie_file_path: Optional[Path] = None,
    headless: bool = True,
) -> Tuple[str, str, str]:
    """
    Log into OpenTable via Playwright and extract fresh cookies.

    Returns:
        (full_cookie_string, csrf_token, bearer_token)
    Raises:
        RuntimeError if login or cookie extraction fails.
    """
    from playwright.sync_api import sync_playwright

    csrf_token = ""
    bearer_token = ""

    def capture_csrf(request):
        nonlocal csrf_token
        token = request.headers.get("x-csrf-token", "")
        if token:
            csrf_token = token

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            java_script_enabled=True,
        )
        # Hide webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        # Capture CSRF token from outgoing requests
        page.on("request", capture_csrf)

        try:
            # Step 1: Go to OpenTable login page
            logging.info("Navigating to OpenTable login page...")
            page.goto("https://www.opentable.com/login", wait_until="domcontentloaded")
            time.sleep(2)

            # Step 2: Enter email
            logging.info("Entering email...")
            email_input = page.wait_for_selector(
                'input[type="email"], input[name="email"], #email',
                timeout=15000,
            )
            email_input.fill(email)
            time.sleep(0.5)

            # Click continue/next button after email
            submit_btn = page.wait_for_selector(
                'button[type="submit"], button:has-text("Continue"), '
                'button:has-text("Next"), button:has-text("Sign in")',
                timeout=10000,
            )
            submit_btn.click()
            time.sleep(2)

            # Step 3: Enter password
            logging.info("Entering password...")
            password_input = page.wait_for_selector(
                'input[type="password"], input[name="password"], #password',
                timeout=15000,
            )
            password_input.fill(password)
            time.sleep(0.5)

            # Click sign in
            sign_in_btn = page.wait_for_selector(
                'button[type="submit"], button:has-text("Sign in"), '
                'button:has-text("Log in")',
                timeout=10000,
            )
            sign_in_btn.click()

            # Wait for login to complete (redirect away from login page)
            logging.info("Waiting for login to complete...")
            page.wait_for_url("**/opentable.com/**", timeout=30000)
            time.sleep(3)

            # Step 4: Navigate to favorites to trigger Akamai cookies + wishlist
            logging.info("Navigating to favorites page...")
            page.goto(
                "https://www.opentable.com/user/favorites",
                wait_until="domcontentloaded",
            )
            time.sleep(3)

            # Step 5: Extract cookies
            cookies = context.cookies()
            cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
            full_cookie_str = "; ".join(cookie_parts)

            # Extract bearer token from authCke cookie
            for c in cookies:
                if c["name"] == "authCke":
                    import urllib.parse
                    decoded = urllib.parse.unquote(c["value"])
                    for part in decoded.split("&"):
                        if part.startswith("atk="):
                            bearer_token = part[4:]
                            break
                    break

            if not bearer_token:
                raise RuntimeError(
                    "Login may have failed — no authCke cookie found. "
                    "Check email/password in config."
                )

            logging.info(
                f"Cookie refresh successful. Got {len(cookies)} cookies, "
                f"bearer token: {bearer_token[:8]}..., "
                f"csrf token: {csrf_token[:8] + '...' if csrf_token else 'not captured'}"
            )

            # Step 6: Write cookies to file if path provided
            if cookie_file_path:
                cookie_file_path.write_text(full_cookie_str)
                logging.info(f"Cookies written to {cookie_file_path}")

            return full_cookie_str, csrf_token, bearer_token

        except Exception as err:
            # Take a screenshot for debugging
            try:
                screenshot_path = Path.cwd() / "config_files" / "login_debug.png"
                page.screenshot(path=str(screenshot_path))
                logging.error(f"Debug screenshot saved to {screenshot_path}")
            except Exception:
                pass
            raise RuntimeError(f"Cookie refresh failed: {err}") from err
        finally:
            browser.close()
