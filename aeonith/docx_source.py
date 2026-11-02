"""Strict, local-only DOCX plain-text extraction for private excerpt planning.

The supported subset is deliberately conservative. Refuse features whose
rendered text cannot be recovered reliably; never imply OOXML-wide fidelity.
No archive members are extracted to disk and no relationships are fetched.
"""

from __future__ import annotations

import re
from pathlib import Path
import stat
import xml.etree.ElementTree as ET
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile


MAX_ARCHIVE_BYTES = 16_000_000
MAX_PART_BYTES = 32_000_000
MAX_TOTAL_EXPANDED_BYTES = 64_000_000
MAX_PARTS = 256
MAX_XML_MARKUP_TOKENS = 250_000
MAX_TEXT_CHARS = 2_000_000
MAX_TEXT_UTF8_BYTES = 8_000_000
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
MC_NS = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
MAIN_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'


def w(tag: str) -> str:
    return '{' + W_NS + '}' + tag


_UNSAFE_ELEMENT_NAMES = {
    # Edited/hidden text and display-dependent content are ambiguous.
    'ins', 'del', 'delText', 'moveFrom', 'moveTo', 'moveFromRangeStart',
    'moveFromRangeEnd', 'moveToRangeStart', 'moveToRangeEnd',
    'vanish', 'webHidden', 'specVanish', 'instrText', 'fldChar', 'fldSimple',
    # Content outside the main paragraph stream cannot be represented safely.
    'footnoteReference', 'endnoteReference', 'commentReference',
    'commentRangeStart', 'commentRangeEnd', 'annotationRef', 'headerReference',
    'footerReference', 'drawing', 'pict', 'object', 'altChunk',
    'subDoc', 'txbxContent', 'sym', 'numPr',
}
UNSAFE_TAGS = {w(name) for name in _UNSAFE_ELEMENT_NAMES} | {f'{{{MC_NS}}}AlternateContent'}
UNSAFE_MC_ATTRIBUTES = {
    f'{{{MC_NS}}}{name}' for name in
    ('ProcessContent', 'MustUnderstand', 'PreserveElements', 'PreserveAttributes')
}
_FORBIDDEN_PART = re.compile(
    r'^word/(?:media/|embeddings/|activeX/|charts/|diagrams/|'
    r'footnotes\.xml$|endnotes\.xml$|comments[^/]*\.xml$|'
    r'header[^/]*\.xml$|footer[^/]*\.xml$|vbaProject[^/]*$)',
    re.IGNORECASE,
)


class DocxSourceError(ValueError):
    """The DOCX is not in the safely extractable subset."""


def _xml(payload: bytes) -> ET.Element:
    # Permit only the XML encoding whose declaration can be inspected without
    # a second parser; UTF-16 could hide a DTD from the byte-level guard.
    if (b'\x00' in payload or payload.count(b'<') > MAX_XML_MARKUP_TOKENS
            or payload.startswith((b'\xff\xfe', b'\xfe\xff'))
            or b'<!doctype' in payload.lower() or b'<!entity' in payload.lower()):
        raise DocxSourceError('DOCX XML declarations are unsupported')
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DocxSourceError('DOCX XML is malformed') from exc


def _read_member(archive: ZipFile, name: str, limit: int) -> bytes:
    try:
        with archive.open(name, 'r') as stream:
            result = stream.read(limit + 1)
    except (BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError,
            zlib.error) as exc:
        raise DocxSourceError('DOCX archive member cannot be read') from exc
    if len(result) > limit:
        raise DocxSourceError('DOCX archive member exceeds resource limit')
    return result


