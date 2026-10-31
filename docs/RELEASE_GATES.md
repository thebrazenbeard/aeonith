# Aeonith source release gates

_v0.2.0 candidate update, 2026-10-31. Evidence below reflects the assembled source tree tested locally by the integrator. It is not a claim of GitHub CI, live inference, or GPT equivalence. The original v0.1.0 main release merged at `63f10ff049ddc33359a7960bc06b1f8c645880ba` with 75 passing tests._

| Gate | Evidence available | Verdict / action |
| --- | --- | --- |
| Exact source and scope | v0.2 is based on the verified v0.1.0 main tree at `63f10ff`; the previously obtained 14-lens specification remains sanitized | Commit only public code, fixtures and docs; never owner-editor private capture |
| No private GPT assets in public source | Candidate code and sanitized spec inspected; sensitive owner-editor capture retained outside the public repository | Do **not** commit private capture, secret trigger, attached knowledge assets, or original GPT export claims |
| Basic executable behavior | v0.2 candidate, Python 3.12, `python -m unittest discover -s tests -q`: **156/156 PASS**, exit 0, including 75 previously passing v0.1 tests | Contract-test pass only; loopback HTTP tests required local socket permission |
| Independent adversarial tests | Three additional parallel specialist review waves; replay-ID binding, expiry recheck, bool type, unexpected tool output, blinded assignment, identity metadata, file mode, performance regressions tested | Reproduced vulnerabilities closed for tested cases; no proof of absent defects |
| JSON capability adapter | v0.1 typed contract and 24 adapter tests retained, plus source-only fail-closed host-boundary example | Neither an installed host adapter nor authorization/replay attestation |
| HTTP provider adapter | Chat Completions + Responses adapters, parameter opt-ins, local mock transport, refusal, redirect and credential tests | No credentialed external model inference tested |
| User workflow | UTF-8 manuscript converter, Markdown renderer, exact source-offset sidecar, isolated wheel smoke in Python 3.12 | No browser app or running network service |
| Evaluation framework | Offline quote/reference audit, filler warnings, stable blind A/B mapping, restrictive output file mode, human annotation schema and hashed provenance manifest | No human ratings or semantic quality scores yet |
| Provider runtime | HTTP adapter present, but no credentialed service probe or human-assessed critique verified | **Open: do not claim live/provider quality or deployment** |
| Publication and rights | Public repo had no license; GPT knowledge files not established for redistribution | **Open: no third-party materials, no invented license** |
| Review comparison | One owner GPT probe was conducted; it merged lens headings and miscounted words | **Open: no equivalence claim; paired held-out evaluations required** |
| Ecosystem authority | Rezon/CCB reviewed for possible contract integration, no service bindings | **Open: source interface is not host-installed or authorized runtime** |
| GitHub release | v0.2 feature branch prepared from `63f10ff`, local source passed 156 tests | **Pending** PR, exact-head Python 3.11/3.12/3.13 CI, merge qualification and readback |

## Hostile release challenges

> A JSON output with fourteen lens IDs does not demonstrate fourteen independent or useful interpretations. A model can repeat one generic sentence fourteen times and pass structural checks.

> Confirming that a quotation appears in the manuscript does not validate the critic's conclusion. Separate textual observation, interpretation, alternative reading, and historical claims in live evaluation.

> A generic compatible HTTP client does not guarantee compatibility with every model vendor. Select and test actual provider/model pairs; do not advertise them from API-shape similarity alone.

> Automatic model judgements can encode position, verbosity, cultural, and authorship biases. Independent human annotations and adversarial alternate readings are stronger than a second model's unexamined numerical scores.

## Suggested next slices

1. Complete exact-head GitHub CI and merge/readback for the v0.2 source release. Do not infer deployment from merge.
2. Qualify an explicitly selected model with a non-sensitive consented manuscript and known privacy/cost budget before operational use.
3. Run consented blind paired literary reviews across flash fiction, poetry, dialogue and ambiguous/long excerpts with human scoring, order swaps, provenance and limitations.
4. Qualify chapter-aware aggregation and counterreading improvements with human usefulness measures; source offsets alone do not measure insight.
5. Seek the repository owner's deliberate decision on license, GPT-to-plugin migration and rights to each knowledge asset before publishing or importing corresponding content.
