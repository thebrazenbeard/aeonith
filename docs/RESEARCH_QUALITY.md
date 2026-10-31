# Aeonith research: literary-critique quality and falsification

Date: 2026-10-31. Owner: native specialist `/root/research_quality` (second wave). Research-only; no Aeonith repository writes. Evidence classes are kept separate: `SOURCE` = peer-reviewed paper or official GitHub source; `INFERENCE` = suggested design transfer; `UNKNOWN` = not shown in Aeonith runtime. GitHub heads are snapshots observed 2026-10-31, not pinned dependencies.

## Concrete near-term enhancements (proposals, not Aeonith capabilities yet)

1. **Text-anchored evidence.** Each nontrivial literary claim should have `evidence`: a short exact quotation from the supplied work, stable paragraph/chapter or character offsets, and an explicit analysis connecting quotation to interpretation. A validator should reject or mark unsupported any quoted span not found in the work; paraphrase should be marked as such. Never invent quotations or bibliographic references. This responds to *Literary Evidence Retrieval via Long-Context Language Models* (ACL 2025), where quotation retrieval and overgeneration are measured failure modes [P2]. Inferred design, not proof that text anchoring makes the interpretation true.
   - Tests: (a) a valid quote and offset round-trip; (b) plausible but nonexistent quote is flagged; (c) Unicode characters/line-break normalization preserve offsets or explicitly mark normalization; (d) inferred character motivation without a quoted passage is marked interpretive rather than observed.
2. **Meaningful lens independence and abstention.** Aeonith's fourteen lenses should remain distinct perspectives, but not each have to invent a criticism. A lens may return `not_applicable`/`insufficient_evidence` with rationale. Require a synthesis with *best alternative reading*, tension among lenses, and a decision-relevant priority, rather than fourteen restatements. The KRISTEVA benchmark parses literary close reading into stylistic extraction, contextual retrieval, and multi-hop interpretation; models lag experienced human readers across most tasks [P1]. This supports a design emphasizing explicit inferential steps without assuming all fourteen lenses independently authoritative.
   - Tests: (a) each lens present/typed without unsupported fabricated findings; (b) the same observation copied to all lenses fails diversity check; (c) a purposely ambiguous passage produces at least one plausible counterreading; (d) stylistic observation and historical claim retain different source labels.
3. **Long-manuscript mode with a provenance-preserving map.** For works larger than model context, retain numbered chunks (chapter ID, byte/character boundaries, title), extract chapter-specific summaries and evidence references, then synthesize across chapters; publish which parts were actually seen. Allow recomputation when chapters change. The LongStoryEval study (600 book-length stories; mean 121K tokens) found aggregation and summary approaches more effective than simple alternatives, with aggregation better for detail and summaries more efficient [P3]. The result does *not* demonstrate that either method solves all cross-chapter continuity.
   - Tests: (a) contradiction planted in chapter 1 and 9 is retrieved with two anchors; (b) omitted chapter forces an honest coverage disclosure; (c) chapter reorder makes stale offsets invalid; (d) summary claims are not mislabeled verbatim text evidence.
4. **Human-calibrated quality over confidence theater.** Offer qualitative judgments with explicit reader/intended-audience priorities, uncertainty, and counterevidence. Resist ungrounded single numerical 'quality' scores, author comparison, and confident claims of objective artistic merit. Research on literary translation found mechanical evaluation criteria and automatic metrics often misjudge creative human translation; reader/professional preference matters [P6]. G-Eval also reports possible self-preference in model judges [P7].
   - Tests: (a) good unconventional prose is not automatically called grammatically defective; (b) a conventional genre draft is not penalized for not being experimental; (c) an intentional dialect is not normalized unless asked; (d) critiques of professional human and machine-generated variants are authorship-blinded.
5. **Controlled comparative-review protocol.** When comparing alternatives, evaluate A/B and B/A (randomized order), hide authorship/model labels, and record disagreements. If winner flips with order, output an unstable result instead of decisive preference. A 2025 study directly measures position bias in judges [P5]; a poetry study showed value for randomized small-batch forced choice but used a narrow 90-poem dataset and a proxy ground truth, so do not generalize blindly [P8].
   - Tests: (a) A/B then B/A invariance; (b) self/authorship labels cannot affect ranking because they are omitted; (c) preference flip is reported; (d) human edits and overrides remain external authoritative decisions.
6. **Multilingual and historical sensitivity.** Distinguish actual source language from translation; require source passage for linguistic claims and verified external citation for historical/cultural assertions; flag uncertainty for idioms, dialect, period constraints, and cross-cultural norms. Literary translation evaluations show that literal accuracy is not equivalent to literary quality [P6]. Do not infer dialect, culture, or period from text style alone.
   - Tests: (a) bilingual passage preserves diacritics and language tags; (b) unverified historical claim is marked external/unknown; (c) non-English creative translation is not graded by English fluency criteria; (d) cultural assertion cannot be represented as a direct textual quote.

