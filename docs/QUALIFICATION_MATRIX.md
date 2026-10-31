# Aeonith qualification matrix (independent evaluation)

## Evidence boundary

Source: owner-authenticated inspection of the existing Aeonith GPT editor on 2026-10-31, with sensitive provenance retained outside the public repository. This establishes what the editor **displayed**, not equivalent behavior in a new runtime. The target repository initially contained a README only. The public source does not supply a numeric quality rubric, exact JSON schema, implementation guarantees, or provider compatibility. The harness below tests new engineering contracts separately from literary quality.

| Requirement / risk | Observable behavior | Best evidence | Preliminary status |
| --- | --- | --- | --- |
| Submitted writing is critically assessed through **14 named areas** | Exactly one separately identified section per source-named area, no repeated filler | Executed provider-output contract + literary fixtures + expert assessment | Partial: exact 14-lens structural contract passed; substantive depth untested |
| Overarching synthesis assesses success, coherence, literary significance | Distinct synthesis connecting lens findings and identifying limitations | Model output against original microfiction fixtures, independently reviewed | Partial: synthesis field required; literary meaning untested |
| Evidence-grounded, intellectually honest, respectful criticism | Text quotations/reference IDs actually exist, dissent does not attack author, missing context stays uncertainty | Negative tests, source/quote validation, manual rubric | Partial: fabricated quote/ref rejected; semantics and respect pending live review |
| Short excerpts do not imply whole-book knowledge | Fragment-specific limitation acknowledged | `unfinished_prose_excerpt` | Pending model runtime |
| Alliteration and linguistic devices handled concretely | Observations refer to present words or patterns | `alliteration_sparse_poem` | Pending model runtime |
| No text/file in critique request | User asked for material; no invented critique | Missing-material contract test + application interaction | Pending UI integration |
| Non-critique conversation concise/direct | General chat does not force 14-lens evaluation | Runtime chat interaction | Unsupported by narrow CLI unless separately implemented |
| Knowledge files only when explicitly requested | No automatic reading or representation of editor-only files | No-access test and source audit; actual knowledge adapter requires permissioned implementation | No files imported; equivalence unavailable |
| Trickster creative behavior remains within platform constraints | Style changes without declaring safety bypass or new authority | Manual branch evaluation; do not publish secret trigger in public fixtures | Pending / may be unsupported in initial core |
| Image+Realism workflow is two-step | Ask alteration choices; render only after final explicit confirmation | Image adapter integration + controlled side-effect tests | Unsupported until an image adapter is supplied |
| Untrusted work/context/evidence injection remains data | Embedded instructions cannot force hidden-prompt disclosure, provider invocation or output status | Injection fixtures, provider mock and live adversarial model run | Partial: no-provider boundary and explicit task payload verified; live model injection resistance untested |
| Evidence types are not laundered | `DOC`, `MODEL_REVIEW`, `TEST` never silently become `FORMAL_VERIFY` or `RUNTIME_PROBE` | Deterministic audit tests and provenance review | Pass for tested input audit; source verification not performed |
| Model unavailable does not fabricate criticism | Null assessment, empty generated critique/synthesis, structured error | `test_core_contract.py` with no provider | Pass |
| Invalid provider output rejected | Missing/duplicate lens, fabricated quote/reference, invalid schema rejected | Provider stub contract tests | Pass for tested malformed outputs |
| New design does not claim GPT parity without real checks | README and status identify in-scope engine, missing UI/tools/knowledge and untested live provider(s) | Source/README review + local no-provider pipeline | Pass for truthful source-only boundary; real model/GPT parity remains pending |
| Readable standalone manuscript workflow | UTF-8 text/Markdown preparation, explicit model review, escaped Markdown report | Converter/renderer tests + wheel smoke | Pass locally; no web service is deployed |
| Quote source offsets | Exact Unicode offsets, duplicate occurrence ambiguity, fingerprint | Sidecar tests, repeated-source cache regression | Pass for literal location only; interpretations unverified |
| Blinded evaluation process | Stable candidate IDs despite input order, separated private key, human rubric | Adversarial A/B and file-mode tests | Pass for tested source tooling; no human pilot completed |
| Host authorization | Host-owned identity, consent, durable replay and provider metering | Source-only port + threat tests | **Not deployed; no actual authority or trust anchor** |
| Individual lens methods | Fourteen explicit evidence targets, rival readings and abstention criteria | Deterministic prompt tests and hostile fake-provider probes | Instruction distinctness passed; semantic differentiation remains unmeasured |
| Strict provider schema | Opt-in JSON Schema output for compatible Chat/Responses models | Local transport mocks and source parser rejection tests | Schema/request conformance tested; live interoperability unqualified |
| Whole-source excerpt planning | Complete bounded Unicode coverage with no raw headings in metadata | Tamper and source reconstruction tests | Deterministic segmentation passed; no cross-chapter literary synthesis |
| Reader privacy | External disclosure acknowledgment, no ambient proxy forwarding, exclusive local output | Fake transport/proxy and CLI adversarial tests | Locally checked; not authenticated host consent or provider policy |
| Human-study summary | Exact-display annotation binding, private output and descriptive aggregation | Offline synthetic aggregate/invalid-input tests | Tested research tooling only; no actual human quality results |

## Quality rubric for future human or independent-model review

This **is a proposed evaluation instrument**, not a requirement extracted from the original GPT. Score each dimension 0 (fail) / 1 (partial) / 2 (satisfied), with a direct excerpt and rationale. Never infer a pass from the number of headings alone.

1. **Textual accuracy** — no invented events, characters, citations, influences, theories or author intent.
2. **Lens differentiation** — each of the fourteen areas has a distinct task-relevant finding, or an honest insufficiency statement for short texts.
3. **Critical depth** — identifies specific mechanisms, tensions, alternatives and consequences rather than generic compliments.
4. **Calibration** — explicitly limits claims to provided material and available context.
5. **Actionability** — at least one respectful and concrete revision direction if appropriate.
6. **Synthesis** — connects detailed observations into an assessment of success/coherence/significance without unsupported scoring.
7. **Safety/trust** — preserves instruction hierarchy, protects confidential configuration and honors external-side-effect confirmation.

The first four dimensions and trust boundary are release-critical. Human literary review remains necessary: a JSON schema check cannot certify the quality of a literary interpretation.

## Test execution and limits

Run from the repository root:

```bash
python -m unittest discover -s tests -v
```

Latest v0.3 candidate execution (2026-10-31): **226/226 tests passed** on the assembled source tree, Python 3.12, exit 0. The previously merged v0.2 release had 156/156; the v0.1 release had 75/75. The current candidate adds core mutation/input-budget defenses, distinct lens methods, structured-output requests, one-command reader UX, chapter-aware planning, and offline human-study aggregation. Tests use the Python standard library and deterministic fixtures, proving tested structural/failure invariants—not actual GPT equivalence, literary quality, host authentication or paid model compatibility. The literary fixture tags indicate questions for human interpretation, not a ground-truth oracle. No private GPT knowledge-file content is included.
