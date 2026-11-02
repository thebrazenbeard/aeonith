# Literary criticism quality gate — proposed study v1

**Status: PROPOSED / NOT RUN.** This is a precommitted plan for a new study, not evidence that any Aeonith model is effective, trained, or deployable. Freeze this document and the exact candidate/runtime manifests **before** beginning its first new-model run. The already-reported PR #20 Lappy pilot is exploratory evidence only: one 2,048-token JSON-schema attempt completed structurally, while one 800-token JSON-object attempt failed. Neither assessed literary judgment.

The objective is to falsify unsupported interpretive claims, especially the assertion that an isolated image is a **recurring motif**. An exact source quote and valid `aeonith.review.v1` JSON do not establish that the interpretation follows from the quote. This study complements, but does not replace, structural audits or literary human judgment.

## Rights, scope, and immutable inputs

- All 18 stimuli below were newly written as short, artificial study passages; they contain no private manuscript, copied book excerpt, author biography, or personal data. Their only intended uses are qualification and regression tests. **Never train or fine-tune on these evaluation items.** Do not import third-party benchmark books without independently verifying rights and preprocessing provenance.
- Preserve each case ID, title and text exactly as printed, including punctuation, Unicode and capitalization. Each request uses `{"schema_version":"aeonith.review.v1","work":{"title":"<TITLE>","text":"<TEXT>"},"lenses":["symbolic"]}` for the primary currently deployed one-lens path. Replace the placeholders with the literal case fields, not case IDs.
- Pin the case list, Git commit, critic prompt, runner and model artifact digests, generation parameters and output-contract versions in a read-only manifest. A model tag or model-name hash is **not** a verified weight digest. For any later adapter training, quarantine this study's entire text and outputs from TRAIN and DEV.
- These tiny passages evaluate calibrated close reading, not understanding of unseen chapters or books. The long-form CLI in draft PR #20 has different context and failure modes, and requires a separate study.

### Four metamorphic recurrence pairs (8 cases)

Each positive variant makes repetition explicit while holding its central image close to its paired negative. In a negative variant, **asserting** that recurrence occurs across a larger unseen work is an overclaim. In a positive variant, recognizing explicit recurrence is justified, but assigning a fixed symbolic meaning is not compulsory. A tentative statement that an image *could become* a motif in a longer work is not an assertion of observed recurrence.

**R01-N — A single bell**

> At dusk the bell rang once. Mara looked toward the harbor.

**R01-P — The evening bell**

> At every dusk the bell rang once. Mara counted the sounds until autumn.

**R02-N — One moth**

> A blue moth touched the window and vanished.

**R02-P — Returning moth**

> For seven evenings the blue moth returned to the same window.

**R03-N — One red door**

> In the abandoned house, the door was red.

**R03-P — Repeated red doors**

> Every room in the abandoned house had a red door.

**R04-N — One lost letter**

> I dropped one letter into the river.

**R04-P — Seasonal letters**

> Each spring I dropped another letter into the river.

### Ten standalone challenge cases

**S01 — Literal complaint**

> After the update, the upload button returns an error. Please restore it.

Grounded behavior: acknowledge its literal software-support content. Critique of tone or rhetoric is legitimate; a recurring literary motif or fictional plot invented from this text is not.

**S02 — Insufficient context**

> The last door stayed open.

Grounded behavior: admit the missing cause, genre and wider narrative. “Last” and “stayed” are actual textual cues, but do not establish who left it open or why.

**S03 — Pronoun ambiguity**

> Eli watched Noor leave. She kept the key.

Grounded behavior: qualify any claim about which person kept the key, unless explicitly argued as one possible reading. Neither person's motives are supplied.

**S04 — Contradictory narrator**

> I never read the note, though I remember every word.

Grounded behavior: identify the apparent tension and multiple explanations (hearsay, deception, memory, metaphor). A definitive diagnosis of the speaker is unsupported.

**S05 — Sequence versus causation**

> The clock stopped. One minute later, the ferry returned.

Grounded behavior: recognize temporal order without asserting that stopping the clock caused the ferry's return.

**S06 — Unspecified history**

> Under a blue banner, they signed the agreement.

Grounded behavior: do not supply an era, country, political faction, religion or treaty name as fact.

**S07 — Stage directions**

> LIGHTS OUT. The actor keeps speaking into the dark.

Grounded behavior: note that the format plausibly suggests stage directions or performance. Do not invent a novel narrator, chapter number or character backstory.

**S08 — Sound and form**

> Rain rattled the rusted roof.

Grounded behavior: notice grounded sound patterning and word choice. Do not insist the rain symbolizes grief without additional evidence.

**S09 — Ethical ambiguity**

> She hid the map from the stranger, then watched the flood reach the bridge.

Grounded behavior: explore ethically competing possibilities while acknowledging unknown intent, necessity and consequence.

**S10 — Dialogue subtext**

> “I saved you a place,” Ina said. “You saved an empty chair,” he answered.

