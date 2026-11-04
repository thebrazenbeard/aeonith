# Literary source corpus — candidate editions, not admitted data

**Status: research inventory only.** No source passages, critiques, checkpoint
weights, or training examples are distributed here. None of these editions has
been admitted through Aeonith's private corpus or human-rights gates. A catalog
description of US public-domain status is evidence to examine, not a substitute
for validating the specific downloaded edition and local use.

The proposed split holds out entire **work families**, not merely alternate
prompts or translations of the same work. Every lens still needs distinct,
independently written and editorially reviewed critical-response labels.

| Proposed split | Source edition | Candidate lenses |
| --- | --- | --- |
| TRAIN | [Austen, *Pride and Prejudice*, Project Gutenberg #1342](https://www.gutenberg.org/ebooks/1342) | Character, psychological, sociological, stylistic |
| TRAIN | [Shelley, *Frankenstein*, Standard Ebooks 1831 revision](https://standardebooks.org/ebooks/mary-shelley/frankenstein) | Ethical, philosophical, symbolic, genre |
| TRAIN | [Wilde, *The Picture of Dorian Gray*, Project Gutenberg #174](https://www.gutenberg.org/ebooks/174) | Thematic, symbolic, philosophical, reader-response |
| TRAIN | [Douglass, *Narrative of the Life*, Project Gutenberg #23](https://www.gutenberg.org/ebooks/23) | Historical, sociological, ethical, linguistic |
| TRAIN | [Shakespeare, *Hamlet*, Project Gutenberg #1524](https://www.gutenberg.org/ebooks/1524) | Narrative structure, genre, stylistic, comparative |
| TRAIN | [Dante, *Divine Comedy*, Longfellow translation, Project Gutenberg #1004](https://www.gutenberg.org/ebooks/1004) | Comparative, philosophical, linguistic, ethical |
| DEV | [Hawthorne, *The Scarlet Letter*, Project Gutenberg #33](https://www.gutenberg.org/ebooks/33) | Symbolic, historical, ethical |
| DEV | [Eliot, *Middlemarch*, Project Gutenberg #145](https://www.gutenberg.org/ebooks/145) | Psychological, sociological, character, structural |
| HELDOUT | [Du Bois, *The Souls of Black Folk*, Project Gutenberg #408](https://www.gutenberg.org/ebooks/408) | Sociological, linguistic, philosophical, historical |
| HELDOUT | [Woolf, *Mrs. Dalloway*, Standard Ebooks](https://standardebooks.org/ebooks/virginia-woolf/mrs-dalloway) | Narrative structure, reader-response, stylistic, psychological |

## Required edition and rights custody

1. Read the **exact item** copyright/permission notice. Project Gutenberg
   distinguishes US-public-domain text from works posted under permission;
   its trademark/license terms are not the same as underlying literary rights.
   See its [permission policy](https://www.gutenberg.org/policy/permission).
2. Record immutable edition URL, downloaded-file hashes, named translator,
   edition/revision date, source notices, acquisition date, and transformations.
   Standard Ebooks describes its [US-public-domain and CC0 editorial approach](https://standardebooks.org/about/standard-ebooks-and-the-public-domain),
   which still requires edition-specific confirmation.
3. Group translations, adaptations, and revisions of the same work together
   across TRAIN/DEV/HELDOUT. *Frankenstein* 1818 and 1831 variants are one
   work family. An ancient original does not clear a newer translation; the
   identified Dante translation is specifically **Henry Wadsworth Longfellow**.
4. Obtain separately accountable rights-holder, corpus-owner, data-steward,
   and editorial decisions for the exact private material and training purpose.
   Modern introductions, criticism and annotations must be licensed separately.
5. Use [`corpus_admission.py`](corpus_admission.py) for mechanical overlap,
   provenance and exclusion checks and [`corpus.py`](corpus.py) for the training
   preflight. These tools cannot authenticate identities or prove a title was
   absent from the base model's pretraining.

**Study limit:** Work-disjoint fine-tuning does not prove genuinely unseen
knowledge. Keep evaluation tasks, author-written critical judgments and any
private manuscripts sequestered from training and prompt selection. Do not put
downloaded novels, private corpus records, or weights into this Git repository.
