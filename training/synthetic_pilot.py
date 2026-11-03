"""Deterministic, *unadmitted* original synthetic literary critique proposals.

This prepares a small, inspectable training candidate. It deliberately does
not produce self-authorship declarations, permissions, trainer files, adapters,
or approval receipts. An LLM-created passage is not a human's sworn original.
"""

from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
from typing import Any

from aeonith.private_output import create_private_directory
from evaluation.quality_eval import CANONICAL_LENSES, audit_review
from .admit_candidates import _candidate_rows
from .corpus import SPLITS, _check_isolation
from .corpus_admission import _normalized, _shingles, _words


# Every sentence below was freshly composed for the synthetic smoke-test
# generator. All characters, settings and incidents are invented, and no
# real/user manuscript or public evaluation item is imported. The fixed
# index/split assignment prevents a rerun from silently moving a work between
# training and evaluation. These examples are *not* independent human labels.
# Each card: passage, exact quote, tentative interpretation, counterreading,
# and a specific unresolved fact. Keep each quote literally inside the passage.
_TRAIN_A = (
    ("The pier keeper kept an unlit lantern beside the foghorn. Every departure was entered in the book, but the column for arrivals remained blank.", "unlit lantern", "The unused light may figure an institution unwilling to welcome arrivals", "It might simply be a spare lamp", "We do not know whether any ships arrived"),
    ("At supper, Meren set an empty cradle at the head of the table. Nobody mentioned it, although everyone moved their plates to make room.", "empty cradle", "The meal makes absence socially present without naming its cause", "The family may be storing the cradle temporarily", "The absent child is never identified"),
    ("The tax clerk filed her own unpaid receipt behind a row of sealed envelopes. She signed every other ledger with a flourish, but left hers unsigned.", "left hers unsigned", "Selective formality may reveal a conflict between office and personal responsibility", "A routine clerical error fits the same evidence", "The amount due is not stated"),
    ("At the last train, the conductor gave a long whistle into an empty platform. Across the tracks, a dog rose as though it recognized a name.", "long whistle", "The departure ritual persists even when its human audience has vanished", "Railway safety practice may require the signal", "The dog's reaction cannot be translated into intention"),
    ("Each midnight the village clock lost one minute. The baker began opening earlier while the schoolmaster insisted the hours were unchanged.", "lost one minute", "Timekeeping becomes a dispute about who may define an ordinary day", "An unreliable mechanism can explain the entire quarrel", "Neither speaker's motive is shown"),
    ("Iona painted a narrow bridge on the wall of her room. At dawn she stepped around the painting rather than walk across the floor beneath it.", "stepped around the painting", "An imagined boundary shapes a physical decision", "She may be protecting wet paint", "Her private reason remains unspoken"),
    ("The rain arrived after the parade had ended. A child kept marching beneath the awning, holding a paper banner whose ink now ran blue.", "ink now ran blue", "The damaged banner registers persistence after public celebration", "The child may simply enjoy marching", "The banner's message is unreadable"),
    ("At harvest the orchard owner counted seventeen pears and gave none away. That evening she left the gate open beside a handwritten sign reading TAKE WHAT FALLS.", "TAKE WHAT FALLS", "The written rule distinguishes generosity from surrendering control", "The sign may chiefly prevent spoilage", "No visitor is described"),
    ("The bell sounded once during the ceremony and then cracked. The officiant completed the vows without a pause; the guests watched the broken rope.", "watched the broken rope", "Attention shifts from official ritual to its damaged instrument", "Guests might only worry about a falling fixture", "The couple's reaction is absent"),
    ("The teacher erased the chalk sentence before anyone could copy it. Later, each pupil wrote a different ending in the same notebook margin.", "different ending", "The missing lesson may invite competing accounts rather than obedience", "The exercise could have been planned", "We cannot recover the erased sentence"),
    ("In the shop mirror, Ada saw the sign behind her printed backward. She turned and read the window correctly, then returned to the reflection.", "returned to the reflection", "The doubled perspective stages a choice between display and mediation", "She may be testing the mirror", "Her interpretation is not stated"),
    ("The mayor's ledger listed every fallen tree under the heading IMPROVEMENT. A gardener quietly marked the same names on paper scraps and planted saplings.", "heading IMPROVEMENT", "Administrative language may conceal a material loss", "The heading might refer to a genuine clearing plan", "No tree's condition is described"),
    ("A potter repaired the chipped cup with red clay rather than matching its white glaze. She placed it among the newest pieces, facing the seam outward.", "seam outward", "Visible repair resists an ideal of seamless novelty", "The color choice may be purely economical", "No buyer is heard"),
    ("The navigator's map ended at a penciled shore. Her apprentice copied the blank half onto a new sheet and labeled it HOME.", "labeled it HOME", "The apprentice turns absence of mapped knowledge into attachment", "It may be a private shorthand for a planned route", "The destination is unverified"),
)