Grounded behavior: consider disappointment, absence, conflict or irony as alternatives. Do not report an unseen prior breakup as established fact.

## Runtime and protocol

1. **No unauthorized workload:** Before inference, confirm the owner-controlled host, real free RAM/VRAM, running processes, GPU lease/ownership, already-installed model inventory, model license and existing critical workloads. Stop if a training job or protected service would be contended with. Do not download a GGUF, create a paid account, enroll in billing, use a paid API, or change Funnel/public service as part of the study. The hard incremental service-spend budget is **$0**.
2. **Candidate custody:** Keep the incumbent VN1 local model as a control. Treat draft `aeonith-critic:0.1` as an **untrained Ollama recipe** (`fine_tuned=false`), not a new trained weight artifact. Test only locally available candidates whose exact runner/base model digest can be read back. Version any Modelfile/adapter separately.
3. **Feasibility screen:** Run R01-N, R01-P and S01 for **two uncontrolled repeats** per candidate (3 × 2 × 2 = 12 attempted responses for a two-candidate comparison). Record every timeout, invalid JSON, unsupported quote, runner failure and completion. Do not extend to the full study if resource safety or basic output viability fails. PR #20's `--repeats` changes trial count; it does **not** establish controlled generation seeds.
4. **Full test:** If the screen permits, run all 18 cases × **three uncontrolled repeats** × two candidates = **108 attempted responses**. Use one model process at a time if GPU ownership or memory requires. Record model/runner version, immutable model-artifact identity where available, local endpoint, timeout, output cap, context cap, temperature, response-format setting, latency and review status for *each attempt*. Do not expose local bearer secrets in reports.
5. **Two separate lanes:** **Production-equivalence lane:** match the actual VN1 launcher, including its currently stated **50-second timeout / 800-token output cap** and exact JSON-output mode. **Laboratory lane:** a clearly separate trial may use 150 seconds / 2,048 tokens / JSON Schema, matching the reported successful Lappy pilot. Never use lab-lane success as a substitute for a production-equivalence pass. For any A/B comparison within a lane, use identical available prompt/temperature/token/time settings; otherwise label outcomes **NOT COMPARABLE**.
6. **Structural audit:** Use `evaluation.quality_eval.audit_review()` and draft PR #20's sanitized `evaluation.model_pilot.run_pilot()` where applicable. Exact-substring checks validate explicit support anchors; they do **not** reject fabricated quotations or unsupported assertions embedded in free-form `analysis`, `synthesis`, `challenges`, or `uncertainties`. A structurally passing critique can still falsely cite a nonexistent sentence or chapter. Record the structural result separately from a human-reviewed quote-integrity and semantic-calibration verdict; if no such review occurred, mark both **UNASSESSED**, never PASS. Store only sanitized status, hashes, timings, dimensions and failure categories in Git. Retain raw model prose and source-pair keys privately on owner-controlled storage, encrypted/access-restricted as appropriate, then delete on a documented retention schedule chosen by the operator.
7. **Blind human review:** For outputs where **both** candidates produce structurally valid reviews, call `evaluation.quality_eval.build_blind_pair()` with distinct candidate IDs and a recorded display seed, retain its private assignment key separately, and bind human annotations to exact display hashes. Obtain at least two **genuinely independent human** ratings per case if possible. The six existing rubric dimensions are `textual_accuracy`, `lens_distinctness`, `critical_depth`, `calibration`, `actionability`, and `synthesis`, each scored 0/1/2 for A and B; reviewers also choose A/B/tie/incomparable and provide a substantive rationale. Native ChatGPT subagents can assist with adversarial review but must **not** be relabeled independent human raters.
8. **Side effects and identity:** Randomize/blind candidate position and inspect A/B balance. Exclude model IDs, provenance and prompts revealing model identity from human display; inspect every free-form prose field manually for self-identifying clues **before** independent review. Field-level metadata projection does not remove a model saying its own identity in `analysis`. Quarantine compromised pairs, retain them in completion/failure accounting, and document any redactions so raters never mistake altered prose for an original answer. Keep rating order independent where possible. Unblind only after annotations and failure accounting are frozen.

### Primary denominator and survivorship-bias safeguard

**Every attempted response belongs in the primary analysis**, including timeouts, `invalid_provider_output`, JSON/schema failures, and failed quote audits. A case with no valid critique is not a literary success, even if the model's few successful examples read beautifully.

> `build_blind_pair()` explicitly refuses structurally invalid candidates. Reporting only paired valid critiques therefore conditions on success and can favor a model that frequently fails. Human A/B preferences are a **secondary, conditional outcome**. Always report the eligible-pair fraction and per-model attrition alongside them; never silently drop a failed attempt from the denominator.

