# Legacy Word `.doc` import: qualified boundary and offline alternatives

**Status (2026-11-02): NO automatic `.doc` importer is qualified.** This is a
source and read-only host investigation, not a new parser, plugin, installation
or tested conversion service. Aeonith's private `aeonith-book` CLI accepts
UTF-8 and an explicitly selected, conservative `.docx` subset. Its browser
editor similarly has no binary `.doc` parser. Never rename a `.doc` file to
`.docx`: they are different formats.

## Why conversion cannot silently become a trusted import

A legacy Word `.doc` is a binary compound file. It may contain macros, linked
content, embedded objects, footnotes, tracked revisions and material outside
the straightforward main-text stream. Converting it to text can **omit writing
that would affect a critique**. Aeonith currently requires accounted-for
source text; merely receiving a readable `.txt` does not prove that every
relevant element of the original Word document was preserved.

[LibreOffice's official command-line reference](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html)
documents `--headless`, `--convert-to`, UTF-8 text export filters, `--outdir`
and a separate user-profile bootstrap setting. These are conversion features,
not a sandbox specification. Its [macro-security settings](https://help.libreoffice.org/latest/en-US/text/shared/optionen/macrosecurity_sl.html)
still permit trusted macros even at the most restrictive documented level;
the [publisher's security advisories](https://www.libreoffice.org/security/)
document real risks from document processing and external links. No
version-matched, cross-platform guarantee of no macro execution, no network
access, no filesystem side effects and faithful extraction was established.

`antiword` is another long-standing text-extraction candidate, but its
installation and safe binary/input/output contract were **not** qualified
here. Its absence does not establish that it is unsafe; it means Aeonith
cannot depend on it without an explicit future qualification.

## Read-only machine inventory

| Environment | `antiword` | LibreOffice | Evidence limit |
| --- | --- | --- | --- |
| VN1 (Windows) | Not found on PATH | Not found on PATH or two conventional Program Files paths | Does not rule out an unusual installation |
| VN2 (Linux) | Not found on PATH | `libreoffice-core` and `libreoffice-writer` package version `4:24.2.7-0ubuntu0.24.04.7` | Presence only; no conversion executed |
| Scratch execution runtime | Not found | Bundled `soffice` wrapper present | Not a declared Aeonith dependency or evidence of availability on a user's PC |

The inventory commands only searched for executables or read installed-package
metadata. No manuscript, test `.doc`, existing application session, model or
service was accessed or changed. A distribution package version is not a
security qualification for untrusted document conversion.

## Practical $0 path for a document you own and trust

1. Use an existing local Word-compatible editor, such as LibreOffice Writer
   **if you already have it**. No cloud conversion account is needed.
2. For documents of uncertain origin, do **not** assume opening them in an
   ordinary, network-connected desktop session is safe. Work with an
   independently isolated environment and verify the editor's macro, linked
   resource and security settings. This repository does not supply or certify
   such isolation.
3. Export a **separate** UTF-8 plain-text copy (preferred) or a new `.docx`;
   keep the original `.doc` untouched. Do not overwrite it.
4. Manually compare the exported text with the original for missing chapters,
   paragraph order, tables, headings, page headers/footers, footnotes,
   comments, tracked changes, text boxes and embedded material. Restore or
   separately annotate anything materially omitted. A loss report is as
   important as a successful export.
5. Feed only the reviewed local UTF-8 file to `aeonith-book`. A DOCX export
   may still be rejected by the strict DOCX importer; that rejection is not a
   reason to loosen its integrity checks. Do not upload the original document
   to public repositories, conversion websites, or AI provider endpoints.

## Gates before an optional local `.doc` adapter could be enabled

- **Explicit opt-in:** reject `.doc` by default; no magic file-type fallback
  or unannounced conversion process.
- **Verified executable:** user-selected, pinned local converter identity,
  version, provenance and allowed platform. No implicit installation or paid
  services.
- **Real process isolation:** isolated non-privileged process/user, no external
  network, bounded CPU/RAM/time, read-only input, separate private scratch,
  constrained writes and reliable process-tree cleanup. A Python subprocess
  timeout alone is **not** a cross-platform sandbox.
- **Content fidelity:** reject encrypted/ambiguous files, macros and linked
  resources, or prove they cannot activate; validate extraction against
  distinct visible-content sources and report unsupported/omitted elements
  rather than silently treating plain text as full coverage.
- **Privacy:** no manuscript, conversion output or credentials in stdout,
  logs, temporary shared directories, Git, browser storage or a paid cloud.
  Reuse qualified private-output custody; on Windows that writer currently
  **fails closed** pending an owner/DACL/reparse traversal qualification.
- **Adversarial Windows and Linux tests:** corrupted compound-file chains,
  large/decompression inputs, macros, links, embedded content, races, profile
  takeover, crashes, cleanup and output-fidelity counterexamples, plus
  exact-head readback on the intended host.

Until these pass, **automatic `.doc` conversion remains UNKNOWN**, not
supported. A manual reviewed export is the usable alternative today.