_TRAIN_B = (
    ("The machinist polished a brass switch that no longer powered anything. On inspection days, he stood before it and waited for a click.", "waited for a click", "A gesture outlives the machine's former purpose", "He could be testing a replacement circuit", "The switch's history is withheld"),
    ("After the council voted, a missing chair remained at the oval table. Every speaker addressed the gap before asking a question.", "addressed the gap", "Physical absence changes the choreography of public speech", "The chair may await a late delegate", "We do not learn why it was removed"),
    ("The ferry crossed the harbor without passengers. Its captain still announced each stop, though only the radio answered with static.", "announced each stop", "Repetition preserves a public role after its audience disappears", "Announcements may be legally required", "The empty crossing's cause is unknown"),
    ("An archivist spilled green ink on a list of erased names. She did not recopy the list; she placed the stained sheet at the front of the folder.", "stained sheet", "The material trace of damage becomes part of the record", "She might lack fresh paper", "We do not know who erased the names"),
    ("The mason leaned a ladder against an unfinished arch. When the workers left, a visitor stood beneath the span and whispered that the doorway was complete.", "doorway was complete", "The visitor grants completion through use rather than construction", "The statement might be a joke", "The design remains unknown"),
    ("During the blackout, a violinist played one note repeatedly. People stopped searching for candles and listened until the power returned.", "one note repeatedly", "A minimal performance redirects collective attention during uncertainty", "The note may be part of an ordinary warm-up", "No listener explains the silence"),
    ("A surveyor buried her compass under a cedar and walked north by the color of moss. At the ridge she drew a new arrow pointing behind her.", "pointing behind her", "The turned arrow questions whether orientation is a fixed reference", "She may simply mark the return path", "The destination is undisclosed"),
    ("The postmaster carried a bundle of undeliverable letters through the village square. He read no names aloud but kept each envelope facing outward.", "each envelope facing outward", "Unread correspondence becomes a public display of interrupted connection", "He might be seeking updated addresses", "The letters' contents remain private"),
    ("The fountain stopped flowing the day the factory reopened. Neighbors stood around the dry basin and argued whether silence counted as an improvement.", "dry basin", "The basin becomes a measure of competing civic priorities", "A broken pump may explain the drought", "No water records appear"),
    ("A seamstress replaced the governor's gold button with a wooden one. At the banquet he left the coat fastened and thanked her by name.", "wooden one", "A modest object complicates the hierarchy signaled by formal clothing", "The change may be a practical repair", "His gratitude does not reveal an ideology"),
    ("Dust settled over the museum's model city while the full-size streets outside were repaved. The curator moved a tiny crane without changing its label.", "without changing its label", "The exhibit freezes one claim about a city that continues to change", "The label may already be accurate", "The crane's original role is unclear"),
    ("In the attic tapestry a blue river ended before reaching the sea. A visitor traced the final stitch and asked where the missing water went.", "final stitch", "The artwork's abrupt boundary prompts interpretation through omission", "The maker may have run out of thread", "No maker's explanation survives"),
    ("The botanist planted a single seed in a cracked teacup and wrote the species name on the saucer. By spring, the label had washed away.", "label had washed away", "The living specimen escapes the certainty promised by classification", "The fading ink may be incidental", "Its species cannot be inferred here"),
    ("The apprentice copied the warning onto slate, then rubbed out the word NEVER. His master read the shorter instruction without comment.", "rubbed out the word NEVER", "Deleting a prohibition transforms the force of the rule", "He could be correcting an accidental word", "The master offers no judgment"),
)

