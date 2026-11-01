"""Source-level checks for the dependency-free Aeonith browser interface.

These checks complement, but do not replace, a deployed browser smoke test.
"""

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

from aeonith.core import CANONICAL_LENSES


ROOT = Path(__file__).resolve().parents[1] / "public"


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []
        self.textareas = []
        self.ids = set()
        self.forms = 0
        self.form_attrs = []
        self.scripts = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "form":
            self.forms += 1
            self.form_attrs.append(attrs)
        if tag == "input":
            self.inputs.append(attrs)
        if tag == "textarea":
            self.textareas.append(attrs)
        if tag == "script":
            self.scripts.append(attrs.get("src", ""))
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs.get("href", ""))


class BrowserContractTests(unittest.TestCase):
    def test_accessible_controls_and_all_canonical_lenses(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        doc = _FormParser()
        doc.feed(markup)
        self.assertEqual(doc.forms, 1)
        # If the JS fails to load, never submit manuscript/token as GET URL query.
        self.assertEqual(doc.form_attrs[0].get("method"), "post")
        self.assertEqual(doc.form_attrs[0].get("action"), "/api/review")
        self.assertEqual(doc.textareas[0].get("spellcheck"), "false")
        self.assertNotIn("maxlength", doc.textareas[0])  # Never silently truncate a pasted manuscript.
        self.assertTrue({"manuscript", "work-title", "service-token", "disclosure", "results", "status", "runtime-status"}.issubset(doc.ids))
        lens_inputs = [input_ for input_ in doc.inputs if input_.get("name") == "lenses"]
        self.assertEqual({input_["value"] for input_ in lens_inputs}, set(CANONICAL_LENSES))
        self.assertEqual(len(lens_inputs), len(CANONICAL_LENSES))
        self.assertEqual({entry["value"] for entry in lens_inputs if "checked" in entry},
                         {"symbolic"})
        self.assertTrue(any(input_.get("type") == "password" and input_.get("id") == "service-token" for input_ in doc.inputs))
        self.assertTrue(any(input_.get("type") == "file" and input_.get("id") == "manuscript-file"
                            and "name" not in input_ for input_ in doc.inputs))
        self.assertTrue({"manuscript-file", "import-status", "import-hint"}.issubset(doc.ids))
        self.assertTrue(any(input_.get("type") == "checkbox" and input_.get("id") == "disclosure" for input_ in doc.inputs))
        self.assertEqual(doc.scripts, ["/app.js"])
        self.assertEqual(doc.stylesheets, ["/styles.css"])

    def test_client_discloses_and_never_stores_or_interprets_model_html(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('"/api/review"', script)
        self.assertNotIn("X-Aeonith-Disclosure", script)
        self.assertNotIn("X-Aeonith-Request-Id", script)
        self.assertNotIn("crypto.randomUUID", script)
        self.assertIn('titleInput.addEventListener("input"', script)
        self.assertIn("consentInput.checked = false", script)
        self.assertIn("Authorization", script)
        self.assertIn("MAX_MANUSCRIPT_CHARS = 12000", script)
        self.assertIn("MAX_LENSES = 14", script)
        self.assertIn("lenses.length > MAX_LENSES", script)
        self.assertNotIn("durable admission", script)
        self.assertNotIn("409:", script)
        self.assertNotIn("429:", script)
        self.assertIn("503:", script)
        self.assertIn("no paid inference API", markup)
        self.assertIn("local model", markup)
        self.assertNotIn("external language-model provider", markup)
        self.assertNotIn("pilot", markup.lower())
        self.assertNotIn("Vercel", markup)
        self.assertIn("textContent", script)
        self.assertNotRegex(script, r"\b(?:localStorage|sessionStorage|indexedDB|document\.cookie|innerHTML|outerHTML|eval)\b")
        self.assertNotRegex(script, r"Math\.random\s*\(")
        self.assertNotRegex(script, r"https?://")
        self.assertNotIn("document.write", script)

    def test_uncredentialed_health_probe_does_not_claim_inference_success(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/healthz"', script)
        self.assertIn('method: "GET"', script)
        self.assertIn("status.review_configured === true", script)
        self.assertIn("A successful review is not guaranteed", script)
        self.assertIn("Local model disabled or unconfigured", script)
        self.assertIn("cache: \"no-store\"", script)
        self.assertIn("redirect: \"error\"", script)

    def test_local_text_import_is_bounded_and_cannot_upload_binary_files(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('accept=".txt,.text,.md,.markdown,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"', markup)
        self.assertIn("TXT/Markdown", markup)
        self.assertIn("Legacy .doc and PDF", markup)
        self.assertIn('fileInput.addEventListener("change"', script)
        self.assertIn("MAX_IMPORT_BYTES = 65536", script)
        self.assertIn("MAX_DOCX_BYTES = 2 * 1024 * 1024", script)
        self.assertIn("DOCX_PARSE_TIMEOUT_MS = 8000", script)
        self.assertIn('new Worker("/docx-import-worker.js")', script)
        self.assertIn("worker.terminate()", script)
        self.assertIn('new TextDecoder("utf-8", { fatal: true })', script)
        self.assertIn("file.arrayBuffer()", script)
        self.assertIn("text.length > MAX_MANUSCRIPT_CHARS", script)
        self.assertIn("window.confirm", script)
        self.assertIn('manuscriptInput.dispatchEvent(new Event("input"', script)
        self.assertIn('fileInput.value = ""', script)
        self.assertNotIn("FormData", script)

    def test_docx_parser_is_native_and_resource_bounded(self):
        worker = (ROOT / "docx-import-worker.js").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('new DecompressionStream("deflate-raw")', worker)
        self.assertIn("MAX_ZIP_TOTAL_UNCOMPRESSED = 8 * 1024 * 1024", worker)
        self.assertIn("MAX_ZIP_ENTRY_UNCOMPRESSED = 4 * 1024 * 1024", worker)
        self.assertIn("MAX_DOCX_XML_BYTES = 2 * 1024 * 1024", worker)
        self.assertIn("crc32", worker)
        self.assertIn('name === "word/document.xml"', worker)
        self.assertIn("reader.read()", worker)
        self.assertIn('new DOMParser().parseFromString(xml, "application/xml")', script)
        self.assertIn("documentXml.createTreeWalker(body, NodeFilter.SHOW_ELEMENT)", script)
        self.assertIn("if (++visited > 50000)", script)
        self.assertIn("if (characters + value.length > MAX_MANUSCRIPT_CHARS)", script)
        self.assertNotIn("element.textContent", script)
        self.assertNotIn("importScripts(", worker)
        self.assertNotIn("fetch(", worker)
        self.assertNotIn("innerHTML", worker)
        packaging = (ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"public/docx-import-worker.js"', packaging)
        self.assertNotIn("mammoth", packaging.lower())
        self.assertFalse((ROOT / "mammoth.browser.min.js").exists())

    def test_tailscale_https_notice_is_host_gated_and_discloses_remote_processing(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertRegex(markup, r'<aside\s+id="funnel-privacy-note"[^>]*\bhidden\b')
        self.assertIn("Tailscale HTTPS", markup)
        self.assertIn("operator-issued bearer token", markup)
        self.assertIn("KoboldCpp", markup)
        self.assertIn("Ollama", markup)
        self.assertIn("One selected by default", markup)
        self.assertEqual(1, markup.count('name="lenses" value="symbolic" checked'))
        self.assertIn("browser storage", markup)
        self.assertIn("server or model may log", markup)
        self.assertIn('window.location.protocol === "https:"', script)
        self.assertIn('window.location.hostname.toLowerCase()', script)
        # Two labels must precede ts.net; arbitrary web origins never trigger it.
        self.assertIn(r'\.ts\.net$', script)
        self.assertIn('byId("funnel-privacy-note").hidden = false', script)
        self.assertIn(".funnel-notice", css)

    def test_local_assets_and_responsive_accessibility(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn("@media", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIsNone(re.search(r"@import|url\(\s*['\"]?https?://", css))


if __name__ == "__main__":
    unittest.main()
