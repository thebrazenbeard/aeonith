# Qwen3.5 SFT label gate — source candidate, not training evidence

The Aeonith LoRA trainer uses conversational prompt/completion records and
`SFTConfig(completion_only_loss=True, packing=False)`. In pinned
[TRL v1.17.1](https://github.com/huggingface/trl/blob/v1.17.1/trl/trainer/sft_trainer.py),
`SFTTrainer._prepare_dataset` builds each row's `labels` using its
completion mask, and the default language-modeling collator uses those prepared
labels. Merely asserting the configuration flag would not prove the actual
loss-bearing token mask.

`training.train_lora.verify_sft_trainer_supervision` is now an additional
**pre-optimizer, fail-closed contract**. On a genuine initialized
`SFTTrainer`, for every train/validation record it:

1. Recomputes the full exact user+assistant chat token sequence and the prompt
   ending with the assistant generation marker.
2. Requires that the prompt is a strict prefix; refuses token-boundary drift.
3. Reads the trainer's **actual prepared** dataset `input_ids` and `labels`,
   rejecting omissions, reorderings, truncation, prompt leakage or lost
   completion supervision.
4. Calls the trainer's **actual configured collator** on the prepared record,
   verifying that the effective batch preserves all token IDs and labels,
   and any padded positions are not supervised.
5. Verifies the effective **attention mask**: every real prompt and completion
   token must be attended (`1`); every padded position must be hidden
   (`0`). Missing/malformed attention masks fail closed. The pinned
   `packing=False`, padded CPU recipe must not silently switch to
   `padding_free`/position-IDs-only semantics.
6. Returns aggregate counts only, with
   `status=sft_labels_verified_not_trained`. The result can enter an eventual
   receipt only after a genuine downstream optimizer result.

The complete probe must run **before** the call to `trainer.train()`; it is
not a pretext to bypass the existing private-output broker or corpus admission
gates. Synthetic-only, pure-unit adversarial checks cover the failure modes
without loading Qwen weights, using private corpus bytes, or running an
optimizer.

## Evidence limits

This source package has NOT executed a real `SFTTrainer` under its installed
TRL 1.17.1 wheel. The scratch environment has no `torch`, `trl`,
`datasets`, `transformers` or `peft`. Successful fake-trainer unit tests
verify only the refusal logic, not runtime integration. A future host-owned,
approved corpus+output-safe trainer run must exercise the actual path and
record an exact model/TRL/transformers revision, source head, and process
resource/output custody before claiming any neural weight update.

> Hostile challenge: prepared labels and one-sample collator outputs may be
> correct while optimizer hooks, packing overrides, a different data-loader
> collator, or downstream model loss code changes effective gradients. This
> gate proves neither generalization nor causal training. Retain independent
> reload and blinded evaluation requirements.