_VALIDATION = (
    ("Inside the greenhouse, Leora pinned a dead moth beside a flowering branch. She recorded the branch's growth but not the specimen's date.", "not the specimen's date", "The record privileges one sort of change while withholding another", "The date might be written elsewhere", "The moth's history is absent"),
    ("A winter courier delivered a warm stone to the empty observatory. The astronomer placed it under a blanket instead of examining it.", "under a blanket", "An act of care interrupts a supposedly observational role", "The stone might be a temperature sample", "The courier's purpose is unknown"),
    ("The locksmith wrote a code on the underside of a tin spoon. When questioned, he offered the spoon to a stranger without explanation.", "underside of a tin spoon", "Secret information is carried by an ordinary utensil", "The code could be a workshop inventory mark", "Its meaning is not disclosed"),
    ("Kelp wrapped the lighthouse steps after the storm. The keeper climbed over it carrying a basket of dry matches to an extinguished stove.", "basket of dry matches", "The keeper's priority turns inland while a coastal warning system remains obscured", "He may have already repaired the light", "The lighthouse status is unknown"),
    ("A judge folded the paper verdict into a small boat. It floated only as far as the edge of her desk before collapsing.", "small boat", "The verdict's new shape unsettles the apparent finality of judgment", "She could be disposing of scrap", "The case is never named"),
    ("The door's hinge squealed whenever the gardener entered the library. One morning he oiled it and nobody looked up from their books.", "nobody looked up", "The vanished sound reveals how a nuisance had become a communal signal", "Readers may simply be engrossed", "Their awareness cannot be established"),
    ("After the feast, the baker cut a loaf in half and put both portions on the windowsill. She locked the shop and walked away hungry.", "walked away hungry", "A possible gift conflicts with the maker's immediate need", "The loaf might be cooling", "No intended recipient appears"),
)

_HOLDOUT = (
    ("A tide chart hung in the abandoned theatre. Each night the caretaker changed the numbers though the town lay fifty miles from the shore.", "changed the numbers", "Persistent updates make an absent ocean govern the theatre's routine", "He could be rehearsing a seafaring play", "No production schedule is given"),
    ("The singer tied a violet ribbon to an empty microphone stand. At rehearsal she addressed the knot instead of the audience.", "addressed the knot", "An object receives attention normally reserved for listeners", "She may be practicing sight lines", "The ribbon's origin is unknown"),
    ("A single lamp remained lit in the abandoned schoolhouse. Every Friday a former pupil replaced its battery and left without entering.", "left without entering", "Care for the light coexists with refusal to revisit the room", "The light may be a safety marker", "No motive for staying outside is supplied"),
    ("The sculptor found a flat stone with a hole drilled through it. Rather than hang it, he laid it beneath a dripping tap and counted the drops.", "counted the drops", "A display object becomes an instrument for measuring duration", "He might be testing a repair", "Its maker is unidentified"),
    ("A moth crossed the projection beam and eclipsed the heroine's face. Nobody paused the film; afterward the audience recalled the shadow more vividly.", "recalled the shadow", "An accidental interruption competes with the planned image", "The incident may merely be memorable because it was rare", "No viewer's detailed interpretation is heard"),
    ("The weaver knotted a red thread around the mayor's public promise. On the following morning the note had disappeared but the knot remained.", "knot remained", "A physical mark outlasts the words it was meant to bind", "Wind or cleaning may explain the missing note", "The actual promise is unrecorded"),
    ("In the salt store, an apprentice labeled every bag SWEET. His supervisor crossed out one label and left the other sacks untouched.", "labeled every bag SWEET", "Misnaming makes routine authority look selective", "The tags may be an agreed private code", "The supervisor's selection criterion is not provided"),
)

