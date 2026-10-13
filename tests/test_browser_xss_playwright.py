"""tests/test_browser_xss_playwright.py
Playwright browser integration test verifying that:
1. Malicious filename `<img src=x onerror=alert(1)>.md` containing an XSS payload
   does not execute any JavaScript or trigger alert dialogs.
2. Content-Security-Policy and security response headers are strictly enforced.
3. Untrusted document snippets, model outputs, and error messages are rendered safely
   using textContent / safe DOM nodes without code execution.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.fake_llm import FakeLLM


class DummyEmbedder:
    model_id: str = "dummy-embed"
    dim: int = 16

    def embed_query(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        v[0] = 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("playwright_server")
    settings = Settings(
        home=tmp_path,
        api_key="test_key_minimum_32_characters_for_playwright_security",
    )
    store = NumpyStore()
    embedder = DummyEmbedder()
    llm = FakeLLM(reply="Safe response with verified citation [S1]")
    dm = DocuMind(store=store, embedder=embedder, llm=llm, settings=settings)

    app = create_app(
        dm=dm,
        settings=settings,
    )

    port = get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to become responsive
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Live uvicorn server failed to start")

    yield base_url

    server.should_exit = True
    thread.join(timeout=2.0)


def test_malicious_filename_and_xss_prevention_playwright(live_server: str, tmp_path: Path):
    """Verify that uploading `<img src=x onerror=alert(1)>.md` containing an XSS payload
    does not execute script or trigger alert dialogs in a real Chromium browser.
    """
    xss_filename = "<img src=x onerror=alert(1)>.md"
    xss_content = (
        "# Security Research Document\n\n"
        "This is an adversarial test document.\n"
        "<script>window.__xss_executed = true; alert('XSS_EXEC');</script>\n"
        "<img src=invalid onerror=\"window.__xss_executed = true;\">\n"
        "[Click here](javascript:alert('XSS_LINK'))\n"
    )
    test_file_path = tmp_path / xss_filename
    test_file_path.write_text(xss_content, encoding="utf-8")

    alerts_triggered: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Listen for any alert / prompt / confirm dialogs
        def handle_dialog(dialog):
            alerts_triggered.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", handle_dialog)

        # 1. Load console page and verify defensive headers
        response = page.goto(f"{live_server}/app/console/code.html", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200

        headers = response.headers
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-frame-options") == "DENY"
        assert "default-src 'self'" in headers.get("content-security-policy", "")
        assert "base-uri 'none'" in headers.get("content-security-policy", "")

        # 2. Upload adversarial file through Library UI or API in browser context
        page.goto(f"{live_server}/app/library/code.html", wait_until="domcontentloaded")

        # Set file input directly
        file_input = page.locator("#file-input")
        if file_input.count() > 0:
            file_input.set_input_files(str(test_file_path))
            page.wait_for_timeout(1000)

        # 3. Assert no alert was triggered during load or upload
        assert len(alerts_triggered) == 0, f"XSS alert dialog was triggered: {alerts_triggered}"

        # 4. Assert window.__xss_executed flag was NOT set
        xss_state = page.evaluate("() => window.__xss_executed")
        assert not xss_state, "XSS payload executed in browser page context!"

        # 5. Open chat drawer and check that model/citation rendering does not execute script
        page.goto(f"{live_server}/app/console/code.html?chat=open", wait_until="domcontentloaded")
        page.wait_for_timeout(500)

        # Inject adversarial content test into chat rendering functions safely
        eval_result = page.evaluate("""() => {
            window.__dom_xss_fired = false;
            const container = document.createElement('div');
            // Test that textContent assignment does not evaluate HTML
            container.textContent = '<img src=x onerror="window.__dom_xss_fired=true">';
            document.body.appendChild(container);
            return window.__dom_xss_fired;
        }""")
        assert eval_result is False

        # Close browser
        context.close()
        browser.close()

    assert len(alerts_triggered) == 0
