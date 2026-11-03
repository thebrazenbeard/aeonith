# Private human-rating workflow (offline, source-only)

`evaluation.human_rater_cli` collects complete, **human-entered** A/B rubrics,
binds each to the exact prepared blind display, and assembles private study
bundles. It makes **no model calls** and cannot prove that a human read the
display, that two pseudonyms are independent humans, that they consented, or
that the reported model comparison genuinely ran.

The commands below are intended for a Linux machine or **WSL with private
files on its Linux-native filesystem** (for example a 0700 directory beneath
the user's Linux home), not a Windows/OneDrive/mounted `/mnt/c` directory.
Native Windows private-file handling still fails closed; Python on Windows
and WSL on Windows are different runtime and filesystem security boundaries.
The collector additionally checks Linux `/proc/self/mountinfo` and refuses
known Windows/remote mounts (`9p`, `drvfs`, network/FUSE types), even where
POSIX-looking mode bits are emulated. Unknown mount types fail closed. This
source check cannot independently certify an underlying host storage stack.

1. Privately preregister the holdouts, rights, frozen base and adapter IDs,
   settings, and exact seeds. Run `paired_model_bench prepare` using approved
   locally generated results, producing `pairs/*.json`, `keys/*.json`, and
   `bench_receipt.json` in new owner-private directories. Do not expose `keys/`
   to raters or publish any of these private files.
2. Each consenting rater opens a corresponding `pairs/*.json` privately in a
   trusted local viewer. The collector itself **never prints the passage or
   critique prose**, even to an interactive terminal. Keep screenshots,
   terminal capture, automated transcription and synchronization off. The
   rater confirms which exact pair ID and SHA-256 they read, then enters six
   0/1/2 A/B dimensions, an A/B/tie/incomparable preference, and rationale.
3. In an interactive terminal (never a redirected/logged one), run for each
   independent participant, choosing a **different new output filename**:

   ```bash
   python -m evaluation.human_rater_cli rate \
     --pair /private/study/pairs/run-id.json \
     --out /private/ratings/rater-one-run-id.json
   ```

   Only pair ID, hash, prompts and a text-free saved receipt appear in terminal
   output. The private rubric file is exclusively created with owner-only 0600
   permissions through the existing descriptor-pinned POSIX writer. A
   noninteractive session fails before reading the pair. A cancellation or bad
   rating creates no output. No previously existing file is overwritten.
   The TTY check only blocks obvious pipes; it **cannot detect terminal
   recording or prove the person or their consent**. Protect the viewing
   environment separately.
4. Assemble the exact displays and completed bound rubrics. First create a
   private 0600 UTF-8 JSON manifest outside Git with this structure, listing
   every eligible pair (including missing/failed-to-rate pairs with an empty
   annotation list):

   ```json
   {
     "schema_version": "aeonith.human_study_file_manifest.v1",
     "records": [
       {
         "pair_file": "/private/study/pairs/run-id.json",
         "bound_annotation_files": [
           "/private/ratings/rater-one-run-id.json",
           "/private/ratings/rater-two-run-id.json"
         ]
       }
     ]
   }
   ```

   Then run:

   ```bash
   python -m evaluation.human_rater_cli assemble \
     --manifest /private/ratings/manifest.json \
     --out /private/ratings/whole-study.json
   python -m evaluation.paired_model_bench study-coverage \
     --receipt /private/study/bench_receipt.json \
     --study /private/ratings/whole-study.json
   ```

   Assembly reads only owner-private regular files through pinned parent
   directory handles, rejects symlinks (including ancestor components),
   duplicate JSON fields, modified A/B displays, duplicate pseudonyms per
   pair, malformed ratings and overlarge files. Assembly rejects more than
   4,000 annotation references **before reading** and limits the aggregate
   JSON input to 16 MB, avoiding a multi-gigabyte accumulation from thousands
   of individually small files. The resulting complete study
   bundle contains **private manuscript and rationale text** and must remain
   outside Git and public logs. The CLI's returned summary never contains
   private prose or pseudonyms. Pair IDs and hashes can still be linkable.

5. Review coverage before unlocking candidate keys. The validator reports
   missing ratings, run/seed denominators, ineligible runs and reviewer
   disagreement. Preserve original consent/identity evidence separately under
   authorized human custody. Independently review source rights, blinding,
   leakage and rater independence before considering any quality conclusion.

## Evidence ceiling

- Unit tests use synthetic scripted answers. They are **not** real human
  judgments and cannot qualify literary quality.
- `OPERATOR_DECLARED_ANNOTATION_SAVED` means a local bound rubric was stored;
  `OPERATOR_DECLARED_STUDY_ASSEMBLED` means source and rubric records were
  consistent. Neither is identity authentication or a signed viewing receipt.
- A green structural audit, two pseudonyms, identical responses across seeds,
  or an A/B preference count is **not** evidence that an adapter improved
  literary insight. Authentic human ratings, provenance and an independently
  sequestered holdout are still required.
- Native Windows private writes remain disabled. WSL is an option only when
  its Python process runs on a suitable native Linux filesystem with the same
  POSIX protections tested by this code; mounted Windows filesystems and
  automatic synchronization are not qualified substitutes.