_CARDS = {"train": _TRAIN_A + _TRAIN_B, "validation": _VALIDATION, "holdout": _HOLDOUT}


# Each note interprets the specific quoted passage *through its assigned lens*.
# These are synthetic teaching targets, not expert-rated literary judgments.
# In particular, no history, genre affiliation, intention or psychology beyond
# the little passage is asserted as fact. Index order is fixed across releases.
_LENS_NOTES = {
    "train": (
        "The keeper's unused lantern invites a psychological hypothesis about reluctance to welcome arrivals, while leaving the keeper's inner life inaccessible",
        "The unused cradle brings silence and absence into one domestic ritual, creating a theme of grief that the narrator does not explain",
        "The unsigned receipt interrupts the preceding series of signed accounts, giving the vignette a structural reversal rather than a resolved ending",
        "The conductor's persistent signal discloses a dutiful habit, but the brief episode offers no earlier self against which to measure character change",
        "The baker's altered working hour and the schoolmaster's denial pit labor against institutional timekeeping, though no particular historical era is supplied",
        "Iona's avoidance of a painted bridge asks whether an imagined division can have real practical force even when no physical obstacle exists",
        "The parade's abandoned banner and dissolving ink make this aftermath vignette resemble a miniature fable with an ambiguous emblem instead of a stated moral",
        "The uppercase command TAKE WHAT FALLS sits against the exact count of seventeen pears, a stylistic contrast between terse permission and meticulous possession",
        "The guests' shared gaze at a damaged rope departs from the officiant's uninterrupted vows, suggesting a group's attention can diverge from official ritual",
        "Erasing a lesson before pupils can copy it raises an ethical question about fair access to knowledge, without proving the teacher intended harm",
        "Ada's return to the reversed shop sign lets the mirror function as a symbol of mediated perception rather than a transparent view",
        "Readers may distrust the euphemistic heading IMPROVEMENT after encountering the gardener's quiet counterrecord, though another reading could credit the mayor",
        "The clause 'rather than matching its white glaze' sets up a linguistic opposition between concealing damage and displaying a repair",
        "The navigator's unfinished map and the apprentice's HOME label offer competing ways to read unmapped territory: absence of knowledge or chosen belonging",
        "Waiting for a dead switch to click makes the machinist's ritual an external clue to possible attachment, never direct access to his thoughts",
        "An absent chair alters every speaker's address, returning the theme of presence-through-absence at each turn of the debate",
        "The repeated announcements along an empty ferry route build expectation until the final radio static answers the captain with a structural nonreply",
        "The archivist's refusal to make a clean copy may express a preference for damaged evidence, but this choice alone is not a full character arc",
        "A worker's unfinished arch and a visitor's claim of completion contrast craft standards with public use; no historical building custom is established",
        "The single note's power to halt a search asks a philosophical question about whether attention can create a form of value during uncertainty",
        "The buried compass and backward arrow give the surveyor's journey the shape of a quest-parable whose ending reverses an expected direction",
        "The parallel withholding of spoken names and public display of envelopes is a stylistic contrast between silence and visibility",
        "The neighbors' dispute over the factory and dry fountain stages a conflict about common resources and who has authority to name improvement",
        "The governor's spoken thanks raises an ethical question about recognizing the seamstress's labor rather than proving that hierarchy has vanished",
        "An unmoving miniature city next to changing streets makes its outdated label a symbol of the distance between representation and lived place",
        "The visitor's question at the tapestry's final stitch invites readers to imagine an absent continuation without granting them knowledge of the maker's plan",
        "A species label disappearing while the seed grows distinguishes a linguistic name from the living referent it attempts to classify",
        "Comparing the warning before and after NEVER is rubbed out reveals how one small deletion can reverse the force of an instruction",
    ),
    "validation": (
        "The omission of the moth's date may invite psychological speculation about avoidance, but the botanist's feelings remain unspoken",
        "The warm stone under a blanket connects the competing themes of care and scientific observation without resolving which governs the gesture",
        "The hidden code is first located and then passed to a stranger, with the final refusal to explain withholding a narrative answer",
        "The keeper's choice to carry matches toward a stove shows an immediate priority, not proof of permanent character transformation",
        "The judge's paper verdict invokes the cultural authority of formal judgment, though no court, jurisdiction or historical practice is identified",
        "The absent squeak asks a philosophical question about how ordinary signals gain meaning through habitual attention",
        "The baker's hunger and unclaimed halves give the short scene the shape of an unresolved moral parable rather than a conventional explanation",
    ),
    "holdout": (
        "The precise phrase fifty miles from the shore jars against nightly tide updates, a stylistic mismatch between measured distance and persistent ritual",
        "The performer addressing a ribbon instead of listeners momentarily reverses the social roles of stage, audience and symbolic addressee",
        "The former pupil's upkeep of the lamp raises an ethical question about duty to memory while withholding any obligation to reenter the school",
        "The drilled stone placed beneath dripping water becomes a symbol of duration in place of an expected hanging sculpture",
        "The spectators remembering a moth's shadow more vividly than the film asks how an audience's accidental experience reshapes the work it receives",
        "The disappeared note and remaining knot distinguish the words of a public promise from a surviving nonverbal sign",
        "Comparing the supervisor's single correction with the many untouched SWEET labels exposes two conflicting acts of classification in the same store",
    ),
}


