# Aeonith source release gates

_Documentation and hostile-release review, 2026-10-31. Evidence below reflects the assembled source tree tested locally by the integrator. It is not a claim of GitHub CI, live inference, or GPT equivalence._

| Gate | Evidence available | Verdict / action |
| --- | --- | --- |
| Exact source and scope | Live target `main` initially only README at `caca5631525bdc19c526d44dc660688755d2101c`; authenticated GPT editor yielded sanitized 14-lens spec | Source candidate established; commit only sanitized spec |
| No private GPT assets in public source | Candidate code and sanitized spec inspected; sensitive owner-editor capture retained outside the public repository | Do **not** commit private capture, secret trigger, attached knowledge assets, or original GPT export claims |
| Basic executable behavior | Assembled tree, `python -m unittest discover -s tests -v`, Python 3.12: **75/75 PASS**, exit 0, including 16 core tests | Contract-test pass only; loopback HTTP tests required local socket permission |
| Independent adversarial tests | 25 tests included in the 75-test integrated suite, plus independent W2 hostile retest of forged provider metadata and output amplification | Reproduced vulnerabilities closed for tested cases; live model behavior not verified |
| JSON capability adapter | 24 tests included in integrated suite; actual core-to-adapter success/failure, forged failure provenance, invalid-output and nonfinite JSON rejection | Tested source contract, not host authorization or replay protection |
| HTTP provider adapter | 10 loopback/mock transport tests included in integrated suite; redirects, errors and credential transport tested | No credentialed external model inference tested |
| Provider runtime | HTTP adapter present, but no credentialed service probe or human-assessed critique verified | **Open: do not claim live/provider quality or deployment** |
| Publication and rights | Public repo had no license; GPT knowledge files not established for redistribution | **Open: no third-party materials, no invented license** |
| Review comparison | One owner GPT probe was conducted; it merged lens headings and miscounted words | **Open: no equivalence claim; paired held-out evaluations required** |
| Ecosystem authority | Rezon/CCB reviewed for possible contract integration, no service bindings | **Open: source interface is not host-installed or authorized runtime** |
| GitHub release | Feature branch prepared from initial `main`; local source tree has passed tests | Lead owns PR, exact-head CI, merge qualification and readback |

## Hostile release challenges

> A JSON output with fourteen lens IDs does not demonstrate fourteen independent or useful interpretations. A model can repeat one generic sentence fourteen times and pass structural checks.

> Confirming that a quotation appears in the manuscript does not validate the critic's conclusion. Separate textual observation, interpretation, alternative reading, and historical claims in live evaluation.

> A generic compatible HTTP client does not guarantee compatibility with every model vendor. Select and test actual provider/model pairs; do not advertise them from API-shape similarity alone.

> Automatic model judgements can encode position, verbosity, cultural, and authorship biases. Independent human annotations and adversarial alternate readings are stronger than a second model's unexamined numerical scores.

## Suggested next slices

1. Integrate Python core, examples, tests, capability adapter, and public spec on one reviewable branch; validate with fresh final-tree tests and static checks.
2. Evaluate real-provider HTTP request/response handling against a controlled local server before trying a paid provider.
3. Run consented, blind, paired literary reviews across flash fiction, poetry, non-English creative text, and long-form excerpts; record limitations and model identity.
4. Add source span offsets, counterreadings, and chapter-aware aggregation only with regression or human-review evidence that they improve findings.
5. Seek Patrick's separate decision on license, GPT-to-plugin migration, and rights to each knowledge asset before any corresponding public release or state change.
