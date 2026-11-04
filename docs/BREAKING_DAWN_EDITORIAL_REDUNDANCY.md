# Breaking Dawn — independent editorial redundancy, not manuscript duplication

**Status: PROPOSED / UNQUALIFIED.** This document establishes a second *review method* for the author-controlled fictional novel *Breaking Dawn*. It does not claim that a local model has reviewed the novel, that any reviewer has validated its prose, or that Aeonith possesses an up-to-date manuscript.

## Decision and ownership

**Primary creative authority:** the author and the private canonical manuscript repository. Aeonith is a *critic*, not an alternate canonical writer or a mirrored storage location. If the writing session or model loses context, recover it from the author's authorized private source—not from this public repository.

**Redundancy here means:** an independently runnable, source-exact editorial checkpoint that challenges the primary writer's assumptions, preserves a stable **public, spoiler-light evaluation method**, and can be performed by a different model or human with the author's explicit permission and a specific manuscript revision. A second model's agreement is not independent factual verification.

Do **not** copy the manuscript, private outline, trauma source records, private character histories, unpublished excerpts, identities, or source hashes into Aeonith's public repo, GitHub issues, CI artifacts, or examples. This document contains no private source text.

## Author-specified criteria, abstracted into a reusable protocol

| Gate | What the reviewer should test | What would falsify it |
|---|---|---|
| First-person immersion | Sustained, believable internal `I` viewpoint with room for readers to recognize their own motives | Third-person/head-hop explanations; formulaic self-help narration |
| Invisible anonymity | The narrator's given name is never necessary or signaled as withheld; most unprimed readers should not notice omission | Conspicuous refusals to give a name, redactions, clues, identity-reveal setups |
| Modern lived voice | A distinctive, fallible voice appropriate to a person living in the present, not decorative pseudo-medieval prose | Antique phrasing unrelated to character; time-period clichés without observation |
| Identification without blandness | Specific contradictions, anger, empathy, fallibility, humor and unflattering choices invite recognition | Generic blank-slate narrator; uniform moral correctness; exposition substituting for action |
| Three-act progression | Descent, behavioral reckoning, perceptual expansion each change external circumstances and the narrator's decisions | Relabeling the same didactic encounter as a new realm |
| Scene causality | Every major scene has an aim, resistance, costly choice and lasting consequence | Interchangeable episodes; logistics and paperwork endlessly postponing conflict |
| Independent characters | Recurring companions, adversaries and loved ones have goals outside the narrator's lesson | Others exist only to pardon, punish, explain, or die for the protagonist |
| Grief and moral complexity | Boundaries, justified protective anger and accountability survive growth; forgiveness is not compelled | Victim blame; moralizing reconciliation; effortless cure or instant sainthood |
| Unresolved reality | Open interpretation is narratively earned; testimony never becomes unsupported medical or metaphysical certainty | An asserted diagnosis, specific toxicology or final supernatural proof unsupported by the scene |
| Source fidelity | Every critique claim is anchored in the exact submitted text and its version | Invented chapters, recurrences, unseen motives, or textual quotations |

The criteria are **editorial questions**, not deterministic evidence that a manuscript succeeded. A validator can audit quote exactness and response structure; it cannot establish that a reader identifies with the narrator or that the prose is exciting.

## Separate review lanes

### Lane A — mechanical integrity (no model)

1. Require explicit author authorization and the exact **local** revision being reviewed. Record a local file name/version outside the Aeonith checkout.
2. Process bounded excerpts using Aeonith's existing source/evidence tools. Preserve source offsets when available; do not claim that excerpts establish whole-book continuity.
3. Check requested review-lens coverage, exact quotations, duplicated output, reported provider state, and refusal/failure conditions through the existing `evaluation/quality_eval.py` contract. A clean result says **structurally valid**, not **literarily good**.
4. Record `NOT ASSESSED` for any unobserved chapter, unknown author context, or unrun model/human review.

### Lane B — adversarial critical reading (explicit opt-in)

1. Provide one bounded passage to a separately selected, authorized reviewer. Where a local model is used, the operator must explicitly configure a local endpoint and approve disclosure. No external hosted model by default; no spending.
2. Request (i) strongest narrative case, (ii) falsifiers, (iii) reasons the reader could disengage, (iv) specific line-level evidence, and (v) uncertainty. Disagreement is an expected result.
3. Ask a human reader **unprimed** about the narrator's credibility, emotional identification, boredom and unanswered questions. Do not mention the unnamed-narrator device before the first response; use `evaluation/BLIND_READER_IMMERSION_CARD.md`.
4. Preserve model, provider/runtime, requested lenses, exact source version, input scope and reviewer status in **private operator custody**. Do not upload private text or raw findings to public CI/logs.
5. Feed only narrowly justified changes back to the private manuscript's author/maintainer. Aeonith cannot canonize a change on its own.

### Lane C — recovery if the primary writer fails

Rehydrate **from author-controlled private custody**: approved creative constitution, current outline, exact manuscript revision and canonical decision log. Re-run Lane A, then a new Lane B. If any source is missing, mark it `UNKNOWN` rather than creatively filling gaps. Aeonith's public documents serve only as an independent rubric, **not** as an alternate copy of the manuscript.

## Existing capabilities and limits

- `docs/READER_WORKFLOW.md`: local, explicit-provider review with a genuine provider failure instead of invented critique.
- `docs/LONGFORM.md`: bounded excerpt planning; no automatic whole-book comprehension.
- `docs/SOURCE_ANCHORS.md`: exact source quoting; presence of a quote is not proof an interpretation is true.
- `evaluation/README.md`: structured literary evaluation; `semantic_quality` remains unassessed by the deterministic auditor.
- `docs/LITERARY_QUALITY_GATE.md`: proposal for synthetic evaluation, **not** a qualification certificate.
- Draft PR #20 develops additional long-form and model capabilities; they are **unmerged** and must not be treated as production functionality.

**Current evidence:** author brief and repository-source inspection only. No manuscript passages uploaded, no critique model invoked, no blind readers recruited, no quality pass issued.
