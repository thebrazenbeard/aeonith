"""Exercise actual browser review handlers in a dependency-free Node DOM harness.

The mock transport returns synthetic critiques. No browser, model, credentials,
host session, network endpoint or user-owned manuscript is accessed.
"""

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]

NODE_DRIVER = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
// An explicit test-only stdin override lets hostile reviewers reproduce the
// same scenario against the immutable predecessor without writing a file.
const source = process.env.AEONITH_BROWSER_SOURCE_STDIN === '1' ?
  fs.readFileSync(0, 'utf8') : fs.readFileSync('./public/app.js', 'utf8');
const slice = (begin, end) => {
  const a = source.indexOf(begin);
  const b = end === null ? source.length : source.indexOf(end, a);
  if (a < 0 || b < 0) throw new Error('Production browser boundary not found');
  return source.slice(a, b);
};

const ids = new Map();
function node() {
  return {
    hidden: false, textContent: '', value: '', checked: false,
    disabled: false, style: {}, children: [], events: {}, attributes: {},
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    addEventListener(name, callback) { this.events[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() {},
  };
}
const byId = id => {
  if (!ids.has(id)) ids.set(id, node());
  return ids.get(id);
};
const form = node();
const lensInputs = [{ checked: true, value: 'symbolic', events: {}, addEventListener(name, callback) { this.events[name] = callback; } },
                    { checked: false, value: 'stylistic', events: {}, addEventListener(name, callback) { this.events[name] = callback; } }];
form.querySelectorAll = () => lensInputs.filter(input => input.checked);
const titleInput = byId('work-title');
const manuscriptInput = byId('manuscript');
const contextInput = byId('story-context');
const contextCountNode = byId('context-character-count');
const consentInput = byId('disclosure');
const tokenInput = byId('service-token');
const submitButton = byId('submit-button');
const resultsNode = byId('results');
resultsNode.hidden = true;
const emptyNode = byId('reading-empty');
const statusNode = byId('status');
const errorNode = byId('error');
const countNode = byId('character-count');
const copyButton = byId('copy-result');
const copyStatus = byId('copy-status');
let copied = '';
let pending = null;
let deferred = false;
let lastPayload = null;
let fetchCount = 0;
const result = {
  schema_version: 'aeonith.review.v1', status: 'completed',
  synthesis: 'The sentence creates suspense.',
  lens_reviews: [{ lens: 'symbolic', analysis: 'The door suggests a threshold.',
                   basis: 'textual', support: [{ source: 'work', quote: 'door' }],
                   limitations: [] }], challenges: [], uncertainties: []
};
const httpResponse = { ok: true, status: 200,
  text: async () => JSON.stringify(result) };
const context = vm.createContext({
  document: { createElement: () => node() }, byId, form, titleInput,
  manuscriptInput, contextInput, contextCountNode, consentInput, tokenInput, submitButton, resultsNode,
  emptyNode, statusNode, errorNode, countNode, copyButton, copyStatus,
  lensInputs, lensLabels: {symbolic: 'Symbolic', stylistic: 'Stylistic', comparative: 'Comparative'},
  MAX_MANUSCRIPT_CHARS: 12000, MAX_CONTEXT_CHARS: 2000, MAX_LENSES: 14, effectiveMaxLenses: 14,
  browserSessionActive: false, AbortController, setTimeout, clearTimeout,
  navigator: { clipboard: { writeText: async text => { copied = text; } } },
  fetch: async (_url, options) => {
    lastPayload = JSON.parse(options.body);
    fetchCount++;
    return deferred ? new Promise(resolve => { pending = resolve; }) : httpResponse;
  },
});
vm.runInContext('let plainTextReview = ""; let displayedReviewSource = null; let requestInFlight = false; let manuscriptRevision = 0;', context);
vm.runInContext('let lensLimitKnown = false; function configureLensCeiling() {}', context);
vm.runInContext(slice('lensInputs.forEach((input) => input.addEventListener("change"', 'configureLensCeiling(null);'), context);
if (source.includes('const semanticAdvisoryLabels = Object.freeze({')) {
  vm.runInContext(slice('const semanticAdvisoryLabels = Object.freeze({', 'let plainTextReview = "";'), context);
}
vm.runInContext(slice('function element(tag, value, className) {', 'function requestError('), context);
vm.runInContext(slice('function requestError(', 'function extractDocxInWorker('), context);
vm.runInContext(slice('form.addEventListener("submit"', null), context);

const submit = () => form.events.submit({ preventDefault() {} });
async function successful() {
  titleInput.value = 'Draft 1';
  manuscriptInput.value = 'The door creaked.';
  tokenInput.value = 'synthetic-only-not-a-real-secret';
  consentInput.checked = true;
  await submit();
  assert.equal(resultsNode.hidden, false);
}
async function run() {
  const scenario = process.argv[1];
  await successful();
  if (scenario === 'invalid_resubmit') {
    // Consent is intentionally reset after every submission; a second click
    // without it must keep the previous valid critique and copy buffer.
    await submit();
    assert.match(errorNode.textContent, /Confirm that you have permission/);
    assert.equal(resultsNode.hidden, false);
    await copyButton.events.click();
    assert.match(copied, /The sentence creates suspense/);
    assert.match(statusNode.textContent, /previous critique remains/i);
  } else if (scenario === 'edit_marks_stale') {
    manuscriptInput.value = 'A different passage.';
    manuscriptInput.events.input();
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /does not apply to the current editor/i);
    assert.match(copyButton.textContent, /prior-version/i);
    await copyButton.events.click();
    assert.match(copied, /PRIOR REVIEW VERSION/);
    assert.match(copied, /Draft 1/);
    titleInput.value = 'Renamed draft';
    titleInput.events.input();
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
  } else if (scenario === 'title_only_stale') {
    titleInput.value = 'Draft 2';
    titleInput.events.input();
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /Earlier critique/);
  } else if (scenario === 'context_in_payload') {
    contextInput.value = 'Miren knows the narrator\'s name, but not his history.';
    contextInput.events.input();
    assert.equal(consentInput.checked, false);
    consentInput.checked = true;
    await submit();
    assert.equal(lastPayload.context, contextInput.value);
    assert.match(byId('result-provenance').children[0].textContent, /context supplied/i);
    await copyButton.events.click();
    assert.equal(copied.includes(contextInput.value), false);
  } else if (scenario === 'context_over_limit') {
    const before = fetchCount;
    contextInput.value = 'X'.repeat(2001);
    contextInput.events.input();
    consentInput.checked = true;
    await submit();
    assert.equal(fetchCount, before);
    assert.match(errorNode.textContent, /2,000 characters/);
    assert.equal(resultsNode.hidden, false);
  } else if (scenario === 'context_edit_marks_stale') {
    contextInput.value = 'Only the first chapter is known.';
    contextInput.events.input();
    assert.equal(consentInput.checked, false);
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /does not apply/i);
    assert.equal(contextCountNode.textContent, `${contextInput.value.length} / 2,000 characters`);
    await copyButton.events.click();
    assert.match(copied, /PRIOR REVIEW VERSION/);
    assert.equal(copied.includes(contextInput.value), false);
  } else if (scenario === 'context_inflight_superseded') {
    contextInput.value = 'The narrator fears stairs.';
    contextInput.events.input();
    consentInput.checked = true;
    deferred = true;
    const request = submit();
    await Promise.resolve();
    assert.equal(lastPayload.context, 'The narrator fears stairs.');
    contextInput.value = 'The narrator has never feared stairs.';
    contextInput.events.input();
    pending(httpResponse);
    await request;
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /does not apply/i);
  } else if (scenario === 'lens_change_marks_stale') {
    consentInput.checked = true;
    lensInputs[1].checked = true;
    lensInputs[1].events.change();
    assert.equal(consentInput.checked, false);
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /does not apply/i);
    await copyButton.events.click();
    assert.match(copied, /PRIOR REVIEW VERSION/);
  } else if (scenario === 'inflight_superseded') {
    manuscriptInput.value = 'The door returned.';
    manuscriptInput.events.input();
    consentInput.checked = true;
    deferred = true;
    const request = submit();
    await Promise.resolve();
    assert.equal(typeof pending, 'function');
    manuscriptInput.value = 'A third passage.';
    manuscriptInput.events.input();
    pending(httpResponse);
    await request;
    assert.equal(resultsNode.hidden, false);
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /does not apply to the current editor/i);
  } else if (scenario === 'invalid_response_preserves') {
    const earlier = byId('result-synthesis').children.length;
    deferred = true;
    consentInput.checked = true;
    const request = submit();
    await Promise.resolve();
    pending({ok:true,status:200,text:async()=>JSON.stringify({status:'completed',schema_version:'aeonith.review.v1',synthesis:'oops',lens_reviews:[null]})});
    await request;
    assert.equal(resultsNode.hidden, false);
    assert.equal(byId('result-synthesis').children.length, earlier);
    assert.match(statusNode.textContent, /previous critique remains/i);
  } else if (scenario === 'complete_lenses_reordered') {
    lensInputs[1].checked = true;
    lensInputs[1].events.change();
    consentInput.checked = true;
    const item = {lens:'symbolic', analysis:'The door suggests a threshold.', basis:'textual',
                  support:[{source:'work', quote:'door'}], limitations:[]};
    deferred = true;
    const request = submit();
    await Promise.resolve();
    pending({ok:true,status:200,text:async()=>JSON.stringify({
      status:'completed',schema_version:'aeonith.review.v1',synthesis:'VALID_TWO_LENS_READING',
      lens_reviews:[{...item,lens:'stylistic'}, item], challenges:[], uncertainties:[]
    })});
    await request;
    assert.equal(errorNode.hidden, true);
    assert.equal(resultsNode.attributes['data-source-state'], 'current-version');
    assert.match(byId('result-synthesis').children[0].children[1].textContent, /VALID_TWO_LENS_READING/);
  } else if (scenario === 'missing_lens_response' || scenario === 'unexpected_lens_response' ||
             scenario === 'duplicate_lens_response' || scenario === 'substituted_lens_response') {
    const originalSynthesis = byId('result-synthesis').children[0];
    // Start a new review with a different lens selection when necessary.
    if (scenario !== 'unexpected_lens_response') {
      lensInputs[1].checked = true;
      lensInputs[1].events.change();
    }
    await copyButton.events.click();
    const originalCopy = copied;
    const item = {lens:'symbolic', analysis:'The threshold matters.', basis:'textual',
                  support:[{source:'work', quote:'door'}], limitations:[]};
    const other = {...item, lens:'stylistic'};
    const substituted = {...item, lens:'comparative'};
    let rows;
    if (scenario === 'missing_lens_response') rows = [item];
    else if (scenario === 'unexpected_lens_response') rows = [other];
    else if (scenario === 'duplicate_lens_response') rows = [item, {...item}];
    else rows = [item, substituted];
    deferred = true;
    consentInput.checked = true;
    const request = submit();
    await Promise.resolve();
    pending({ok:true,status:200,text:async()=>JSON.stringify({
      status:'completed',schema_version:'aeonith.review.v1',synthesis:'MALFORMED_NEW_RESULT',
      lens_reviews:rows, challenges:[], uncertainties:[]
    })});
    await request;
    assert.equal(resultsNode.hidden, false);
    assert.equal(byId('result-synthesis').children[0], originalSynthesis);
    await copyButton.events.click();
    assert.equal(copied, originalCopy);
    assert.match(errorNode.textContent, /incomplete or malformed critique/i);
    assert.match(statusNode.textContent, /previous critique remains/i);
  } else if (scenario === 'triage_absent') {
    await copyButton.events.click();
    assert.match(copied, /Semantic quality not assessed/);
    assert.match(copied, /no semantic-triage report/);
  } else if (scenario === 'triage_warning_code_only') {
    result.semantic_triage = {
      schema_version: 'aeonith.semantic_triage.v1',
      semantic_quality: 'UNASSESSED', classification: 'HEURISTIC_HUMAN_REVIEW_ONLY',
      warnings: [
        { code: 'possible_unseen_story_context', path: 'DO_NOT_LEAK_PRIVATE_PATH' },
        { code: 'possible_unfounded_recurrence', path: '<script>PRIVATE_EXCERPT</script>' },
        { code: 'unknown_raw_secret_code', path: 'OTHER_SECRET' },
      ],
      limitations: ['UNTRUSTED_PRIVATE_PASSAGE'],
    };
    consentInput.checked = true;
    await submit();
    await copyButton.events.click();
    assert.match(copied, /Possible assertion about unseen story events/);
    assert.match(copied, /Possible unsupported recurrence/);
    assert.match(copied, /Some advisory warning codes were unrecognized/);
    for (const forbidden of ['PRIVATE_PATH', 'PRIVATE_EXCERPT', 'OTHER_SECRET',
                             'unknown_raw_secret_code', 'UNTRUSTED_PRIVATE_PASSAGE']) {
      assert.equal(copied.includes(forbidden), false);
    }
  } else if (scenario === 'triage_empty_no_quality_pass') {
    result.semantic_triage = {
      schema_version: 'aeonith.semantic_triage.v1',
      semantic_quality: 'UNASSESSED', classification: 'HEURISTIC_HUMAN_REVIEW_ONLY',
      warnings: [],
    };
    consentInput.checked = true;
    await submit();
    await copyButton.events.click();
    assert.match(copied, /No lexical warnings were raised/);
    assert.match(copied, /not a quality pass/);
  } else if (scenario === 'triage_full_90') {
    result.semantic_triage = {
      schema_version: 'aeonith.semantic_triage.v1',
      semantic_quality: 'UNASSESSED', classification: 'HEURISTIC_HUMAN_REVIEW_ONLY',
      warnings: Array.from({length: 90}, (_, i) => ({
        code: i % 2 ? 'possible_unseen_story_context' : 'possible_unfounded_recurrence',
        path: 'PRIVATE_FIELD_' + i,
      })),
    };
    consentInput.checked = true;
    await submit();
    await copyButton.events.click();
    assert.equal((copied.match(/Possible assertion about unseen story events/g) || []).length, 1);
    assert.equal((copied.match(/Possible unsupported recurrence/g) || []).length, 1);
    assert.equal(copied.includes('Advisory metadata was unrecognized'), false);
    assert.equal(copied.includes('PRIVATE_FIELD_'), false);
  } else if (scenario === 'triage_malformed_is_not_verified') {
    result.semantic_triage = {
      schema_version: 'aeonith.semantic_triage.v1',
      semantic_quality: 'VERIFIED', classification: 'HEURISTIC_HUMAN_REVIEW_ONLY',
      warnings: [{code:'possible_unseen_story_context', path:'MALICIOUS_PRIVATE_PATH'}],
    };
    consentInput.checked = true;
    await submit();
    await copyButton.events.click();
    assert.match(copied, /Advisory metadata was unrecognized/);
    assert.equal(copied.includes('MALICIOUS_PRIVATE_PATH'), false);
  } else throw new Error('unknown scenario ' + scenario);
}
run().then(() => process.stdout.write('PASS')).catch(error => {
  process.stderr.write(error.stack || String(error)); process.exitCode=1;
});
"""


@unittest.skipUnless(shutil.which("node"), "Node.js required for browser handler test")
class BrowserReviewProvenanceTests(unittest.TestCase):
    def test_context_field_is_explicit_bounded_and_described_in_html(self):
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="story-context"', html)
        # No maxlength: a longer paste must trigger a clear validation error,
        # not be silently truncated by the browser before the user sees it.
        self.assertNotIn('id="story-context" name="context" rows="4" maxlength=', html)
        self.assertIn('id="context-character-count"', html)
        self.assertIn('aria-describedby="context-hint context-character-count"', html)
        self.assertIn('id="context-hint"', html)

    def test_invalid_resubmit_preserves_previous_review(self):
        self._run("invalid_resubmit")

    def test_editor_changes_mark_prior_review_stale(self):
        self._run("edit_marks_stale")

    def test_title_only_change_marks_prior_review_stale(self):
        self._run("title_only_stale")

    def test_explicit_context_reaches_provider_without_copy_leak(self):
        self._run("context_in_payload")

    def test_context_limit_prevents_request_and_preserves_review(self):
        self._run("context_over_limit")

    def test_context_edit_resets_consent_and_marks_review_stale(self):
        self._run("context_edit_marks_stale")

    def test_inflight_context_revision_is_provenance_stale(self):
        self._run("context_inflight_superseded")

    def test_selected_lenses_change_marks_review_stale(self):
        self._run("lens_change_marks_stale")

    def test_inflight_response_for_old_text_is_not_current(self):
        self._run("inflight_superseded")

    def test_malformed_new_response_preserves_prior_review(self):
        self._run("invalid_response_preserves")

    def test_response_missing_requested_lens_is_rejected_preserving_prior_review(self):
        self._run("missing_lens_response")

    def test_complete_reordered_lens_coverage_is_accepted(self):
        self._run("complete_lenses_reordered")

    def test_response_unrequested_lens_is_rejected_preserving_prior_review(self):
        self._run("unexpected_lens_response")

    def test_response_duplicate_lens_is_rejected_preserving_prior_review(self):
        self._run("duplicate_lens_response")

    def test_response_substituted_lens_is_rejected_preserving_prior_review(self):
        self._run("substituted_lens_response")

    def test_old_service_without_triage_remains_honest(self):
        self._run("triage_absent")

    def test_known_warning_codes_have_fixed_labels_and_no_path_leak(self):
        self._run("triage_warning_code_only")

    def test_empty_warning_list_is_not_semantic_success(self):
        self._run("triage_empty_no_quality_pass")

    def test_max_backend_90_warnings_dedup_without_raw_metadata(self):
        self._run("triage_full_90")

    def test_malformed_triage_cannot_claim_verification(self):
        self._run("triage_malformed_is_not_verified")

    def _run(self, scenario: str) -> None:
        result = subprocess.run(
            ["node", "-e", NODE_DRIVER, scenario], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS")


if __name__ == "__main__":
    unittest.main()
