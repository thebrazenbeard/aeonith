"use strict";

// Dependency-free, browser-local DOCX import. This worker never contacts a
// server or parses XML. It verifies a bounded ZIP directory, extracts only
// word/document.xml, and streams its decompression with a hard byte counter.
// The main thread parses the bounded XML with the browser's native DOMParser.

const MAX_DOCX_BYTES = 2 * 1024 * 1024;
const MAX_ZIP_ENTRIES = 1000;
const MAX_ZIP_ENTRY_UNCOMPRESSED = 4 * 1024 * 1024;
const MAX_ZIP_TOTAL_UNCOMPRESSED = 8 * 1024 * 1024;
const MAX_DOCX_XML_BYTES = 2 * 1024 * 1024;
const MAX_ZIP_RATIO = 200;

function inspectDocxZip(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 22 ||
      buffer.byteLength > MAX_DOCX_BYTES) {
    throw new Error("DOCX file size is outside the permitted limits.");
  }
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const earliest = Math.max(0, bytes.length - 22 - 65535);
  let eocd = -1;
  for (let offset = bytes.length - 22; offset >= earliest; offset--) {
    if (view.getUint32(offset, true) === 0x06054b50 &&
        offset + 22 + view.getUint16(offset + 20, true) === bytes.length) {
      eocd = offset;
      break;
    }
  }
  if (eocd < 0 || view.getUint16(eocd + 4, true) !== 0 ||
      view.getUint16(eocd + 6, true) !== 0) {
    throw new Error("Not a supported DOCX ZIP archive.");
  }
  const entriesOnDisk = view.getUint16(eocd + 8, true);
  const count = view.getUint16(eocd + 10, true);
  const directorySize = view.getUint32(eocd + 12, true);
  const directoryStart = view.getUint32(eocd + 16, true);
  if (!count || count !== entriesOnDisk || count > MAX_ZIP_ENTRIES ||
      count === 0xffff || directoryStart === 0xffffffff ||
      directorySize === 0xffffffff || directoryStart + directorySize > eocd) {
    throw new Error("DOCX archive structure exceeds safe limits.");
  }
  let offset = directoryStart;
  const end = directoryStart + directorySize;
  let total = 0;
  let documentEntry = null;
  let contentTypesFound = false;
  const seenNames = new Set();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  for (let index = 0; index < count; index++) {
    if (offset + 46 > end || view.getUint32(offset, true) !== 0x02014b50) {
      throw new Error("DOCX archive directory is malformed.");
    }
    const flags = view.getUint16(offset + 8, true);
    const compression = view.getUint16(offset + 10, true);
    const crc = view.getUint32(offset + 16, true);
    const compressed = view.getUint32(offset + 20, true);
    const uncompressed = view.getUint32(offset + 24, true);
    const nameSize = view.getUint16(offset + 28, true);
    const extraSize = view.getUint16(offset + 30, true);
    const commentSize = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const next = offset + 46 + nameSize + extraSize + commentSize;
    if (next > end || (flags & 1) !== 0 || (compression !== 0 && compression !== 8) ||
        compressed === 0xffffffff || uncompressed === 0xffffffff ||
        localOffset >= directoryStart ||
        uncompressed > MAX_ZIP_ENTRY_UNCOMPRESSED ||
        (uncompressed !== 0 && (compressed === 0 || uncompressed > compressed * MAX_ZIP_RATIO))) {
      throw new Error("DOCX archive contains an unsupported or oversized ZIP entry.");
    }
    const name = decoder.decode(bytes.subarray(offset + 46, offset + 46 + nameSize));
    if (!name || name.startsWith("/") || name.includes("\\") ||
        name.split("/").includes("..")) {
      throw new Error("DOCX archive contains an unsafe ZIP entry name.");
    }
    if (seenNames.has(name)) {
      throw new Error("DOCX archive contains duplicate ZIP entry names.");
    }
    seenNames.add(name);
    total += uncompressed;
    if (total > MAX_ZIP_TOTAL_UNCOMPRESSED) {
      throw new Error("DOCX archive would expand beyond safe limits.");
    }
    if (name === "word/document.xml") {
      if (!uncompressed || uncompressed > MAX_DOCX_XML_BYTES) {
        throw new Error("DOCX document XML exceeds safe limits.");
      }
      documentEntry = { compression, crc, compressed, uncompressed, localOffset, nameSize,
                        nameBytes: bytes.slice(offset + 46, offset + 46 + nameSize), flags };
    }
    if (name === "[Content_Types].xml") contentTypesFound = true;
    offset = next;
  }
  if (offset !== end || !documentEntry || !contentTypesFound) {
    throw new Error("The file is not a complete Word DOCX document.");
  }
  // Verify the local file header corresponds to the selected central entry;
  // a parser discrepancy must not lead us to another compressed member.
  const entry = documentEntry;
  const local = entry.localOffset;
  if (local + 30 > directoryStart || view.getUint32(local, true) !== 0x04034b50 ||
      view.getUint16(local + 6, true) !== entry.flags ||
      view.getUint16(local + 8, true) !== entry.compression ||
      view.getUint16(local + 26, true) !== entry.nameSize) {
    throw new Error("DOCX archive has conflicting ZIP headers.");
  }
  const dataStart = local + 30 + view.getUint16(local + 26, true) +
                    view.getUint16(local + 28, true);
  if (dataStart + entry.compressed > directoryStart) {
    throw new Error("DOCX compressed document is outside its ZIP member bounds.");
  }
  const localName = bytes.subarray(local + 30, local + 30 + entry.nameSize);
  for (let i = 0; i < localName.length; i++) {
    if (localName[i] !== entry.nameBytes[i]) {
      throw new Error("DOCX ZIP member names disagree.");
    }
  }
  return { ...entry, dataStart };
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function extractDocumentXml(buffer) {
  const entry = inspectDocxZip(buffer);
  const compressed = new Uint8Array(buffer, entry.dataStart, entry.compressed);
  let output;
  if (entry.compression === 0) {
    if (compressed.length !== entry.uncompressed) {
      throw new Error("DOCX stored document length is inconsistent.");
    }
    output = compressed.slice();
  } else {
    if (typeof DecompressionStream !== "function") {
      throw new Error("This browser cannot decompress Word DOCX files locally.");
    }
    const stream = new Blob([compressed]).stream()
      .pipeThrough(new DecompressionStream("deflate-raw"));
    const reader = stream.getReader();
    const parts = [];
    let length = 0;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        length += chunk.value.byteLength;
        if (length > entry.uncompressed || length > MAX_DOCX_XML_BYTES) {
          await reader.cancel();
          throw new Error("DOCX decompression exceeded its strict byte limit.");
        }
        parts.push(chunk.value);
      }
    } finally {
      reader.releaseLock();
    }
    if (length !== entry.uncompressed) {
      throw new Error("DOCX decompressed length disagrees with its ZIP header.");
    }
    output = new Uint8Array(length);
    let position = 0;
    for (const part of parts) {
      output.set(part, position);
      position += part.byteLength;
    }
  }
  if (crc32(output) !== entry.crc) {
    throw new Error("DOCX document XML failed its ZIP integrity check.");
  }
  const xml = new TextDecoder("utf-8", { fatal: true }).decode(output);
  if (/<!DOCTYPE|<!ENTITY/i.test(xml)) {
    throw new Error("DOCX documents with XML entities or document types are not supported.");
  }
  return xml;
}

self.onmessage = async (event) => {
  try {
    const xml = await extractDocumentXml(event.data && event.data.buffer);
    self.postMessage({ ok: true, xml });
  } catch (error) {
    self.postMessage({
      ok: false,
      error: error && typeof error.message === "string" && error.message.length <= 180 ?
        error.message : "The local DOCX parser could not read this document."
    });
  }
};