Three repeats of one stimulus are correlated. Report 18 **distinct stimulus-level descriptive outcomes** using a declared within-case majority/consensus rule; 54 repeats are not 54 independently sampled literary works. Moreover, the eight recurrence stimuli form four deliberately related positive/negative pairs, leaving **14 stimulus families** (four paired families and ten standalones). Do not treat the 18 stimuli as statistically independent observations. Preserve the four within-family contrasts, use family-clustered uncertainty summaries if estimating variability, and keep individual failure counts and disagreement visible. The proposed 14-of-18 preference threshold is a descriptive engineering gate, not a significance test.

### Overclaim rubric and counterexamples

- **Critical negative-control error:** In R01-N through R04-N, the critique states as fact that an image, word or event *recurs throughout the work*, that the author planted a recurring motif, or that later passages repeat it, despite only the one supplied occurrence and no corroborating evidence. The same applies to asserting an invented specific authorial intent, character biography, historical setting or causal link in S01–S10. A source-exact quote does not repair an unsupported inference.
- **Not automatically an error:** “This could develop into a motif if it recurs elsewhere”; “the bell might symbolize an alert, but the passage alone cannot prove that”; “the red door occurs in each described room” for R03-P; “each spring another letter is dropped” for R04-P. An analysis can use *motif* as a hypothetical future craft suggestion without asserting unseen recurrence. A nuanced reading can be symbolic without certainty.
- **Positive-pair sensitivity:** Compare each Rxx-P with Rxx-N. A strong critic recognizes explicit repeated evidence in P, avoids claiming repetition in N, and calibrates symbolic claims in both. It need not say the word “motif”; exact-token keyword scoring alone is insufficient.
- **Ambiguous cases:** Human raters must record why a claim is overconfident rather than treat disagreement about symbolism as a factual error. If qualified reviewers cannot agree, mark **UNCERTAIN**, not a fabricated pass.

### Proposed product gates (not statistical proof)

Apply in order; if one fails, **do not promote** a candidate to the live model. These thresholds are engineering acceptance proposals and should be frozen before execution, not tuned afterward.

| Gate | Proposed minimum |
| --- | --- |
| Rights/host | Verified model and test-data rights; no paid spend, unapproved model downloads or workload collisions |
| Production completion | At least **95%** structurally valid completed reviews under **50 s / 800 output tokens**, with each timeout/failure included in denominator |
| Quote integrity | **Zero** invented or non-source-exact work quotations **after manual review of all free-form prose**; exact support-anchor checks alone cannot establish this. Unreviewed attempts are **UNASSESSED**, not PASS |
| Negative-control calibration | At least **90%** of judged negative-control responses free of *asserted* unsupported recurrence/invented context (manual adjudication) |
| Metamorphic pairs | At least **3 of 4** pairs show, by case-level consensus, better-recognized recurrence evidence in positive variants without false claims in negatives |
| Blind preference | Candidate preferred on at least **14 of 18** distinct case-level comparisons, with ≥2 independent human raters/case, no decrease in `textual_accuracy` or `calibration` averages; ties, incomparable and invalid pairs are reported explicitly |
| Resource/reliability | Fits the actual host's owner-authorized RAM/VRAM/CPU envelope, avoids interfering with other services, meets live latency limits; rollback to incumbent proven |

Even if these provisional gates pass, claims are limited to **better demonstrated performance on this small preregistered challenge set**. They do not show broad literary expertise, authorial intent detection, human parity, generalized long-form understanding, stable cross-seed behavior, or genuine fine-tuning. A trained adapter requires an actual weight update, persistence/reload proof, rights-cleared corpus and a separate held-out study.

## Primary methodological sources

- [KRISTEVA: Close Reading as a Novel Task for Benchmarking Interpretive Reasoning (ACL 2025)](https://aclanthology.org/2025.acl-long.1577/) distinguishes stylistic observation, contextual retrieval and multi-hop close reading; this study samples smaller textual-grounding/calibration probes, not KRISTEVA's 1,331 licensed questions.
- [LiteraryQA: Towards Effective Evaluation of Long-document Narrative QA (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.1729/) reports weak alignment of simple n-gram metrics with human literary-QA judgment; exact quote matching is therefore an integrity check, not an insight score. This v1 uses no LiteraryQA excerpts.
- [Chatbot Arena: An Open Platform for Evaluating LLMs by Human Preference (ICML 2024)](https://proceedings.mlr.press/v235/chiang24b.html) motivates blinded human pairwise comparison. Aeonith's small 18-case gate is not Arena-scale, and its threshold table is a deployment heuristic rather than a statistically established leaderboard ranking.

## Completion status ledger

| Evidence class | State as this document is proposed |
| --- | --- |
| Original stimuli and negative-control contrasts | **Defined in source**; no model responses run under this protocol |
| Code/JSON contract tests | Already exist independently; they are not semantic evaluation |
| New controlled live-model run | **NOT PERFORMED** |
| Independent human rating | **NOT PERFORMED** |
| Model artifact / adapter train-and-reload | **NOT PERFORMED** by this protocol |
| Literary generalization or production promotion | **UNASSESSED / NOT AUTHORIZED BY THIS DOCUMENT** |
