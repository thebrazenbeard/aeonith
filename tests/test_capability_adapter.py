"""Public contract checks; reviewer function is a controlled boundary fixture."""

import json
import math
import sys
import unittest
from pathlib import Path

CORE_SOURCE = Path(__file__).resolve().parents[1] / "core_build"
if CORE_SOURCE.is_dir() and str(CORE_SOURCE) not in sys.path:
    sys.path.insert(0, str(CORE_SOURCE))

from capability_adapter import CAPABILITY, decode_and_invoke, invoke


def _input(request_id="r-1"):
    return {
        "kind": "capability.invoke.v1",
        "request_id": request_id,
        "capability": CAPABILITY,
        "payload": {"schema_version": CAPABILITY, "work": {"text": "A sentence."}, "lenses": ["stylistic"]},
    }


def _completed_result():
    return {
        "schema_version": CAPABILITY,
        "status": "completed",
        "assessment": None,
        "lens_reviews": [{
            "lens": "stylistic", "analysis": "The sentence has clipped rhythm.",
            "basis": "textual", "support": [{"source": "work", "quote": "sentence"}],
            "limitations": [],
        }],
        "synthesis": "The work is brief but coherent.",
        "challenges": [],
        "uncertainties": [],
        "evidence_audit": [],
        "provenance": {
            "review_source": "injected_provider",
            "provider_name": "FixtureProvider",
            "input_evidence_verified": False,
            "knowledge_files_attached_by_core": False,
            "provider_external_knowledge": "UNKNOWN",
            "selected_lenses": ["stylistic"],
        },
        "error": None,
    }


