"""Offline tests of the native browser DOCX worker with real ZIP/XML bytes.

Node emulates the Web Worker messaging boundary with DecompressionStream.
No third-party parser, network, or model access occurs.
"""

from __future__ import annotations

from io import BytesIO
import json
import shutil
import struct
import subprocess
import unittest
import warnings
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
NODE_WORKER_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const raw = fs.readFileSync(0);
const buffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
const sandbox = {
  // The browser terminates this Worker immediately after its one response.
  // Mirror that lifecycle in Node: flush the result synchronously, then exit,
  // instead of waiting for unrelated Node stream/VM handles to become idle.
  postMessage: result => { fs.writeSync(1, JSON.stringify(result)); process.exit(0); },
  TextDecoder, DataView, Uint8Array, ArrayBuffer, Promise,
  DecompressionStream, setTimeout, clearTimeout, Blob, Set
};
sandbox.self = sandbox;
const context = vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('./public/docx-import-worker.js', 'utf8'), context);
sandbox.onmessage({ data: { buffer } });
"""

# The ZIP-bomb fixture tests a synchronous *directory metadata* rejection.
# Invoke that exact production boundary without spawning the worker's async
# message/DecompressionStream lifecycle; doing so avoids intermittent Windows
# Node subprocess hangs unrelated to ZIP admission correctness.
NODE_ZIP_DIRECTORY_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const raw = fs.readFileSync(0);
const buffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
const context = vm.createContext({
  buffer, TextDecoder, DataView, Uint8Array, ArrayBuffer, Set, self: {}
});
vm.runInContext(fs.readFileSync('./public/docx-import-worker.js', 'utf8'), context);
let result;
try {
  vm.runInContext('inspectDocxZip(buffer)', context);
  result = { ok: true };
} catch (error) {
  result = { ok: false, error: error && error.message || String(error) };
}
fs.writeSync(1, JSON.stringify(result));
process.exit(0);
"""

