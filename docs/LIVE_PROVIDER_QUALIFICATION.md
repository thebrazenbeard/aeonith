# Live provider qualification (operator-controlled)

Aeonith v0.3's local unit and transport tests are **not** evidence that an
actual deployed provider/model can complete a literary review. This document
describes a narrow canary that tests one real API call without using a private
manuscript. It is a runtime smoke test, not a human literary-quality study.

## Preconditions

1. Verify the intended deployment URL, repository commit, account/team, and
   deployment-protection status. Never paste a provider API key into a URL,
   command line, web form, chat message, or source file.
2. Configure the deployed service's server-side provider URL, model and API
   key through protected host environment settings. The client must not choose
   or override the upstream provider destination.
3. Configure a **separate** inbound `AEONITH_SERVICE_TOKEN` with the hosting
   provider or equivalent host-owned authentication. Supply the same token to
   the canary through a local protected environment/secret manager, not a
   command-line literal.
4. Confirm that a paid invocation and disclosure of the synthetic canary text
   are acceptable. Apply provider billing limits and service access/rate
   limits before exposing a paid endpoint to other people.
5. Select a real model that supports the configured Responses API output
   format. Model compatibility, cost and retention are not inferred from the
   class name or from schema validation.

## Safe probe

From the checked-out repository root, **without any paid call**:

```bash
python -m scripts.live_canary \
  --url https://YOUR-VERIFIED-HOST/api/review
```

The default result is `{"status":"not_run","reason":"explicit_execution_required"}`
with exit status `2` (not a passing release gate).
It performs no network request and does not need any secrets.

After the above preconditions are met, explicitly opt in to sending the
newly written, non-sensitive canary fiction to the deployed service:

```bash
python -m scripts.live_canary \
  --url https://YOUR-VERIFIED-HOST/api/review \
  --auth-env AEONITH_SERVICE_TOKEN \
  --execute --allow-paid-inference --timeout 90
```

If an independently protected Vercel preview is being tested and an operator
has an authorized automation-bypass secret, add
`--vercel-bypass-env VERCEL_AUTOMATION_BYPASS_SECRET` with that value set in
the operator's **private environment**. Never supply the secret itself as an
argument. Run the probe only against URLs owned or trusted by the operator;
the service bearer token is sent to the explicitly chosen URL.

The canary includes `X-Aeonith-Disclosure: accepted` only after the explicit
paid-inference opt-in. The service requires this acknowledgment before sending
the text to a remote model. The canary refuses redirects and inherited HTTP(S) proxies; uses HTTPS for
remote hosts and permits HTTP only for explicit localhost/loopback testing;
reads no more than 4 MB from the response; and bounds the HTTP timeout to
120 seconds. It sends only the constant synthetic text:

> At noon the harbor bell rang thirteen times. The fishermen laughed at the
> mistake, but the tide did not.

The CLI prints only a compact outcome, such as
`{"status":"passed","lens_count":14,"work_quote_anchors":14,"elapsed_ms":1720}`.
It does **not** print the supplied text, response analyses, bearer secrets,
upstream errors, or the endpoint URL. Exit `0` means that its bounded checks
passed; exit `1` means a safe-to-report failure; exit `2` means execution
was skipped (missing explicit execution or paid-inference consent). A default
not-run never exits successfully and never counts as a provider qualification.

## What must pass

- HTTP 200 JSON object; `schema_version=aeonith.review.v1`;
  `status=completed`; no embedded error.
- All fourteen requested canonical lenses, exactly once, each with a
  nonempty analysis. Textual readings must include literal quotes from the
  synthetic source; insufficient-text readings must explain limitations.
- At least one actual work-text quote anchor, an overarching synthesis, a
  `null` literary assessment, and expected provider-sourced provenance.
- No untrusted reference IDs or invented quotations in the result's lens
  supports, and no accidental non-finite or duplicate JSON fields.
- A separate manual observation of deployment status and latency; if the
  endpoint times out or returns an upstream failure, investigate rather than
  automatically retrying a potentially billable request.

`tests/test_live_canary.py` covers no-network-by-default, explicit consent,
missing credentials, unsafe URLs, quote/lens validation, HTTP errors,
redirect rejection, proxy bypass, and a successful local HTTP fake. Those
tests incur **no provider cost** and do not establish live compatibility.

## What passing does *not* prove

The canary cannot establish critical insight, absence of hallucinations beyond
its anchors, author satisfaction, parity with the ChatGPT GPT, provider
identity/retention guarantees, authentication ownership, cost safety under
load, or whether any review was actually seen by a person. A malicious fake
service could return a structurally valid synthetic result. Human blinded
comparison, rate/cost-abuse protections, independent origin verification and
real retention assessment remain separate release gates.

The Responses adapter sends `store: false`, which disables API response-state
storage for later retrieval; **it is not a zero-retention promise**. Confirm
the selected provider's actual applicable policy before sending private work.

Official references:

- [OpenAI Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Vercel Function limits](https://vercel.com/docs/functions/limitations)
- [Vercel duration configuration](https://vercel.com/docs/functions/configuring-functions/duration)
