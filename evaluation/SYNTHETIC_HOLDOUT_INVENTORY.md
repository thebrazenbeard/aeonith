# Synthetic holdout inventory bridge — not blind evaluation

`evaluation.synthetic_holdout_inventory.inspect_synthetic_inventory` maps the
exact, pinned 42-row synthetic proposal into the existing three-way
`split_inventory` accepted by `paired_model_bench` and `causal_control_matrix`.
It is source-only, in-memory and **text-free**. It uses the model-generated
candidate's SHA-256 to refuse a changed proposal and the existing exact
source/hash overlap validator to reject malformed split inventories.

For the 2026-11-03 VN1 pilot, the observed proposal SHA-256 is
`a3abe9eaa7749bd972654eafe671e99e5b3ce478f62a42dc066573344b4faf3a`.

```python
from evaluation.synthetic_holdout_inventory import inspect_synthetic_inventory

inventory = inspect_synthetic_inventory(
    expected_candidate_sha256="a3abe9eaa7749bd972654eafe671e99e5b3ce478f62a42dc066573344b4faf3a"
)
assert inventory["holdout_blind_qualified"] is False
```

The resulting inventory has 28 training, seven validation and seven holdout
entries containing **only** `source_id` and SHA-256 of each passage. It can
support later descriptive accounting of base, adapted and shuffled-feedback
arms across multiple seeds, but it creates **no** execution or observation
record and grants **no** corpus permission, trainer lease or score.

## Critical limitation

All synthetic passages and their target critiques are in the checked-in
`training/synthetic_pilot.py` source and in the candidate corpus. Consequently
this holdout is suitable as a smoke-test split but **not a genuinely blind,
unseen, independent literary evaluation**. Hash non-overlap cannot exclude
semantic overlap or prior model exposure. Real claims about generalized
literary quality require a separately stewarded withheld task generator or
human-supplied unseen works with proven custody, actual model executions,
fresh-process adapter reload, frozen and shuffled-feedback controls, at least
two seeds, and independent blinded review. The existing control matrix and
paired benchmark can account for declared results but do not perform those
effects or authenticate their provenance.