def _check_archive(archive: ZipFile) -> None:
    entries = archive.infolist()
    if not 1 <= len(entries) <= MAX_PARTS:
        raise DocxSourceError('DOCX part count exceeds limit')
    seen: set[str] = set()
    expanded = 0
    for item in entries:
        name = item.filename
        segments = name.rstrip('/').split('/')
        if (not name or len(name) > 255 or name.startswith('/')
                or '\\' in name or ':' in name
                or any(s in ('', '.', '..') for s in segments)
                or '\x00' in name or item.flag_bits & 0x1
                or item.compress_type not in (ZIP_DEFLATED, ZIP_STORED)):
            raise DocxSourceError('DOCX archive contains unsupported parts')
        if item.is_dir():
            continue
        key = name.casefold()
        if key in seen:
            raise DocxSourceError('DOCX archive has ambiguous duplicate parts')
        seen.add(key)
        mode = (item.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise DocxSourceError('DOCX archive symlink entries are refused')
        if item.file_size > MAX_PART_BYTES or item.file_size < 0:
            raise DocxSourceError('DOCX part exceeds size limit')
        expanded += item.file_size
        if expanded > MAX_TOTAL_EXPANDED_BYTES:
            raise DocxSourceError('DOCX expanded payload exceeds limit')
        if _FORBIDDEN_PART.match(name):
            raise DocxSourceError('DOCX contains unsupported rich content')
    names = {item.filename for item in entries if not item.is_dir()}
    if not {'[Content_Types].xml', 'word/document.xml'} <= names:
        raise DocxSourceError('DOCX core parts are missing')


def read_docx_source(path: str) -> str:
    """Return bounded literal text from a narrowly supported .docx package.

    The resulting string is the *extracted* manuscript source; it is not a
    claim to have represented every possible Word rendering or annotation.
    """
    target = Path(path)
    if target.suffix.lower() != '.docx' or target.is_symlink():
        raise DocxSourceError('a named local .docx file is required')
    if hasattr(target, 'is_junction') and target.is_junction():
        raise DocxSourceError('DOCX junction paths are unsupported')
    if not target.is_file() or target.stat().st_size > MAX_ARCHIVE_BYTES:
        raise DocxSourceError('DOCX archive is unavailable or too large')
    try:
        with ZipFile(target, 'r') as archive:
            _check_archive(archive)
            types = _xml(_read_member(archive, '[Content_Types].xml', 1_000_000))
            if types.tag != '{' + CT_NS + '}Types':
                raise DocxSourceError('DOCX content types are malformed')
            if not any(
                e.tag == '{' + CT_NS + '}Override'
                and e.attrib.get('PartName') == '/word/document.xml'
                and e.attrib.get('ContentType') == MAIN_MIME
                for e in types
            ):
                raise DocxSourceError('DOCX main document is not standard text')
            if 'word/styles.xml' in archive.namelist():
                styles = _xml(_read_member(archive, 'word/styles.xml', MAX_PART_BYTES))
                if any(e.tag in {w('vanish'), w('webHidden'), w('specVanish')}
                       for e in styles.iter()):
                    raise DocxSourceError('DOCX contains hidden text styles')
            root = _xml(_read_member(archive, 'word/document.xml', MAX_PART_BYTES))
    except (BadZipFile, EOFError, RuntimeError, NotImplementedError) as exc:
        raise DocxSourceError('DOCX is not a supported ZIP document') from exc
    if root.tag != w('document'):
        raise DocxSourceError('DOCX main element is invalid')
    if any(any(key in UNSAFE_MC_ATTRIBUTES for key in node.attrib)
           for node in root.iter()):
        raise DocxSourceError('DOCX markup-compatibility handling is unsupported')
    bodies = root.findall(w('body'))
    if len(bodies) != 1:
        raise DocxSourceError('DOCX body is missing or ambiguous')
    body = bodies[0]
    if any(node.tag in UNSAFE_TAGS or (
        node.tag.startswith('{' + W_NS + '}') and node.tag.endswith('Change')
    ) for node in body.iter()):
        raise DocxSourceError('DOCX contains content that cannot be extracted faithfully')

    # ElementTree does not implement OOXML's Markup Compatibility rules. An
    # mc:Ignorable namespace wrapper may carry a w:p / w:t descendant that
    # Word intentionally discards; blindly iterating every w:p would then
    # send invisible prose to the model. Refuse foreign-namespace wrappers
    # containing paragraph/text markers while allowing harmless w14/w15
    # metadata elements and a bare root mc:Ignorable declaration.
    semantic_tags = {w('p'), w('t'), w('tab'), w('br'), w('cr'),
                     w('noBreakHyphen'), w('softHyphen'), w('lastRenderedPageBreak')}
    for node in body.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag.startswith('{' + W_NS + '}'):
            continue
        if (node.text and node.text.strip()) or any(
            child.tag in semantic_tags for child in node.iter()
        ):
            raise DocxSourceError('DOCX contains unrecognized markup around text')

    # Preserve visible runs, tabs and line breaks in document order, including
    # paragraphs inside table cells. Formatting and table topology are lost.
    paragraphs: list[str] = []
    text_tags = {w('t'), w('tab'), w('br'), w('cr'), w('noBreakHyphen'),
                 w('softHyphen'), w('lastRenderedPageBreak')}
    seen_text_nodes = 0
    for p in body.iter(w('p')):
        parts = []
        for node in p.iter():
            if node.tag in text_tags:
                seen_text_nodes += 1
            if node.tag == w('t'):
                parts.append(node.text or '')
            elif node.tag == w('tab'):
                parts.append('\t')
            elif node.tag in (w('br'), w('cr'), w('lastRenderedPageBreak')):
                parts.append('\n')
            elif node.tag == w('noBreakHyphen'):
                parts.append('\u2011')
            elif node.tag == w('softHyphen'):
                parts.append('\u00ad')
        paragraphs.append(''.join(parts))
    if seen_text_nodes != sum(node.tag in text_tags for node in body.iter()):
        raise DocxSourceError('DOCX contains unaccounted text')
    result = '\n'.join(paragraphs)
    if (not result.strip() or '\x00' in result or len(result) > MAX_TEXT_CHARS):
        raise DocxSourceError('DOCX text is empty or too large')
    try:
        if len(result.encode('utf-8')) > MAX_TEXT_UTF8_BYTES:
            raise DocxSourceError('DOCX UTF-8 text exceeds limit')
    except UnicodeError as exc:
        raise DocxSourceError('DOCX contains invalid Unicode') from exc
    return result
