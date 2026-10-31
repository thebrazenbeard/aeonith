"""Adversarial contract tests for the conditional host gate (no live host)."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from capability_adapter import CAPABILITY, INVOKE_KIND
from integrations.host_gate import (
    READ_ONLY_REVIEW, AuthorizationRequest, HostContext, Reservation,
    invoke_with_host_authority,
)


def envelope(**updates):
    value = {
        "kind": INVOKE_KIND,
        "request_id": "case-001",
        "capability": CAPABILITY,
        "payload": {"schema_version": CAPABILITY, "proposition": "A small literary argument."},
    }
    value.update(updates)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


CONTEXT = HostContext("actor-1", "tenant-1", "provider-1", True, "full-review-payload")


class FakeAuthority:
    """Pure test fixture, NOT an authenticated/durable production authority."""

    def __init__(self, override=None):
        self.override = override
        self.calls = 0
        self.seen = set()
        self.seen_ids = set()

    def authorize_and_reserve(self, request: AuthorizationRequest):
        self.calls += 1
        if request.request_sha256 in self.seen or request.request_id in self.seen_ids:
            return None
        self.seen.add(request.request_sha256)
        self.seen_ids.add(request.request_id)
        result = Reservation(
            issuer="test-host", reservation_id="test-reservation", request_id=request.request_id,
            actor_id=request.actor_id,
            tenant_id=request.tenant_id, provider_id=request.provider_id,
            external_provider=request.external_provider,
            disclosure_scope=request.disclosure_scope,
            capability=request.capability, effect=READ_ONLY_REVIEW,
            request_sha256=request.request_sha256, consent_external_disclosure=True,
            consent_receipt_id="host-consent-receipt",
            expires_at_epoch=2000.0, max_input_bytes=262144,
            max_output_bytes=2097152, reserved_provider_calls=1,
            reserved_provider_input_tokens=2048, reserved_provider_output_tokens=4096,
            reserved_cost_microusd=25000, max_runtime_ms=30000,
        )
        return self.override(result) if self.override else result


class GateTests(unittest.TestCase):
    def invoke(self, *, raw=None, authority=None, context=CONTEXT, reviewer=None):
        if reviewer is None:
            reviewer = lambda _payload: {"schema_version": CAPABILITY, "status": "provider_unavailable"}
        return invoke_with_host_authority(
            envelope() if raw is None else raw,
            context=context, authority=authority, reviewer=reviewer,
            clock=lambda: 1000.0,
        )

    def test_default_is_denial_without_host_authority(self):
        self.assertEqual(self.invoke()["error"]["code"], "host_authority_unavailable")

    def test_no_context_reviewer_or_valid_context_denied(self):
        self.assertEqual(self.invoke(authority=FakeAuthority(), context=None)["outcome"], "rejected")
        bad = replace(CONTEXT, actor_id="actor\nadmin")
        self.assertEqual(self.invoke(authority=FakeAuthority(), context=bad)["outcome"], "rejected")
        outcome = invoke_with_host_authority(envelope(), context=CONTEXT, authority=FakeAuthority(), clock=lambda: 1000.0)
        self.assertEqual(outcome["error"]["code"], "host_authority_unavailable")

    def test_invalid_envelopes_do_not_reserve(self):
        for raw in (
            b'{"kind":"a","kind":"b"}',
            b'{"kind": NaN}',
            b"{broken",
            envelope(authorization={"lease": "untrusted"}),
            envelope(capability="side_effect.v1"),
            envelope(payload={}),
            b"x" * 262145,
        ):
            with self.subTest(raw=raw[:30]):
                auth = FakeAuthority()
                result = self.invoke(raw=raw, authority=auth)
                self.assertEqual(result["outcome"], "rejected")
                self.assertEqual(auth.calls, 0)

    def test_successful_reservation_only_returns_sanitized_adapter_failure(self):
        result = self.invoke(authority=FakeAuthority())
        self.assertEqual(result["outcome"], "unavailable")
        self.assertEqual(result["error"]["code"], "provider_unavailable")
        self.assertIsNone(result["result"])

    def test_authorized_completed_review_keeps_structured_result(self):
        work = "The sentence stands."
        raw = envelope(payload={
            "schema_version": CAPABILITY,
            "work": {"text": work},
            "lenses": ["stylistic"],
        })
        completed = {
            "schema_version": CAPABILITY,
            "status": "completed",
            "assessment": None,
            "lens_reviews": [{
                "lens": "stylistic", "analysis": "The short syntax is direct.",
                "basis": "textual", "support": [{"source": "work", "quote": "sentence"}],
                "limitations": [],
            }],
            "synthesis": "A narrow stylistic observation.",
            "challenges": [], "uncertainties": [], "evidence_audit": [],
            "provenance": {
                "review_source": "injected_provider", "provider_name": "FixtureProvider",
                "input_evidence_verified": False,
                "knowledge_files_attached_by_core": False,
                "provider_external_knowledge": "UNKNOWN",
                "selected_lenses": ["stylistic"],
            },
            "error": None,
        }
        observed = []

        def reviewer(payload):
            observed.append(payload)
            return completed

        response = self.invoke(raw=raw, authority=FakeAuthority(), reviewer=reviewer)
        self.assertEqual(response["outcome"], "ok")
        self.assertEqual(response["result"], completed)
        self.assertEqual(observed[0]["work"]["text"], work)

    def test_replay_denied_by_fixture_authority(self):
        auth = FakeAuthority()
        self.assertEqual(self.invoke(authority=auth)["outcome"], "unavailable")
        self.assertEqual(self.invoke(authority=auth)["error"]["code"], "host_authority_denied")

    def test_same_id_with_changed_payload_is_replay_at_host_boundary(self):
        auth = FakeAuthority()
        first = envelope(payload={"schema_version": CAPABILITY, "proposition": "One story."})
        second = envelope(payload={"schema_version": CAPABILITY, "proposition": "Different story."})
        self.assertNotEqual(first, second)
        self.assertEqual(self.invoke(raw=first, authority=auth)["outcome"], "unavailable")
        self.assertEqual(self.invoke(raw=second, authority=auth)["error"]["code"], "host_authority_denied")

    def test_all_binding_mismatch_cases(self):
        mutations = [
            {"issuer": ""}, {"reservation_id": "bad id"},
            {"request_id": "another-case"},
            {"actor_id": "other"}, {"tenant_id": "other"},
            {"provider_id": "other"}, {"capability": "other"},
            {"external_provider": False},
            {"disclosure_scope": "other"},
            {"effect": "memory.write"}, {"request_sha256": "0" * 64},
            {"consent_external_disclosure": False}, {"consent_receipt_id": None},
            {"expires_at_epoch": 1000.0}, {"expires_at_epoch": float("inf")},
            {"max_input_bytes": 1}, {"max_input_bytes": 262145},
            {"max_output_bytes": 0}, {"max_output_bytes": 2097153},
            {"reserved_provider_calls": 0}, {"reserved_provider_calls": 2},
            {"reserved_provider_input_tokens": 0},
            {"reserved_provider_output_tokens": 0},
            {"reserved_cost_microusd": 0}, {"max_runtime_ms": 0},
        ]
        for fields in mutations:
            with self.subTest(fields=fields):
                auth = FakeAuthority(override=lambda grant, f=fields: replace(grant, **f))
                self.assertEqual(self.invoke(authority=auth)["error"]["code"], "host_authority_denied")

    def test_boolean_cannot_masquerade_as_resource_budget(self):
        auth = FakeAuthority(override=lambda grant: replace(grant, max_output_bytes=True))
        self.assertEqual(self.invoke(authority=auth)["outcome"], "rejected")

    def test_integer_cannot_masquerade_as_external_provider_boolean(self):
        auth = FakeAuthority(override=lambda grant: replace(grant, external_provider=1))
        self.assertEqual(self.invoke(authority=auth)["error"]["code"], "host_authority_denied")

    def test_reservation_expiring_during_authority_call_never_invokes_reviewer(self):
        clock_values = iter([1000.0, 2000.0])
        observed = []
        result = invoke_with_host_authority(
            envelope(), context=CONTEXT, authority=FakeAuthority(),
            reviewer=lambda payload: observed.append(payload) or {},
            clock=lambda: next(clock_values),
        )
        self.assertEqual(result["error"]["code"], "host_authority_denied")
        self.assertEqual(observed, [])

    def test_output_budget_suppresses_result(self):
        auth = FakeAuthority(override=lambda grant: replace(grant, max_output_bytes=10))
        self.assertEqual(self.invoke(authority=auth)["error"]["code"], "output_budget_exceeded")

    def test_external_consent_scoped_only_to_external_provider(self):
        local = replace(CONTEXT, external_provider=False)
        auth = FakeAuthority(override=lambda grant: replace(
            grant, consent_external_disclosure=False, consent_receipt_id=None,
        ))
        self.assertEqual(self.invoke(authority=auth, context=local)["outcome"], "unavailable")

    def test_authority_exception_and_invalid_clock_fail_closed(self):
        class Broken:
            def authorize_and_reserve(self, _request):
                raise RuntimeError("credential=secret-do-not-expose")

        text = json.dumps(self.invoke(authority=Broken()))
        self.assertNotIn("secret-do-not-expose", text)
        invalid = invoke_with_host_authority(
            envelope(), context=CONTEXT, authority=FakeAuthority(),
            reviewer=lambda _: {}, clock=lambda: float("nan"),
        )
        self.assertEqual(invalid["outcome"], "rejected")

    def test_provider_exception_sanitized(self):
        def crash(_payload):
            raise RuntimeError("user manuscript and API key should not leak")

        result = self.invoke(authority=FakeAuthority(), reviewer=crash)
        self.assertEqual(result["error"]["code"], "reviewer_error")
        self.assertNotIn("API key", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
