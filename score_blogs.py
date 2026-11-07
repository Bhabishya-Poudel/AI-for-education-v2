"""
Score every blog on all 14 criteria through the Gemini web UI and write scores.csv.
"""
import os
import re
import sys
import json
import glob
import time
import random
import pandas as pd
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BLOGS_FOLDER = "blogs"
REFERENCE_FILE = "LawsOfMotionWiki.txt"
OUTPUT_CSV = "scores.csv"
CHAT_URL = "https://gemini.google.com/app"
AUTH_STATE = Path("state/auth.json")  # created by save_login.py

# --- Gemini page selectors -------------------------------------------------
# Several candidates per element, tried in order, because Gemini changes its markup.
INPUT_SELECTORS = [
    "rich-textarea div.ql-editor[contenteditable='true']",
    "div.ql-editor[contenteditable='true']",
    "div[role='textbox'][contenteditable='true']",
    "textarea",
]
SEND_SELECTORS = [
    "button[aria-label*='Send message']",
    "button.send-button",
    "button[aria-label*='Send']",
]
STOP_SELECTORS = [
    "button[aria-label*='Stop']",
    "button.stop",
]
REPLY_SELECTORS = [
    "model-response message-content",
    "model-response",
    ".model-response-text",
]

REPLY_TIMEOUT_S = 240        # max wait for one answer
PAUSE_BETWEEN_BLOGS_S = (15, 30)
RETRIES_PER_BLOG = 2
HEADLESS = False             # keep False: Google may block headless logins

CRITERIA_NAMES = [
    "accuracy", "completeness", "linguistic_accessibility",
    "organization_coherence", "explanation_conceptual_development",
    "learning_objective_alignment", "practice_application",
    "cognitive_engagement", "learner_appropriateness_inclusivity",
    "visual_multimodal_representation", "usability_accessibility",
    "credibility_provenance", "assessment_feedback",
    "interactivity_collaboration",
]

_pw = {}  # lazily-created Playwright objects, reused across calls


class GeminiError(Exception):
    """A recoverable problem with one blog (retry or skip it)."""


def _get_page():
    if "page" not in _pw:
        if not AUTH_STATE.exists():
            raise SystemExit(f"\n{AUTH_STATE} not found (see save_login.py).")
        _pw["p"] = sync_playwright().start()
        _pw["browser"] = _pw["p"].chromium.launch(
            headless=HEADLESS, channel="chrome", slow_mo=50,
            args=["--disable-blink-features=AutomationControlled"])
        _pw["context"] = _pw["browser"].new_context(storage_state=str(AUTH_STATE))
        _pw["page"] = _pw["context"].new_page()
    return _pw["page"]


def close_browser():
    if "browser" in _pw:
        _pw["browser"].close()
        _pw["p"].stop()
        _pw.clear()


def _first_visible(page, selectors, timeout_ms=15000):
    """Return a locator for the first selector that becomes visible."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() and loc.last.is_visible():
                return loc.last
        page.wait_for_timeout(300)
    return None


def _reply_count(page):
    for sel in REPLY_SELECTORS:
        n = page.locator(sel).count()
        if n:
            return n, sel
    return 0, None


def _attach_files(page, files):
    """Attach local files through Gemini's 'Upload and tools' menu."""
    page.locator("button[aria-label='Upload and tools']").first.click()
    page.wait_for_timeout(800)
    item = page.locator("[role='menuitem']:has-text('Upload files')").first
    with page.expect_file_chooser(timeout=10000) as fc:
        item.click()
    fc.value.set_files([str(f) for f in files])
    # Wait until every file chip is shown (they have a 'close <name>' button).
    deadline = time.time() + 90
    while time.time() < deadline:
        if page.locator("button[aria-label^='close ']").count() >= len(files):
            break
        page.wait_for_timeout(500)
    else:
        raise GeminiError("file attachments did not appear")
    page.wait_for_timeout(3000)  # let uploads finish


def ask_gemini(prompt, files=()):
    """Send a short prompt (plus attached files) to Gemini in a fresh chat;
    return the raw reply text."""
    page = _get_page()
    try:
        page.goto(CHAT_URL, wait_until="domcontentloaded")  # fresh chat each time
        page.wait_for_timeout(2500)
        if "accounts.google.com" in page.url:
            raise SystemExit("\nGoogle asked for a login: session expired.")

        box = _first_visible(page, INPUT_SELECTORS)
        if box is None:
            raise GeminiError("could not find the chat input box")
        if files:
            _attach_files(page, files)
        box = _first_visible(page, INPUT_SELECTORS) or box
        box.click()
        box.fill(prompt)
        page.wait_for_timeout(1000)

        send = _first_visible(page, SEND_SELECTORS, timeout_ms=5000)
        if send is not None:
            send.click()
        else:
            box.press("Enter")

        # Wait for the reply to appear, then for generation to finish.
        deadline = time.time() + REPLY_TIMEOUT_S
        while time.time() < deadline and _reply_count(page)[0] == 0:
            page.wait_for_timeout(500)
        count, reply_sel = _reply_count(page)
        if not reply_sel:
            raise GeminiError("no reply appeared")

        last, stable = "", 0
        while time.time() < deadline:
            generating = any(page.locator(s).count() and
                             page.locator(s).first.is_visible()
                             for s in STOP_SELECTORS)
            current = page.locator(reply_sel).last.inner_text()
            if not generating and current and current == last:
                stable += 1
                if stable >= 3:
                    return current
            else:
                stable, last = 0, current
            page.wait_for_timeout(1000)
        raise GeminiError("reply did not finish in time")
    except PWTimeout as e:
        raise GeminiError(f"Playwright timeout: {e}") from e


