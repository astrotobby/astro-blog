"""One-time helper: save your logged-in Rumble session for the blog-to-video pipeline.

Rumble has no upload API, so the pipeline drives the upload page in a browser. The
GitHub runner often isn't shown Rumble's login form, so instead it reuses a session
you create here, on your own computer, by logging in normally.

    pip install playwright
    python -m playwright install chromium
    python scripts/rumble_session.py

A browser window opens: log in to Rumble yourself (including any 2FA), then come back
to this terminal and press Enter. The script writes rumble_session.b64 next to it.
Paste that file's contents into a GitHub repo secret named RUMBLE_STORAGE_STATE, then
delete the file. Repeat whenever uploads report that the saved session expired.
"""
import base64
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).with_name("rumble_session.b64")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://rumble.com/login.php")
    input("Log in to Rumble in the browser window, then press Enter here... ")
    page.goto("https://rumble.com/upload.php")
    page.wait_for_timeout(3000)
    if "login" in page.url:
        print("Still not logged in -- nothing saved. Run the script again.")
    else:
        state = context.storage_state()
        import json
        OUT.write_text(base64.b64encode(json.dumps(state).encode()).decode())
        print(f"Saved {OUT}. Paste its contents into the RUMBLE_STORAGE_STATE secret, "
              "then delete the file.")
    browser.close()
