"""
One-time login: opens a real browser, you sign in to Google by hand,
then press Enter in the terminal. The session is saved to state/auth.json,
which score_blogs.py loads. Re-run this if the session expires.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

AUTH_STATE = Path("state/auth.json")
CHAT_URL = "https://gemini.google.com/app"

AUTH_STATE.parent.mkdir(exist_ok=True)

with sync_playwright() as p:
    # channel="chrome" uses your installed Chrome; Google is less likely to
    # reject it than Playwright's bundled Chromium. Remove it to use Chromium.
    browser = p.chromium.launch(
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context()
    page = context.new_page()
    page.goto(CHAT_URL)

    input("Sign in to Google in the browser window until you see the Gemini "
          "chat box, then press Enter here... ")

    context.storage_state(path=str(AUTH_STATE))
    print(f"Saved session to {AUTH_STATE}")
    browser.close()
