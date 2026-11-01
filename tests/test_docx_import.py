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
  postMessage: result => { process.stdout.write(JSON.stringify(result)); },
  TextDecoder, DataView, Uint8Array, ArrayBuffer, Promise,
  DecompressionStream, setTimeout, clearTimeout, Blob, Set
};
sandbox.self = sandbox;
const context = vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('./public/docx-import-worker.js', 'utf8'), context);
sandbox.onmessage({ data: { buffer } });
"""

# Exercise the actual browser extraction function in a Window-like VM without
# relying on network-loaded DOM libraries. The fake XML tree deliberately
# throws on `.textContent` and descendant searches, catching quadratic work.
NODE_XML_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const scenario = process.argv[1];
const script = fs.readFileSync('./public/app.js', 'utf8');
const begin = script.indexOf('function extractDocxText(xml) {');
const end = script.indexOf('\nfileInput.addEventListener("change"', begin);
if (begin < 0 || end < 0) throw new Error('DOCX extractor not found');
const WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
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
} else if (scenario === 'wrong_namespace') {
  elements.push(node('p'));
  elements.push(node('t', [textNode('spoof')], 'urn:wrong-namespace'));
} else {
  throw new Error('unknown test scenario');
}
const body = node('body');
const root = node('document');
root.getElementsByTagNameNS = () => [body];
const parsed = {
  documentElement: root,
  getElementsByTagName: () => [],
  createTreeWalker: () => {
    let index = 0;
    return { nextNode: () => elements[index++] || null };
  }
};
const sandbox = {
  DOMParser: class { parseFromString() { return parsed; } },
  NodeFilter: { SHOW_ELEMENT: 1 }
};
try {
  const text = vm.runInNewContext('const MAX_MANUSCRIPT_CHARS = 12000;\n' +
    script.slice(begin, end) + '\nextractDocxText(' + JSON.stringify(rawXml) + ');', sandbox);
  process.stdout.write(JSON.stringify({ ok: true, text }));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message }));
}
"""


def make_docx(text: str, *, duplicate_document: bool = False) -> bytes:
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
        '<w:body><w:p><w:r><w:t>' + escape(text) +
        '</w:t></w:r></w:p></w:body></w:document>'
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", contents)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", doc)
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
            timeout=10,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr.decode("utf-8", "replace"))
        return json.loads(outcome.stdout.decode("utf-8"))

    def test_real_docx_streams_verified_document_xml(self):
        result = self._run(make_docx("A lantern, a threshold, and a choice."))
        self.assertTrue(result["ok"], result)
        root = ElementTree.fromstring(result["xml"])
        runs = root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        self.assertEqual([run.text for run in runs], ["A lantern, a threshold, and a choice."])

    def test_legacy_doc_binary_is_not_mislabeled_as_docx(self):
        result = self._run(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy word binary")
        self.assertFalse(result["ok"], result)

    def test_compressed_docx_bomb_is_rejected_before_extraction(self):
        # The archive is tiny, but its XML would inflate beyond the 4 MiB
        # per-entry limit. The worker rejects its directory metadata first.
        result = self._run(make_docx("A" * (5 * 1024 * 1024)))
        self.assertFalse(result["ok"], result)
        self.assertTrue("oversized ZIP entry" in result["error"] or
                        "XML exceeds safe limits" in result["error"], result)

    def test_duplicate_docx_zip_names_are_rejected_before_parser(self):
        result = self._run(make_docx("one paragraph", duplicate_document=True))
        self.assertFalse(result["ok"], result)
        self.assertIn("duplicate ZIP entry", result["error"])

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
            cwd=ROOT, capture_output=True, check=False, timeout=10,
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

    def test_window_xml_extractor_rejects_oversize_and_complex_documents(self):
        for scenario, expected in (
            ("oversized_text", "12,000 characters"),
            ("too_many_nodes", "too many XML elements"),
            ("entity", "cannot safely parse"),
            ("embedded_body", "unsupported embedded body"),
            ("wrong_namespace", "no usable body text"),
        ):
            with self.subTest(scenario=scenario):
                result = self._run_browser_xml(scenario)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["error"])


if __name__ == "__main__":
    unittest.main()
