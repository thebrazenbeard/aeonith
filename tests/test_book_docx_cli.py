"""Adversarial, offline DOCX imports for the private long-form CLI."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from aeonith import book_cli
from aeonith.docx_source import DocxSourceError, read_docx_source


CONTENT_TYPES = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)


def document(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{body}</w:body></w:document>')


def paragraph(value: str) -> str:
    return f'<w:p><w:r><w:t>{value}</w:t></w:r></w:p>'


class DocxBookCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'manuscript.docx'
        self.output = self.root / 'review.json'

    def make_docx(self, body: str, extras=None, *, raw_doc=None):
        parts = {'[Content_Types].xml': CONTENT_TYPES,
                 'word/document.xml': raw_doc if raw_doc is not None else document(body)}
        parts.update(extras or {})
        with ZipFile(self.source, 'w', compression=ZIP_DEFLATED) as package:
            for name, value in parts.items():
                package.writestr(name, value)

    def invoke(self, *extra):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            result = book_cli.main(['--input', str(self.source), '--output', str(self.output),
                                    *extra])
        return result, stderr.getvalue(), stdout.getvalue()

    @unittest.skipIf(os.name == 'nt', 'Windows private output ACL custody is not qualified')
    def test_explicit_docx_prepares_full_content_without_network_or_console_prose(self):
        self.make_docx(paragraph('Canto I') + paragraph('A blue hour.') +
                       '<w:tbl><w:tr><w:tc>' + paragraph('In a table.') +
                       '</w:tc></w:tr></w:tbl>' + paragraph('Canto II') +
                       paragraph('At the end.'))
        code, stderr, stdout = self.invoke('--input-format', 'docx', '--max-segments', '5')
        self.assertEqual(code, 3, stderr)
        self.assertEqual(stdout, '')
        self.assertNotIn('blue hour', stderr)
        saved = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(saved['planned_segments'], 2)
        self.assertEqual(saved['completed_chars'], 0)
        self.assertEqual(saved['status'], 'provider_unavailable')
        self.assertNotIn('In a table.', self.output.read_text(encoding='utf-8'))

    def test_binary_input_is_not_implicitly_accepted(self):
        self.make_docx(paragraph('Do not guess the file format.'))
        code, stderr, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn('guess', stderr)

    def test_missing_word_part_fails_before_output(self):
        with ZipFile(self.source, 'w') as z:
            z.writestr('[Content_Types].xml', CONTENT_TYPES)
        code, stderr, _ = self.invoke('--input-format', 'docx')
        self.assertEqual(code, 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn('document.xml', stderr)

    def test_entity_declaration_tracked_changes_hidden_and_embeds_refused(self):
        bad = (
            ('<!DOCTYPE w:document [<!ENTITY x "BAD">]>' + document(paragraph('x'))),
            document('<w:ins>' + paragraph('new') + '</w:ins>'),
            document('<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden</w:t></w:r></w:p>'),
            document('<w:p><w:r><w:drawing/></w:r></w:p>'),
            document('<w:p><w:r><w:footnoteReference w:id="1"/></w:r></w:p>'),
        )
        for raw in bad:
            with self.subTest(raw=raw[:60]):
                self.make_docx('', raw_doc=raw)
                code, stderr, _ = self.invoke('--input-format', 'docx')
                self.assertEqual(code, 2, stderr)
                self.assertFalse(self.output.exists())
                self.assertNotIn('hidden', stderr)

    def test_refuses_unsupported_media_parts_and_duplicate_names(self):
        self.make_docx(paragraph('Present.'), extras={'word/media/photo.jpg': b'bytes'})
        self.assertEqual(self.invoke('--input-format', 'docx')[0], 2)
        self.assertFalse(self.output.exists())
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(self.source, 'w') as z:
                z.writestr('[Content_Types].xml', CONTENT_TYPES)
                z.writestr('word/document.xml', document(paragraph('first')))
                z.writestr('word/document.xml', document(paragraph('second')))
        self.assertEqual(self.invoke('--input-format', 'docx')[0], 2)
        self.assertFalse(self.output.exists())

    def test_gross_xml_expansion_refused(self):
        self.make_docx(paragraph('A' * (8_000_000 + 10)))
        self.assertEqual(self.invoke('--input-format', 'docx')[0], 2)
        self.assertFalse(self.output.exists())

    def test_invalid_raw_deflate_is_sanitized_before_output_reservation(self):
        self.make_docx(paragraph('A whole paragraph of private original writing.'))
        raw = bytearray(self.source.read_bytes())
        with ZipFile(self.source) as package:
            member = package.getinfo('word/document.xml')
        header = member.header_offset
        # ZIP local-file header: fixed 30 bytes, then filename and extra data.
        filename_len = int.from_bytes(raw[header + 26:header + 28], 'little')
        extra_len = int.from_bytes(raw[header + 28:header + 30], 'little')
        compressed_start = header + 30 + filename_len + extra_len
        self.assertEqual(member.compress_type, ZIP_DEFLATED)
        # Raw DEFLATE block's BTYPE=11 is reserved and must make zlib fail;
        # leave the central directory intact to exercise the read boundary.
        raw[compressed_start] = (raw[compressed_start] & ~0b110) | 0b110
        self.source.write_bytes(raw)
        with self.assertRaises(DocxSourceError):
            read_docx_source(str(self.source))
        code, stderr, stdout = self.invoke('--input-format', 'docx')
        self.assertEqual(code, 2)
        self.assertEqual(stdout, '')
        self.assertFalse(self.output.exists())
        self.assertNotIn('private original writing', stderr)
        self.assertNotIn('Traceback', stderr)

    def test_unaccounted_non_paragraph_text_markers_are_rejected(self):
        self.make_docx(paragraph('Visible.') + '<w:tab/>')
        code, stderr, _ = self.invoke('--input-format', 'docx')
        self.assertEqual(code, 2, stderr)
        self.assertFalse(self.output.exists())

    def test_markup_compatibility_ignored_content_cannot_be_sent_as_prose(self):
        raw = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:z="urn:ignored-by-word" mc:Ignorable="z">'
            '<w:body>' + paragraph('VISIBLE') +
            '<z:ignored>' + paragraph('NOTVISIBLE_PRIVATE_NOTE') +
            '</z:ignored></w:body></w:document>'
        )
        self.make_docx('', raw_doc=raw)
        with self.assertRaises(DocxSourceError):
            read_docx_source(str(self.source))
        code, stderr, stdout = self.invoke('--input-format', 'docx')
        self.assertEqual(code, 2)
        self.assertEqual(stdout, '')
        self.assertFalse(self.output.exists())
        self.assertNotIn('NOTVISIBLE_PRIVATE_NOTE', stderr)

    def test_markup_compatibility_declaration_without_hidden_content_is_allowed(self):
        raw = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            'xmlns:z="urn:ignored-by-word" mc:Ignorable="z">'
            '<w:body>' + paragraph('Ordinary visible text.') +
            '</w:body></w:document>'
        )
        self.make_docx('', raw_doc=raw)
        self.assertEqual(read_docx_source(str(self.source)), 'Ordinary visible text.')

    def test_hidden_styles_macro_and_zip_traversal_are_rejected(self):
        bad_extras = (
            {'word/styles.xml': ('<w:styles xmlns:w="http://schemas.openxmlformats.org/'
                                 'wordprocessingml/2006/main"><w:style><w:rPr>'
                                 '<w:vanish/></w:rPr></w:style></w:styles>')},
            {'word/vbaProject.bin': b'untrusted macro bytes'},
            {'word/../other.xml': 'not extracted'},
            {'word/header1.xml': document(paragraph('Secret header'))},
        )
        for extra in bad_extras:
            with self.subTest(extra=next(iter(extra))):
                self.make_docx(paragraph('body'), extra)
                code, stderr, _ = self.invoke('--input-format', 'docx')
                self.assertEqual(code, 2, stderr)
                self.assertFalse(self.output.exists())
                self.assertNotIn('Secret header', stderr)

    @unittest.skipIf(os.name == 'nt', 'Windows private output ACL custody is not qualified')
    def test_checkpoint_filtering_preserves_post_marker_docx_text_only(self):
        secret = 'PREVIOUS_AUTHOR_DRAFT_NEVER_SEND'
        self.make_docx(paragraph(secret + '[ps]') + paragraph('Canto I') +
                       paragraph('A garden opened.'))
        calls = []

        class LocalProvider:
            def __init__(self, **settings):
                self.timeout = settings['timeout']

            def review(self, payload):
                calls.append(payload)
                text = payload['task']['work']['text']
                return {
                    'lens_reviews': [{
                        'lens': 'symbolic', 'analysis': 'A limited interpretation.',
                        'basis': 'textual',
                        'support': [{'source': 'work', 'quote': text[:8]}],
                        'limitations': [],
                    }],
                    'synthesis': 'Excerpt only.', 'uncertainties': [],
                }

        with patch('aeonith.book_cli.LocalOpenAICompatibleProvider', LocalProvider):
            code, stderr, _ = self.invoke('--input-format', 'docx', '--after-marker', '[ps]',
                                          '--provider', 'local-openai-compatible')
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['task']['work']['text'], '\nCanto I\nA garden opened.')
        self.assertNotIn(secret, self.output.read_text(encoding='utf-8'))

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows private output ACL refusal')
    def test_windows_docx_prepares_without_writing_or_provider_call(self):
        self.make_docx(paragraph('Private synthetic text.'))
        code, stderr, stdout = self.invoke('--input-format', 'docx')
        self.assertEqual(code, 2)
        self.assertEqual(stdout, '')
        self.assertFalse(self.output.exists())
        self.assertNotIn('Private synthetic text.', stderr)


if __name__ == '__main__':
    unittest.main()