class CapabilityAdapterTests(unittest.TestCase):
    def test_delegates_and_preserves_structured_result(self):
        expected = _completed_result()
        observed = []

        def reviewer(payload):
            observed.append(payload)
            return expected

        result = invoke(_input(), reviewer)
        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(result["core_status"], "completed")
        self.assertEqual(result["request_id"], "r-1")
        self.assertIs(result["result"], expected)
        self.assertEqual(observed, [_input()["payload"]])

    def test_actual_core_with_injected_local_provider_completed(self):
        from aeonith.core import critique

        class FixtureProvider:
            name = "FixtureProvider"

            def review(self, provider_payload):
                self.received = provider_payload
                return {
                    "lens_reviews": [{
                        "lens": "stylistic",
                        "analysis": "The sentence is short and direct.",
                        "basis": "textual",
                        "support": [{"source": "work", "quote": "sentence"}],
                        "limitations": [],
                    }],
                    "synthesis": "The tiny passage permits a narrow stylistic reading.",
                    "challenges": [],
                    "uncertainties": [],
                    "assessment": None,
                }

        provider = FixtureProvider()
        result = invoke(_input(), lambda payload: critique(payload, provider=provider))
        self.assertEqual(result["outcome"], "ok")
        self.assertEqual(result["result"]["status"], "completed")
        self.assertEqual(result["result"]["provenance"]["provider_external_knowledge"], "UNKNOWN")
        self.assertEqual(provider.received["task"]["lenses"], ["stylistic"])

    def test_actual_core_unavailable_has_status_but_no_raw_result(self):
        from aeonith.core import critique

        result = invoke(_input(), critique)
        self.assertEqual(result["outcome"], "unavailable")
        self.assertEqual(result["core_status"], "provider_unavailable")
        self.assertIsNone(result["result"])
        self.assertEqual(result["error"]["code"], "provider_unavailable")
        self.assertNotIn("provenance", json.dumps(result))

    def test_without_configured_reviewer_has_no_fabricated_result(self):
        result = invoke(_input())
        self.assertEqual(result["outcome"], "unavailable")
        self.assertIsNone(result["result"])

    def test_duplicate_nested_keys_rejected(self):
        payload = b'{"kind":"capability.invoke.v1","request_id":"r-1","capability":"aeonith.review.v1","payload":{"work":{"text":"a","text":"b"}}}'
        result = decode_and_invoke(payload)
        self.assertEqual(result["error"]["code"], "invalid_json")

    def test_nonfinite_json_rejected(self):
        payload = b'{"kind":"capability.invoke.v1","request_id":"r-1","capability":"aeonith.review.v1","payload":{"x":NaN}}'
        self.assertEqual(decode_and_invoke(payload)["error"]["code"], "invalid_json")

    def test_numeric_overflow_nonfinite_json_rejected(self):
        payload = b'{"kind":"capability.invoke.v1","request_id":"r-1","capability":"aeonith.review.v1","payload":{"x":1e309}}'
        self.assertEqual(decode_and_invoke(payload)["error"]["code"], "invalid_json")

    def test_excessively_nested_json_rejected(self):
        payload = b"[" * 3000 + b"0" + b"]" * 3000
        self.assertEqual(decode_and_invoke(payload)["error"]["code"], "invalid_json")

    def test_overlarge_request_rejected(self):
        result = decode_and_invoke(b" " * 262_145)
        self.assertEqual(result["error"]["code"], "input_too_large")

    def test_rejects_unexpected_envelope_keys(self):
        request = _input()
        request["authorization"] = "self-asserted"
        result = invoke(request)
        self.assertEqual(result["error"]["code"], "invalid_envelope")

    def test_review_exception_redacted(self):
        def broken(_):
            raise RuntimeError("secret-provider-token")

        result = invoke(_input(), broken)
        self.assertEqual(result["error"], {"code": "reviewer_error", "message": "The reviewer failed"})
        self.assertNotIn("secret-provider-token", json.dumps(result))

    def test_wrong_capability_rejected_without_calling_reviewer(self):
        request = _input()
        request["capability"] = "dangerous.write.v1"

        def broken(_):
            raise AssertionError("must not be called")

        result = invoke(request, broken)
        self.assertEqual(result["error"]["code"], "unsupported_capability")

    def test_core_invalid_request_is_rejected(self):
        def reviewer(_):
            return {"schema_version": CAPABILITY, "status": "invalid_request"}

        result = invoke(_input(), reviewer)
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["core_status"], "invalid_request")
        self.assertIsNone(result["result"])

    def test_malicious_noncompleted_statuses_never_forward_raw_fields(self):
        statuses = {
            "provider_unavailable": "unavailable",
            "invalid_request": "rejected",
            "provider_error": "failed",
            "invalid_provider_output": "failed",
        }
        for status, outcome in statuses.items():
            with self.subTest(status=status):
                forged = {
                    "schema_version": CAPABILITY,
                    "status": status,
                    "provenance": {"input_evidence_verified": True, "review_source": "FORMAL_VERIFY"},
                    "fake_secret": "raw",
                    "error": {"message": "secret-provider-token"},
                }
                result = invoke(_input(), lambda _: forged)
                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(result["core_status"], status)
                self.assertIsNone(result["result"])
                self.assertEqual(result["error"]["code"], status)
                rendered = json.dumps(result)
                for forbidden in ("FORMAL_VERIFY", "fake_secret", "raw", "secret-provider-token", "input_evidence_verified"):
                    self.assertNotIn(forbidden, rendered)

    def test_incomplete_forged_success_is_failed(self):
        result = invoke(_input(), lambda _: {"schema_version": CAPABILITY, "status": "completed"})
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")
        self.assertIsNone(result["result"])

    def test_missing_requested_lens_is_failed(self):
        forged = _completed_result()
        forged["lens_reviews"] = []
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_unanchored_quote_is_failed(self):
        forged = _completed_result()
        forged["lens_reviews"][0]["support"] = [{"source": "work", "quote": "invented line"}]
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_malformed_nested_types_fail_without_exception(self):
        forged = _completed_result()
        forged["lens_reviews"][0]["lens"] = ["stylistic"]
        forged["assessment"] = {"malformed": True}
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_unknown_core_status_is_failed(self):
        result = invoke(_input(), lambda _: {"schema_version": CAPABILITY, "status": "trusted_by_vote"})
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_forged_verified_flag_and_nonfinite_number_are_failed(self):
        forged = _completed_result()
        forged["lens_reviews"][0]["support"][0]["verified"] = True
        forged["extra"] = math.nan
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")
        self.assertIsNone(result["result"])

    def test_unknown_support_verification_flag_is_failed_even_without_nan(self):
        forged = _completed_result()
        forged["lens_reviews"][0]["support"][0]["verified"] = True
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_nonfinite_nested_number_is_failed_even_without_extra_fields(self):
        forged = _completed_result()
        forged["lens_reviews"][0]["analysis"] = "A sentence."
        forged["evidence_audit"] = [{"claim_id": "c", "score": math.inf}]
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_overlarge_completed_result_is_failed(self):
        forged = _completed_result()
        forged["synthesis"] = "A" * 2_097_153
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")

    def test_forged_verified_evidence_audit_is_failed(self):
        forged = _completed_result()
        forged["evidence_audit"] = [{"claim_id": "fake", "status": "verified", "source_refs": []}]
        result = invoke(_input(), lambda _: forged)
        self.assertEqual(result["error"]["code"], "invalid_reviewer_output")


if __name__ == "__main__":
    unittest.main()
