"""Pre-optimizer checks against actual SFTTrainer prepared dataset labels.

Pure unit fakes exercise the Aeonith refusal contract without importing torch
or claiming an installed TRL runtime test.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from training.corpus import CorpusError
from training.train_lora import verify_sft_trainer_supervision


CORPUS = {
    "train": [{"prompt": "original scene", "completion": "specific critique"}],
    "validation": [{"prompt": "second scene", "completion": "another critique"}],
}


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict):
        assert tokenize and return_dict is False
        prompt = [101] + [ord(c) for c in messages[0]["content"]] + [102]
        if add_generation_prompt:
            assert len(messages) == 1
            return prompt
        assert len(messages) == 2
        return prompt + [201] + [ord(c) for c in messages[1]["content"]] + [202]


def prepared_records(corpus=CORPUS):
    tokenizer = FakeTokenizer()
    rows = {}
    for split, examples in corpus.items():
        rows[split] = []
        for example in examples:
            messages = [{"role": "user", "content": example["prompt"]},
                        {"role": "assistant", "content": example["completion"]}]
            full = tokenizer.apply_chat_template(messages, tokenize=True,
                                                 add_generation_prompt=False, return_dict=False)
            prompt = tokenizer.apply_chat_template(messages[:1], tokenize=True,
                                                   add_generation_prompt=True, return_dict=False)
            rows[split].append({"input_ids": full, "labels": [-100] * len(prompt) + full[len(prompt):]})
    return rows


def fake_trainer(records=None):
    rows = deepcopy(records if records is not None else prepared_records())
    return SimpleNamespace(train_dataset=rows["train"], eval_dataset=rows["validation"],
                           data_collator=FakeCollator())


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return deepcopy(self.values)


class FakeCollator:
    def __call__(self, samples):
        return {
            "input_ids": FakeTensor([sample["input_ids"] for sample in samples]),
            "labels": FakeTensor([sample["labels"] for sample in samples]),
            "attention_mask": FakeTensor([[1] * len(sample["input_ids"]) for sample in samples]),
        }


class TrainerSupervisionTests(unittest.TestCase):
    def check(self, trainer, *, corpus=CORPUS, tokenizer=None):
        return verify_sft_trainer_supervision(trainer, corpus,
                                              tokenizer or FakeTokenizer(), max_length=320)

    def test_actual_prepared_labels_for_both_splits_pass(self):
        receipt = self.check(fake_trainer())
        self.assertEqual(receipt["status"], "sft_labels_verified_not_trained")
        self.assertEqual(receipt["train"]["examples"], 1)
        self.assertGreater(receipt["validation"]["supervised_tokens"], 0)
        self.assertNotIn("trained", receipt)

    def test_prompt_leakage_is_rejected(self):
        trainer = fake_trainer()
        trainer.train_dataset[0]["labels"][1] = trainer.train_dataset[0]["input_ids"][1]
        with self.assertRaisesRegex(CorpusError, "prompt tokens"):
            self.check(trainer)

    def test_completion_tokens_missing_or_shifted_is_rejected(self):
        trainer = fake_trainer()
        trainer.train_dataset[0]["labels"][-1] = -100
        with self.assertRaisesRegex(CorpusError, "completion labels"):
            self.check(trainer)

    def test_wrong_or_reordered_dataset_refused(self):
        trainer = fake_trainer()
        trainer.train_dataset[0]["input_ids"][0] = 5
        with self.assertRaisesRegex(CorpusError, "differs"):
            self.check(trainer)

    def test_truncated_and_dropped_examples_refused(self):
        trainer = fake_trainer()
        trainer.eval_dataset[0]["labels"].pop()
        with self.assertRaisesRegex(CorpusError, "differs"):
            self.check(trainer)
        trainer = fake_trainer()
        trainer.train_dataset = []
        with self.assertRaisesRegex(CorpusError, "dropped or added"):
            self.check(trainer)

    def test_missing_labels_refused(self):
        trainer = fake_trainer()
        del trainer.train_dataset[0]["labels"]
        with self.assertRaisesRegex(CorpusError, "inspectable labels"):
            self.check(trainer)

    def test_trainer_missing_prepared_split_refused(self):
        trainer = fake_trainer()
        trainer.eval_dataset = None
        with self.assertRaisesRegex(CorpusError, "unavailable"):
            self.check(trainer)

    def test_prefix_divergence_refused(self):
        class DivergentTokenizer(FakeTokenizer):
            def apply_chat_template(self, messages, **kwargs):
                ids = super().apply_chat_template(messages, **kwargs)
                if kwargs["add_generation_prompt"]:
                    ids[0] = 999
                return ids
        with self.assertRaisesRegex(CorpusError, "exact model-context prefix"):
            self.check(fake_trainer(), tokenizer=DivergentTokenizer())

    def test_overflow_before_optimizer_is_rejected(self):
        with self.assertRaisesRegex(CorpusError, "exceeds max_length"):
            verify_sft_trainer_supervision(fake_trainer(), CORPUS, FakeTokenizer(), max_length=12)

    def test_malformed_labels_refused(self):
        trainer = fake_trainer()
        trainer.train_dataset[0]["labels"] = None
        with self.assertRaisesRegex(CorpusError, "differs"):
            self.check(trainer)

    def test_real_collator_result_must_preserve_labels(self):
        class LeakingCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                labels = result["labels"].tolist()
                labels[0][0] = samples[0]["input_ids"][0]
                result["labels"] = FakeTensor(labels)
                return result
        trainer = fake_trainer()
        trainer.data_collator = LeakingCollator()
        with self.assertRaisesRegex(CorpusError, "collator altered"):
            self.check(trainer)

    def test_real_collator_padded_supervision_refused(self):
        class BadPaddingCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                result["input_ids"] = FakeTensor([samples[0]["input_ids"] + [0]])
                result["labels"] = FakeTensor([samples[0]["labels"] + [7]])
                return result
        trainer = fake_trainer()
        trainer.data_collator = BadPaddingCollator()
        with self.assertRaisesRegex(CorpusError, "collator altered"):
            self.check(trainer)

    def test_attention_hiding_completion_is_rejected_even_if_labels_pass(self):
        class HiddenCompletionCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                attention = result["attention_mask"].tolist()
                attention[0][-1] = 0
                result["attention_mask"] = FakeTensor(attention)
                return result
        trainer = fake_trainer()
        trainer.data_collator = HiddenCompletionCollator()
        with self.assertRaisesRegex(CorpusError, "attention mask hides"):
            self.check(trainer)

    def test_attention_hiding_prompt_is_rejected(self):
        class HiddenPromptCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                attention = result["attention_mask"].tolist()
                attention[0][0] = 0
                result["attention_mask"] = FakeTensor(attention)
                return result
        trainer = fake_trainer()
        trainer.data_collator = HiddenPromptCollator()
        with self.assertRaisesRegex(CorpusError, "attention mask hides"):
            self.check(trainer)

    def test_attention_must_not_expose_padded_tokens(self):
        class ExposedPaddingCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                result["input_ids"] = FakeTensor([samples[0]["input_ids"] + [0, 0]])
                result["labels"] = FakeTensor([samples[0]["labels"] + [-100, -100]])
                result["attention_mask"] = FakeTensor([[1] * (len(samples[0]["input_ids"]) + 2)])
                return result
        trainer = fake_trainer()
        trainer.data_collator = ExposedPaddingCollator()
        with self.assertRaisesRegex(CorpusError, "attention mask hides"):
            self.check(trainer)

    def test_valid_masked_padding_passes(self):
        class ProperPaddingCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                result["input_ids"] = FakeTensor([samples[0]["input_ids"] + [0, 0]])
                result["labels"] = FakeTensor([samples[0]["labels"] + [-100, -100]])
                result["attention_mask"] = FakeTensor([[1] * len(samples[0]["input_ids"]) + [0, 0]])
                return result
        trainer = fake_trainer()
        trainer.data_collator = ProperPaddingCollator()
        self.assertEqual(self.check(trainer)["train"]["examples"], 1)

    def test_missing_attention_fails_even_with_position_ids(self):
        class PositionIdsOnlyCollator(FakeCollator):
            def __call__(self, samples):
                result = super().__call__(samples)
                del result["attention_mask"]
                result["position_ids"] = FakeTensor([list(range(len(samples[0]["input_ids"])))])
                return result
        trainer = fake_trainer()
        trainer.data_collator = PositionIdsOnlyCollator()
        with self.assertRaisesRegex(CorpusError, "not inspectable"):
            self.check(trainer)

    def test_malformed_attention_shape_and_values_fail(self):
        class MalformedMaskCollator(FakeCollator):
            def __init__(self, mask):
                self.mask = mask

            def __call__(self, samples):
                result = super().__call__(samples)
                result["attention_mask"] = FakeTensor(self.mask)
                return result
        valid_len = len(prepared_records()["train"][0]["input_ids"])
        for bad in [[], [[1] * (valid_len - 1)], [[True] * valid_len],
                    [[2] * valid_len], [["1"] * valid_len]]:
            with self.subTest(bad=bad):
                trainer = fake_trainer()
                trainer.data_collator = MalformedMaskCollator(bad)
                with self.assertRaisesRegex(CorpusError, "attention mask hides"):
                    self.check(trainer)


if __name__ == "__main__":
    unittest.main()