def parse_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    
    #Parse_json = to just extract JSON values from AI's ratings and remove sentences


def build_prompt(blog_name, has_reference):
    """Short instruction; the three texts travel as attached files."""
    shape = ",\n".join(f'  "{c}": <SCORE>' for c in CRITERIA_NAMES)
    ref = ("The file LawsOfMotionWiki.txt is the trusted REFERENCE; use it when "
           "judging accuracy and completeness.\n" if has_reference else "")
    return f"""You are evaluating an educational blog post against a formal
criterion framework. Three text files are attached:
  1. criteria.txt - the full 14-criterion framework
  2. LawsOfMotionWiki.txt - the trusted reference text
  3. {blog_name} - the BLOG TO EVALUATE (the blog is the attached file, it
     is not missing)
Read all attached files completely before scoring. {ref}
SCORING SCALE
  1 = very poor   2 = poor   3 = adequate   4 = good   5 = excellent
  null = this criterion genuinely does not apply, or there is insufficient
         context to evaluate it
Use null rather than a low score when a criterion cannot be evaluated.
Respect each criterion's BOUNDARY section; score each criterion on its own.

Return ONLY a JSON object and no other text. Replace each <SCORE>
placeholder with an integer from 1 to 5, or with null:

{{
{shape}
}}"""


def _blog_number(path):
    m = re.search(r"(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else 0


def _natural_key(path):
    return (_blog_number(path), os.path.basename(path))


def main():
    global OUTPUT_CSV

    reference_text = ""
    if os.path.exists(REFERENCE_FILE):
        with open(REFERENCE_FILE, encoding="utf-8") as f:
            reference_text = f.read()
        print(f"Using {REFERENCE_FILE} as the trusted source.")
    else:
        print(f"No {REFERENCE_FILE} found. Accuracy/completeness will be "
              "judged from the model's own knowledge instead.")

    blog_files = sorted(glob.glob(os.path.join(BLOGS_FOLDER, "*.txt")),
                        key=_natural_key)
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        m = re.fullmatch(r"(\d+)-(\d+)", arg)
        if m:
            #batch mode: python score_blogs.py 3-7  -> Blog3 ... Blog7
            lo, hi = int(m.group(1)), int(m.group(2))
            blog_files = [p for p in blog_files
                          if lo <= _blog_number(p) <= hi]
        else:
            #test mode: python score_blogs.py Blog5.txt
            blog_files = [os.path.join(BLOGS_FOLDER, arg)]
            OUTPUT_CSV = "test_scores.csv"
    if not blog_files:
        raise SystemExit(f"No .txt files found in the '{BLOGS_FOLDER}' folder.")

    # Resume: keep rows already scored, skip those blogs.
    rows = []
    if os.path.exists(OUTPUT_CSV):
        prev = pd.read_csv(OUTPUT_CSV)
        rows = prev.to_dict("records")
    done = {r["blog"] for r in rows}
    todo = [p for p in blog_files if os.path.basename(p) not in done]
    print(f"Found {len(blog_files)} blog(s); {len(done)} already scored, "
          f"{len(todo)} to do.\n")

    def save():
        if rows:
            pd.DataFrame(rows).set_index("blog").to_csv(OUTPUT_CSV)

    try:
        for i, path in enumerate(todo):
            name = os.path.basename(path)
            print(f"Scoring {name} ...", end=" ", flush=True)
            prompt = build_prompt(name, bool(reference_text))
            files = [Path("criteria.txt")]
            if reference_text:
                files.append(Path(REFERENCE_FILE))
            files.append(Path(path))

            scores = None
            for attempt in range(1, RETRIES_PER_BLOG + 2):
                try:
                    answer = ask_gemini(prompt, files)
                except GeminiError as e:
                    print(f"\n  attempt {attempt} failed: {e}", flush=True)
                    continue
                scores = parse_json(answer)
                if scores is not None:
                    break
                print(f"\n  attempt {attempt}: could not parse JSON. "
                      f"Raw answer: {answer[:200]!r}", flush=True)

            if scores is None:
                print("  giving up on this blog (not saved; it will be retried "
                      "on the next run).")
                continue

            row = {"blog": name}
            for crit in CRITERIA_NAMES:
                row[crit] = scores.get(crit)
            rows.append(row)
            save()  # write after every blog so nothing is lost
            print("done.")

            if i < len(todo) - 1:
                time.sleep(random.uniform(*PAUSE_BETWEEN_BLOGS_S))
    except (SystemExit, KeyboardInterrupt):
        save()
        print(f"\nStopped early. Saved {len(rows)} blog(s) to {OUTPUT_CSV}.")
        raise

    if not rows:
        raise SystemExit("\nNo blogs scored successfully.")
    print(f"\nSaved {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_browser()
