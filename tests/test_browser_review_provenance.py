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
const lensInputs = [{ checked: true, value: 'symbolic' }];
form.querySelectorAll = () => lensInputs.filter(input => input.checked);
const titleInput = byId('work-title');
const manuscriptInput = byId('manuscript');
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
  manuscriptInput, consentInput, tokenInput, submitButton, resultsNode,
  emptyNode, statusNode, errorNode, countNode, copyButton, copyStatus,
  lensInputs, lensLabels: {symbolic: 'Symbolic'},
  MAX_MANUSCRIPT_CHARS: 12000, MAX_LENSES: 14, effectiveMaxLenses: 14,
  browserSessionActive: false, AbortController, setTimeout, clearTimeout,
  navigator: { clipboard: { writeText: async text => { copied = text; } } },
  fetch: async () => deferred ? new Promise(resolve => { pending = resolve; }) : httpResponse,
});
vm.runInContext('let plainTextReview = ""; let displayedReviewSource = null; let requestInFlight = false; let manuscriptRevision = 0;', context);
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
    assert.match(copied, /PRIOR MANUSCRIPT VERSION/);
    assert.match(copied, /Draft 1/);
    titleInput.value = 'Renamed draft';
    titleInput.events.input();
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
  } else if (scenario === 'title_only_stale') {
    titleInput.value = 'Draft 2';
    titleInput.events.input();
    assert.equal(resultsNode.attributes['data-source-state'], 'earlier-version');
    assert.match(statusNode.textContent, /Earlier critique/);
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
    def test_invalid_resubmit_preserves_previous_review(self):
        self._run("invalid_resubmit")

    def test_editor_changes_mark_prior_review_stale(self):
        self._run("edit_marks_stale")

    def test_title_only_change_marks_prior_review_stale(self):
        self._run("title_only_stale")

    def test_inflight_response_for_old_text_is_not_current(self):
        self._run("inflight_superseded")

    def test_malformed_new_response_preserves_prior_review(self):
        self._run("invalid_response_preserves")

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