## Hostile falsifiers and release gates

> A rigid requirement to produce a criticism for every lens will reward invented defects, repetition, and confidence inflation. Show improvement on author-reviewed literary examples, not just schema completeness.

> A valid quotation proves that the words exist, not that Aeonith's interpretation is sound. Measure *entailment of observations* separately from *plausibility of interpretation* and *usefulness to the author*.

> Critique by a second model is not independent human validity. Blind authorship, reversed positions, disagreement capture, and author-controlled accept/reject are necessary before claims of improved artistic judgment.

> Research benchmark datasets are not automatically redistributable. LongStoryEval and LiteraryQA GitHub repository metadata had no detectable SPDX license at audit. The public repo must not vendor them or their source books merely because they are visible.

Recommended release language: `model-assisted literary review`, `observations and alternative readings`, not `verified expert criticism` or `objective scores`. Require at least one independently annotated sample per genre for claims about practical quality and a provider-executed demonstration before advertising live model behavior.

## Public GitHub repositories inspected (source licenses and exact heads)

| Repository | Observed main HEAD | GitHub license metadata | Recommendation |
|---|---|---|---|
| [DingyiYang/LongStoryEval](https://github.com/DingyiYang/LongStoryEval) | `ffc0c052664be345090a57b718fabc14b92c8136` | none detectable | Read paper/design; do not copy repository code/dataset/books without permission |
| [SapienzaNLP/LiteraryQA](https://github.com/SapienzaNLP/LiteraryQA) | `d80898bcfa91f9e968b7bb47086ef8fe005c61a0` | none detectable | Borrow benchmarking ideas only; repo says books are obtained by external script, not distributed as text |
| [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) | `3952947fe19838d23d15146e81b71049142b68f4` | MIT | Optional future independently versioned eval-runner adapter; too much weight for first MVP |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | `5582f347bbc5359b201ce2d48c9c7fbebd8dcbd9` | MIT | Optional prompt red-team/CI regression matrix, not a runtime dependency |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | `90e230cbe916c73240a48312c494065a39bf52d1` | Apache-2.0 | Optional model-judge quality checks with documented judge bias |
| [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | `25162c4fc05c2d2d019b0ffb5b6b2a9f315ec007` | MIT | Consider *later* for prompt optimization against human examples, not to replace owner GPT instructions |

This is repository metadata and architecture research only. No dependency installation, code inclusion, benchmark execution, or Aeonith live model qualification was performed.

## Primary research references

- [P1] [KRISTEVA: Close Reading as a Novel Task for Benchmarking Interpretive Reasoning](https://aclanthology.org/2025.acl-long.1577/) (ACL 2025): 1,331 questions; studied models 49.7–69.7% accuracy; behind experienced humans on 10/11 tasks.
- [P2] [Literary Evidence Retrieval via Long-Context Language Models](https://aclanthology.org/2025.acl-short.29/) (ACL 2025): 292 manually verified examples; nuanced signals and overgeneration remain difficult.
- [P3] [What Matters in Evaluating Book-Length Stories?](https://aclanthology.org/2025.acl-long.799/) (ACL 2025): 600 books, compares aggregation, incremental and summary methods.
- [P4] [LiteraryQA: Towards Effective Evaluation of Long-document Narrative QA](https://aclanthology.org/2025.emnlp-main.1729/) (EMNLP 2025): n-gram metrics correlate poorly at the system level with human judgments; model judges can align better with ranks, with caveats.
- [P5] [Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge](https://aclanthology.org/2025.ijcnlp-long.18/) (IJCNLP-AACL 2025): position consistency, repetition stability, preference fairness.
- [P6] [How Good Are LLMs for Literary Translation, Really?](https://aclanthology.org/2025.naacl-long.548/) (NAACL 2025): literary translation criteria and assessor expertise affect judgment; simplified best-worst scheme outperformed complex MQM with student raters in that setting.
- [P7] [G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment](https://aclanthology.org/2023.emnlp-main.153/) (EMNLP 2023): improved correlation in summarization; warns possible model-generated-text preference.
- [P8] [Can Large Language Models Outperform Non-Experts in Poetry Evaluation?](https://aclanthology.org/2025.emnlp-main.1625/) (EMNLP 2025): narrow comparison finding; 90 poems, randomized forced-choice, venue-based proxy ground truth.

## Scope of results

`SOURCE`: external papers/repos were read through web/GitHub on 2026-10-31. `INFERENCE`: recommendations above. `UNKNOWN`: Aeonith's implemented/runtime effectiveness, improvement over GPT baseline, model/provider generality, actual human utility. No claim of tests passing is made here.