# Exercise the actual browser extraction function in a Window-like VM without
# relying on network-loaded DOM libraries. The fake XML tree deliberately
# throws on `.textContent` and descendant searches, catching quadratic work.
NODE_XML_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const scenario = process.argv[1];
const script = fs.readFileSync('./public/app.js', 'utf8');
const begin = script.indexOf('function extractDocxText(xml, stylesXml = null) {');
const end = script.indexOf('\nfileInput.addEventListener("change"', begin);
if (begin < 0 || end < 0) throw new Error('DOCX extractor not found');
const WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const MC_NS = 'http://schemas.openxmlformats.org/markup-compatibility/2006';
function node(localName, childNodes = [], namespaceURI = WORD_NS) {
  return {
    localName, namespaceURI, childNodes,
    get textContent() { throw new Error('No unbounded subtree textContent reads'); },
    getElementsByTagName() { throw new Error('No descendant rescans'); }
  };
}
const textNode = value => ({ nodeType: 3, nodeValue: value });
const elements = [];
const pushText = value => elements.push(node('t', [textNode(value)]));
let rawXml = '<w:document/>';
let rawStyles = null;
const styleElements = [];
if (scenario === 'normal') {
  elements.push(node('p'));
  pushText('A <script>literal</script>');
  elements.push(node('p'));
  pushText('B');
  elements.push(node('tab'));
  pushText('C');
  elements.push(node('br'));
} else if (scenario === 'nested_paragraphs') {
  for (let i = 0; i < 9000; i++) elements.push(node('p'));
  pushText('safe');
} else if (scenario === 'nested_text') {
  elements.push(node('p'));
  elements.push(node('t', [node('t', [textNode('hidden')])]));
} else if (scenario === 'oversized_text') {
  elements.push(node('p'));
  pushText('A'.repeat(12001));
} else if (scenario === 'too_many_nodes') {
  for (let i = 0; i < 50001; i++) elements.push(node('r'));
} else if (scenario === 'entity') {
  rawXml = '<!DOCTYPE w:document [<!ENTITY e "payload">]><w:document/>';
} else if (scenario === 'embedded_body') {
  elements.push(node('altChunk'));
} else if (scenario === 'text_box') {
  elements.push(node('p'));
  elements.push(node('txbxContent'));
  elements.push(node('p'));
  pushText('Word text box, not a reliable paragraph stream');
} else if (scenario === 'drawing_without_media') {
  elements.push(node('p'));
  elements.push(node('drawing'));
  pushText('Text shape around drawing metadata');
} else if (scenario === 'field_instruction') {
  elements.push(node('p'));
  elements.push(node('fldSimple'));
  pushText('Word-generated field result, not literal prose');
} else if (scenario === 'numbering') {
  elements.push(node('p'));
  elements.push(node('numPr'));
  pushText('Numbering context omitted by browser');
} else if (scenario === 'visible_word_glyphs') {
  elements.push(node('p'));
  pushText('well');
  elements.push(node('noBreakHyphen'));
  pushText('being');
  elements.push(node('softHyphen'));
  pushText('today');
  elements.push(node('lastRenderedPageBreak'));
  pushText('tomorrow');
} else if (scenario === 'duplicate_body') {
  elements.push(node('p'));
  pushText('Only the first of two Word bodies is visible to this parser');
} else if (scenario === 'tracked_deletion') {
  elements.push(node('p'));
  pushText('retained text');
  elements.push(node('del'));
  elements.push(node('delText', [textNode('removed text')]));
} else if (scenario === 'tracked_insertion') {
  elements.push(node('p'));
  elements.push(node('ins'));
  pushText('not yet accepted');
} else if (scenario === 'moved_from') {
  elements.push(node('p'));
  elements.push(node('moveFrom'));
  pushText('obsolete location');
} else if (scenario === 'moved_range') {
  elements.push(node('p'));
  elements.push(node('moveFromRangeStart'));
  pushText('ambiguous location');
} else if (scenario === 'hidden_run') {
  elements.push(node('p'));
  elements.push(node('rPr'));
  elements.push(node('vanish'));
  pushText('hidden from readers');
} else if (scenario === 'web_hidden') {
  elements.push(node('p'));
  elements.push(node('webHidden'));
  pushText('hidden online');
} else if (scenario === 'styled_run') {
  elements.push(node('p'));
  elements.push(node('rPr'));
  elements.push(node('rStyle'));
  pushText('Potentially hidden by a named Word style');
} else if (scenario === 'styled_paragraph') {
  elements.push(node('p'));
  elements.push(node('pPr'));
  elements.push(node('pStyle'));
  pushText('Potentially hidden by a paragraph style');
} else if (scenario === 'default_style_hidden') {
  elements.push(node('p'));
  pushText('Hidden through a default Word style');
  rawStyles = '<w:styles><w:style w:default="1"><w:rPr><w:vanish/></w:rPr></w:style></w:styles>';
  styleElements.push(node('style'), node('rPr'), node('vanish'));
} else if (scenario === 'unused_style_hidden') {
  elements.push(node('p'));
  pushText('Unstyled passage with unsafe style definitions');
  rawStyles = '<w:styles><w:style><w:rPr><w:webHidden/></w:rPr></w:style></w:styles>';
  styleElements.push(node('style'), node('rPr'), node('webHidden'));
} else if (scenario === 'ordinary_styles') {
  elements.push(node('p'));
  pushText('Ordinary visible passage');
  rawStyles = '<w:styles><w:style><w:semiHidden/></w:style></w:styles>';
  styleElements.push(node('style'), node('semiHidden'));
} else if (scenario === 'mc_alternate') {
  const alternate = node('AlternateContent', [], MC_NS);
  const choice = node('Choice', [], MC_NS);
  const chosenParagraph = node('p');
  const chosenText = node('t', [textNode('Visible choice')]);
  const fallback = node('Fallback', [], MC_NS);
  const fallbackParagraph = node('p');
  const fallbackText = node('t', [textNode('Invisible fallback')]);
  choice.parentNode = alternate;
  chosenParagraph.parentNode = choice;
  chosenText.parentNode = chosenParagraph;
  fallback.parentNode = alternate;
  fallbackParagraph.parentNode = fallback;
  fallbackText.parentNode = fallbackParagraph;
  elements.push(alternate, choice, chosenParagraph, chosenText,
                fallback, fallbackParagraph, fallbackText);
} else if (scenario === 'foreign_wrapper') {
  const ignored = node('ignored', [], 'urn:ignored-by-word');
  const paragraph = node('p');
  const text = node('t', [textNode('Private ignored text')]);
  paragraph.parentNode = ignored;
  text.parentNode = paragraph;
  elements.push(ignored, paragraph, text);
} else if (scenario === 'wrong_namespace') {
  elements.push(node('p'));
  elements.push(node('t', [textNode('spoof')], 'urn:wrong-namespace'));
} else {
  throw new Error('unknown test scenario');
}
const body = node('body');
const root = node('document');
root.getElementsByTagNameNS = () => scenario === 'duplicate_body' ? [body, node('body')] : [body];
const parsed = {
  documentElement: root,
  getElementsByTagName: () => [],
  createTreeWalker: () => {
    let index = 0;
    return { nextNode: () => elements[index++] || null };
  }
};
const stylesRoot = node('styles');
const stylesDocument = {
  documentElement: stylesRoot,
  getElementsByTagName: () => [],
  createTreeWalker: () => {
    let index = 0;
    return { nextNode: () => styleElements[index++] || null };
  }
};
const sandbox = {
  DOMParser: class { parseFromString(input) { return input === rawStyles && rawStyles !== null ? stylesDocument : parsed; } },
  NodeFilter: { SHOW_ELEMENT: 1 }
};
try {
  const text = vm.runInNewContext('const MAX_MANUSCRIPT_CHARS = 12000;\n' +
    script.slice(begin, end) + '\nextractDocxText(' + JSON.stringify(rawXml) + ',' + JSON.stringify(rawStyles) + ');', sandbox);
  process.stdout.write(JSON.stringify({ ok: true, text }));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message }));
}
"""


def make_docx(text: str, *, duplicate_document: bool = False,
              raw_body: str | None = None,
              extra_parts: dict[str, bytes | str] | None = None) -> bytes:
    contents = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + (raw_body if raw_body is not None else
        '<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>') +
        '</w:body></w:document>'
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", contents)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", doc)
        for name, content in (extra_parts or {}).items():
            archive.writestr(name, content)
        if duplicate_document:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("word/document.xml", doc)
    return output.getvalue()


@unittest.skipUnless(shutil.which("node"), "Node is required to test the browser parser")
class BrowserDocxWorkerTests(unittest.TestCase):
    def _run(self, binary: bytes) -> dict:
        outcome = subprocess.run(
            ["node", "-e", NODE_WORKER_DRIVER],
            cwd=ROOT,
            input=binary,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr.decode("utf-8", "replace"))
        return json.loads(outcome.stdout.decode("utf-8"))

    def _inspect_directory(self, binary: bytes) -> dict:
        # This driver has no asynchronous worker lifecycle and exits
        # synchronously after its ZIP-directory assertion. Windows CI can
        # nevertheless delay Node process startup/stdio long enough for the
        # old 10-second harness timeout to flake; retain a bounded 30-second
        # subprocess cap without weakening the pre-decompression security test.
        outcome = subprocess.run(
            ["node", "-e", NODE_ZIP_DIRECTORY_DRIVER],
            cwd=ROOT, input=binary, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr.decode("utf-8", "replace"))
        return json.loads(outcome.stdout.decode("utf-8"))

    def test_real_docx_streams_verified_document_xml(self):
        result = self._run(make_docx("A lantern, a threshold, and a choice."))
        self.assertTrue(result["ok"], result)
        root = ElementTree.fromstring(result["xml"])
        runs = root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        self.assertEqual([run.text for run in runs], ["A lantern, a threshold, and a choice."])

    def test_worker_extracts_styles_xml_for_visibility_checks(self):
        styles = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/'
                  'wordprocessingml/2006/main"><w:docDefaults/></w:styles>')
        result = self._run(make_docx("Ordinary prose.", extra_parts={"word/styles.xml": styles}))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result.get("stylesXml"), styles)

    def test_worker_rejects_oversized_or_unverified_styles_xml(self):
        # Use moderately compressible bytes so ZIP ratio checks admit the
        # entry and the dedicated styles-byte cap is exercised directly.
        oversized_styles = "".join(f"{i:06d}" for i in range(350000))
        too_large = self._inspect_directory(make_docx(
            "Ordinary prose.", extra_parts={"word/styles.xml": oversized_styles}))
        self.assertFalse(too_large["ok"], too_large)
        self.assertIn("styles XML exceeds safe limits", too_large["error"])

        corrupted = bytearray(make_docx(
            "Ordinary prose.", extra_parts={"word/styles.xml": "<w:styles/>"}))
        # The final ZIP directory entry belongs to styles.xml. Corrupt its
        # central CRC while leaving the document's CRC valid.
        central = corrupted.rfind(b"PK\x01\x02")
        self.assertGreater(central, 0)
        struct.pack_into("<I", corrupted, central + 16, 0)
        result = self._run(bytes(corrupted))
        self.assertFalse(result["ok"], result)
        self.assertIn("ZIP integrity check", result["error"])

    def test_real_docx_revision_and_hidden_markup_survives_bounded_worker(self):
        # Real ZIP/XML fixtures establish that the worker does not suppress
        # revision markers; the Window extractor is responsible for rejection.
        cases = (
            ('<w:p><w:r><w:t>current</w:t></w:r>'
             '<w:del w:id="3"><w:r><w:delText>old</w:delText></w:r></w:del></w:p>', 'del'),
            ('<w:p><w:moveFrom w:id="2"><w:r><w:t>moved</w:t></w:r>'
             '</w:moveFrom></w:p>', 'moveFrom'),
            ('<w:p><w:r><w:rPr><w:vanish/></w:rPr>'
             '<w:t>hidden</w:t></w:r></w:p>', 'vanish'),
        )
        namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        for body, local_name in cases:
            with self.subTest(local_name=local_name):
                result = self._run(make_docx('', raw_body=body))
                self.assertTrue(result['ok'], result)
                root = ElementTree.fromstring(result['xml'])
                self.assertTrue(root.findall(f'.//{namespace}{local_name}'))

    def test_legacy_doc_binary_is_not_mislabeled_as_docx(self):
        result = self._run(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy word binary")
        self.assertFalse(result["ok"], result)

    def test_compressed_docx_bomb_is_rejected_before_extraction(self):
        # The archive is tiny, but its XML would inflate beyond the 4 MiB
        # per-entry limit. Call the real directory inspector directly, with
        # no decompression API available, to prove rejection *pre-extraction*.
        result = self._inspect_directory(make_docx("A" * (5 * 1024 * 1024)))
        self.assertFalse(result["ok"], result)
        self.assertTrue("oversized ZIP entry" in result["error"] or
                        "XML exceeds safe limits" in result["error"], result)

    def test_duplicate_docx_zip_names_are_rejected_before_parser(self):
        result = self._run(make_docx("one paragraph", duplicate_document=True))
        self.assertFalse(result["ok"], result)
        self.assertIn("duplicate ZIP entry", result["error"])

    def test_unrepresented_word_parts_are_rejected_before_document_extraction(self):
        # The original document XML can be valid while a footnote, header,
        # comment, picture, or embedded object carries meaningful content not
        # reflected in the extracted main-body prose. Never imply fidelity.
        for name in (
            "word/comments.xml", "word/footnotes.xml", "word/endnotes.xml",
            "word/header1.xml", "word/footer2.xml", "word/media/image1.png",
            "word/embeddings/oleObject1.bin", "word/activeX/activeX1.bin",
            "word/vbaProject.bin", "word/charts/chart1.xml",
        ):
            with self.subTest(name=name):
                archive = make_docx("Visible main-body paragraph.", extra_parts={name: b"other content"})
                result = self._inspect_directory(archive)
                self.assertFalse(result["ok"], result)
                self.assertIn("unsupported rich content", result["error"])

    def test_forged_zip_size_is_stopped_by_stream_byte_counter(self):
        binary = bytearray(make_docx("A" * 30000))
        central = binary.rfind(b"PK\x01\x02")
        self.assertGreater(central, 0)
        struct.pack_into("<I", binary, central + 24, 1024)
        result = self._run(bytes(binary))
        self.assertFalse(result["ok"], result)
        self.assertIn("strict byte limit", result["error"])

    def test_normal_docx_over_review_character_limit_is_not_truncated(self):
        result = self._run(make_docx("A" * 12001))
        self.assertTrue(result["ok"], result)
        # The browser's Window DOMParser stage checks the extracted text
        # length before writing anything into the manuscript editor.
        self.assertGreater(len(ElementTree.fromstring(result["xml"]).findall(
            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")[0].text), 12000)

    def test_worker_javascript_parses(self):
        outcome = subprocess.run(
            ["node", "--check", "public/docx-import-worker.js"],
            cwd=ROOT, capture_output=True, check=False, timeout=4,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr.decode("utf-8", "replace"))

    def _run_browser_xml(self, scenario: str) -> dict:
        outcome = subprocess.run(
            ["node", "-e", NODE_XML_DRIVER, scenario],
            cwd=ROOT, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr.decode("utf-8", "replace"))
        return json.loads(outcome.stdout.decode("utf-8"))

    def test_window_xml_extractor_preserves_plain_markup_and_paragraphs(self):
        result = self._run_browser_xml("normal")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], "A <script>literal</script>\n\nB\tC\n")

    def test_window_xml_extractor_handles_deeply_nested_paragraphs_linearly(self):
        result = self._run_browser_xml("nested_paragraphs")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], "safe")

    def test_window_xml_extractor_rejects_nested_text_markup(self):
        result = self._run_browser_xml("nested_text")
        self.assertFalse(result["ok"], result)
        self.assertIn("unsupported nested text markup", result["error"])

    def test_window_extractor_rejects_ambiguous_revision_and_hidden_text(self):
        for scenario in (
            'tracked_deletion', 'tracked_insertion', 'moved_from',
            'moved_range', 'hidden_run', 'web_hidden',
        ):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result['ok'], result)
                self.assertIn('tracked changes or hidden text', result['error'])

    def test_window_extractor_rejects_unrepresentable_word_body_semantics(self):
        # These main-body elements are unsafe without Word's display resolver
        # even if the ZIP contains no word/media/ or auxiliary rich part.
        for scenario in ('text_box', 'drawing_without_media',
                         'field_instruction', 'numbering'):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result['ok'], result)
                self.assertIn('cannot be imported faithfully', result['error'])

    def test_window_extractor_preserves_visible_word_glyphs_and_page_breaks(self):
        result = self._run_browser_xml('visible_word_glyphs')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['text'], 'well\u2011being\u00adtoday\ntomorrow')

    def test_window_extractor_rejects_multiple_document_bodies(self):
        result = self._run_browser_xml('duplicate_body')
        self.assertFalse(result['ok'], result)
        self.assertIn('readable body', result['error'])

    def test_window_extractor_rejects_word_ignored_alternates_and_wrappers(self):
        # Word's markup compatibility namespace can include multiple candidate
        # readings, only one of which is visible. The browser must never send
        # both alternatives or content under an ignored foreign wrapper.
        for scenario in ('mc_alternate', 'foreign_wrapper'):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result['ok'], result)
                self.assertIn('unrecognized markup around text', result['error'])

    def test_window_extractor_refuses_unresolved_named_text_styles(self):
        # The browser parser does not evaluate word/styles.xml, so it cannot
        # tell if an rStyle/pStyle reference makes content invisible in Word.
        for scenario in ('styled_run', 'styled_paragraph'):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result['ok'], result)
                self.assertIn('tracked changes or hidden text', result['error'])

    def test_window_extractor_checks_stylesheet_for_hidden_content(self):
        for scenario in ('default_style_hidden', 'unused_style_hidden'):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result['ok'], result)
                self.assertIn('hidden style', result['error'])
        ordinary = self._run_browser_xml('ordinary_styles')
        self.assertTrue(ordinary['ok'], ordinary)
        self.assertEqual(ordinary['text'], 'Ordinary visible passage')

    def test_window_xml_extractor_rejects_oversize_and_complex_documents(self):
        for scenario, expected in (
            ("oversized_text", "12,000 characters"),
            ("too_many_nodes", "too many XML elements"),
            ("entity", "cannot safely parse"),
            ("embedded_body", "unsupported embedded body"),
            ("wrong_namespace", "unrecognized markup around text"),
        ):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["error"])


if __name__ == "__main__":
    unittest.main()