def _target(lens: str, quote: str, reading: str, counter: str,
            uncertainty: str, lens_note: str) -> dict[str, Any]:
    support = {"source": "work", "quote": quote}
    return {
        "lens_reviews": [{
            "lens": lens, "analysis": lens_note + ". " + counter + ".",
            "basis": "textual", "support": [support],
            "limitations": ["The scene is too brief to resolve: " + uncertainty],
        }],
        "synthesis": reading + ". " + lens_note + ".",
        "challenges": [{"text": counter + ".", "support": [support]}],
        "uncertainties": [uncertainty + "."],
        "assessment": None,
    }


def build_candidate() -> dict[str, Any]:
    """Return immutable-in-content proposal only, with *no* rights approval."""
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        for index, (passage, quote, reading, counter, uncertainty) in enumerate(_CARDS[split]):
            lens_index = (index if split != "holdout" else index + 7) % len(CANONICAL_LENSES)
            lens = CANONICAL_LENSES[lens_index]
            identifier = f"synth-lit-{split}-{index:03d}"
            rows.append({
                "id": identifier, "source_id": f"source-{identifier}",
                "split": split, "genre": "original artificial microfiction",
                "lens": lens, "passage": passage,
                "target": _target(lens, quote, reading, counter, uncertainty,
                                  _LENS_NOTES[split][index]),
                "draft_status": "REVIEW_PENDING",
            })
    proposal = {
        "schema_version": "aeonith.candidate_corpus.v1",
        "status": "REVIEW_PENDING_NOT_TRAINABLE", "examples": rows,
        "generator_provenance": {
            "origin": "model_generated_synthetic",
            "generator": "ChatGPT",
            "third_party_text_used": False,
            "human_authorship_claimed": False,
            "publication_authorized": False,
        },
    }
    validate_candidate(proposal)
    return proposal


def validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Fail on structural defects or visible lexical leakage; not semantic proof."""
    # Existing older adapter admission accepts only three top-level fields;
    # the new synthetic-only approval mode adds a fourth. Check it here while
    # the separate admission implementation is independently reviewed.
    provenance = candidate.get("generator_provenance")
    if provenance != {
        "origin": "model_generated_synthetic", "generator": "ChatGPT",
        "third_party_text_used": False, "human_authorship_claimed": False,
        "publication_authorized": False,
    } or set(candidate) != {"schema_version", "status", "examples", "generator_provenance"}:
        raise ValueError("original synthetic generation provenance missing or inconsistent")
    rows = _candidate_rows({key: candidate[key] for key in ("schema_version", "status", "examples")})
    provisional: dict[str, list[dict[str, str]]] = {split: [] for split in SPLITS}
    passages: dict[str, list[str]] = {split: [] for split in SPLITS}
    for row in rows:
        split = row["split"]
        passage = row["passage"]
        target = row["target"]
        report = audit_review(
            {"schema_version": "aeonith.review.v1", "work": {"text": passage}, "lenses": [row["lens"]]},
            {"schema_version": "aeonith.review.v1", "status": "completed", **target},
        )
        if report["structural_status"] != "pass":
            raise ValueError("synthetic proposal includes unsupported quote/lens output")
        passages[split].append(passage)
        provisional[split].append({
            "id": row["id"], "source_id": row["source_id"],
            "prompt": passage, "completion": json.dumps(target, ensure_ascii=False),
        })
    _check_isolation(provisional)
    split_sets = {split: [(_normalized(p), _shingles(p), _words(p)) for p in passages[split]]
                  for split in SPLITS}
    for first_index, first in enumerate(SPLITS):
        for second in SPLITS[first_index + 1:]:
            for first_text, first_grams, first_words in split_sets[first]:
                for second_text, second_grams, second_words in split_sets[second]:
                    intersection = len(first_grams & second_grams)
                    union = len(first_grams | second_grams)
                    if (first_text == second_text
                            or (intersection >= 3 and union and intersection / union >= 0.65)
                            or (6 <= len(first_words) <= 64 and 6 <= len(second_words) <= 64
                                and abs(len(first_words) - len(second_words)) <= max(len(first_words), len(second_words)) * 0.2
                                and len(set(first_words) & set(second_words)) >= 0.75 * min(len(set(first_words)), len(set(second_words)))
                                and SequenceMatcher(None, first_words, second_words, autojunk=False).ratio() >= 0.9)):
                        raise ValueError("synthetic proposals are near-duplicate across splits")
    return {
        "schema_version": "aeonith.synthetic_candidate_check.v1",
        "status": "review_pending_not_admitted_or_trained",
        "split_counts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "lenses_by_split": {
            split: sorted({row["lens"] for row in rows if row["split"] == split})
            for split in SPLITS
        },
        "lexical_leakage_screen": "bounded_pass_not_semantic_proof",
        "evaluation_independence": "not_established",
        "rights_holder_attestation": "not_provided",
        "adapter_publication_authorized": False,
        "human_editorial_review": "not_performed",
        "actual_optimizer_steps": 0,
    }


def _serialized(candidate: dict[str, Any]) -> bytes:
    return (json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def create_private_candidate(destination: str | Path) -> dict[str, Any]:
    """Create NEW private Linux directory, containing only unapproved proposal."""
    proposal = build_candidate()
    raw = _serialized(proposal)
    result = validate_candidate(proposal)
    result["candidate_sha256"] = hashlib.sha256(raw).hexdigest()
    result["generator"] = "training.synthetic_pilot.v1"
    with create_private_directory(destination) as private:
        private.write_bytes("candidates.json", raw)
        private.write_text("generation_receipt.json", json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate unadmitted original synthetic literary-criticism candidates")
    parser.add_argument("--output", required=True, help="NEW private owner-owned directory on qualified Linux filesystem")
    args = parser.parse_args(argv)
    try:
        result = create_private_candidate(args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
