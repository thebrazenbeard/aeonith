"""No-network checks for the fail-closed Redis admission boundary."""

from __future__ import annotations

import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from aeonith.admission import admit_request


REQUEST_ID = "508c86e9-bfda-461d-b0fd-f5e6418d547a"
OTHER_ID = "319e214a-9375-4c96-9486-86e6e50348e6"
CONFIG = {
    "AEONITH_ADMISSION_REDIS_URL": "https://safe-tiger-12345.upstash.io",
    "AEONITH_ADMISSION_REDIS_TOKEN": "not-a-real-test-token",
    "AEONITH_DAILY_REVIEW_LIMIT": "2",
}


class _Response:
    def __init__(self, data: object, status: int = 200) -> None:
        self.status = status
        self.payload = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return io.BytesIO(self.payload).read(size)


class _SingleResultOpener:
    def __init__(self, result: object, status: int = 200) -> None:
        self.response = _Response(result, status)
        self.calls = []

    def open(self, request, timeout: float):
        self.calls.append((request, timeout))
        return self.response


def _call(outcome: object, *, env=None, headers=None):
    opener = _SingleResultOpener(outcome)
    with patch("aeonith.admission.build_opener", return_value=opener):
        result = admit_request(
            {"X-Aeonith-Request-Id": REQUEST_ID} if headers is None else headers,
            CONFIG if env is None else env,
        )
    return result, opener


class AdmissionTests(unittest.TestCase):
    def test_success_makes_exactly_one_atomic_eval(self):
        (status, error), opener = _call({"result": 0})
        self.assertIsNone(status)
        self.assertIsNone(error)
        self.assertEqual(len(opener.calls), 1)
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, CONFIG["AEONITH_ADMISSION_REDIS_URL"])
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"),
                         "Bearer " + CONFIG["AEONITH_ADMISSION_REDIS_TOKEN"])
        self.assertLessEqual(timeout, 5)
        command = json.loads(request.data)
        self.assertEqual(command[0], "EVAL")
        self.assertEqual(command[2], "2")
        self.assertEqual(command[-2], "2")
        self.assertTrue(command[-1].isdigit())
        script = command[1]
        for expected in ("EXISTS", "GET", "INCR", "SET", "EXPIRE"):
            self.assertIn(expected, script)
        self.assertNotIn(REQUEST_ID, json.dumps(command))

    def test_replay_and_exhausted_daily_budget_are_denied(self):
        for expected, status, code in (
            (1, 409, "duplicate_request"),
            (2, 429, "daily_budget_exhausted"),
        ):
            with self.subTest(expected=expected):
                (actual, error), _ = _call({"result": expected})
                self.assertEqual(actual, status)
                self.assertEqual(error["error"]["code"], code)

    def test_missing_or_invalid_ledger_config_fails_closed(self):
        for env in (
            {},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_URL": ""},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_URL": "http://safe-tiger.upstash.io"},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_URL": "https://localhost"},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_URL": "https://safe-tiger.upstash.io/other"},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_URL": "https://safe-tiger.upstash.io@evil.test"},
            {**CONFIG, "AEONITH_ADMISSION_REDIS_TOKEN": ""},
            {**CONFIG, "AEONITH_DAILY_REVIEW_LIMIT": ""},
            {**CONFIG, "AEONITH_DAILY_REVIEW_LIMIT": "zero"},
            {**CONFIG, "AEONITH_DAILY_REVIEW_LIMIT": "0"},
            {**CONFIG, "AEONITH_DAILY_REVIEW_LIMIT": "1000000"},
        ):
            with self.subTest(env_keys=list(env)):
                with patch("aeonith.admission.build_opener") as transport:
                    status, error = admit_request({"X-Aeonith-Request-Id": REQUEST_ID}, env)
                self.assertEqual(status, 503)
                self.assertEqual(error["status"], "provider_unavailable")
                transport.assert_not_called()

    def test_invalid_or_duplicate_request_identifier_does_not_contact_redis(self):
        values = (
            {},
            {"X-Aeonith-Request-Id": "not-a-uuid"},
            {"X-Aeonith-Request-Id": "508C86E9-BFDA-461D-B0FD-F5E6418D547A"},
            {"X-Aeonith-Request-Id": "508c86e9-bfda-161d-b0fd-f5e6418d547a"},
            {"X-Aeonith-Request-Id": REQUEST_ID, "x-aeonith-request-id": OTHER_ID},
        )
        for headers in values:
            with self.subTest(headers=headers):
                with patch("aeonith.admission.build_opener") as transport:
                    status, error = admit_request(headers, CONFIG)
                self.assertEqual(status, 400)
                self.assertEqual(error["error"]["code"], "invalid_request_id")
                transport.assert_not_called()

    def test_email_message_duplicate_header_is_denied(self):
        message = Message()
        message.add_header("X-Aeonith-Request-Id", REQUEST_ID)
        message.add_header("X-Aeonith-Request-Id", OTHER_ID)
        with patch("aeonith.admission.build_opener") as transport:
            status, _ = admit_request(message, CONFIG)
        self.assertEqual(status, 400)
        transport.assert_not_called()

    def test_network_timeouts_redirects_errors_and_malformed_response_fail_closed(self):
        class _FailureOpener:
            def __init__(self, exception):
                self.exception = exception

            def open(self, _request, timeout):
                raise self.exception

        failures = (
            URLError("test network failure"),
            TimeoutError("test timeout"),
            HTTPError("https://safe-tiger-12345.upstash.io", 302,
                      "redirect forbidden", {}, None),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("aeonith.admission.build_opener", return_value=_FailureOpener(failure)):
                    status, error = admit_request({"X-Aeonith-Request-Id": REQUEST_ID}, CONFIG)
                self.assertEqual(status, 503)
                self.assertNotIn("test network failure", json.dumps(error))

        for response in ({"error": "SECRET redis internal"}, {"result": "OK"},
                         {"result": False}, {"result": None}, {"result": 42},
                         {}, [], {"result": 0, "error": "ambiguous"}):
            with self.subTest(response=response):
                (status, error), _ = _call(response)
                self.assertEqual(status, 503)
                self.assertNotIn("SECRET", json.dumps(error))

        class _RawResponse(_Response):
            def __init__(self, raw: bytes):
                self.status = 200
                self.payload = raw

        for raw in (b"not JSON", b"{" + b"x" * 5000 + b"}"):
            with self.subTest(raw_length=len(raw)):
                with patch("aeonith.admission.build_opener") as build:
                    build.return_value.open.return_value = _RawResponse(raw)
                    status, error = admit_request({"X-Aeonith-Request-Id": REQUEST_ID}, CONFIG)
                self.assertEqual(status, 503)
                self.assertEqual(error["error"]["code"], "admission_unavailable")

    def test_one_admission_and_replays_are_serialized_by_atomic_server_decision(self):
        """Simulated REST server: verify concurrency has one logical reservation."""
        lock = threading.Lock()
        seen = set()
        count = 0

        class _AtomicFakeOpener:
            def open(self, request, timeout):
                nonlocal count
                command = json.loads(request.data)
                replay_key = command[4]
                with lock:
                    if replay_key in seen:
                        result = 1
                    elif count >= 2:
                        result = 2
                    else:
                        seen.add(replay_key)
                        count += 1
                        result = 0
                return _Response({"result": result})

        with patch("aeonith.admission.build_opener", return_value=_AtomicFakeOpener()):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(
                    lambda _: admit_request({"X-Aeonith-Request-Id": REQUEST_ID}, CONFIG),
                    range(32),
                ))
        self.assertEqual([status for status, _ in results].count(None), 1)
        self.assertEqual([status for status, _ in results].count(409), 31)
        self.assertEqual(count, 1)

    def test_distinct_concurrent_identifiers_exhaust_one_shared_daily_allowance(self):
        lock = threading.Lock()
        count = 0

        class _BudgetFakeOpener:
            def open(self, request, timeout):
                nonlocal count
                with lock:
                    if count >= 2:
                        decision = 2
                    else:
                        count += 1
                        decision = 0
                return _Response({"result": decision})

        identifiers = [f"508c86e9-bfda-461d-b0fd-{i:012x}" for i in range(30)]
        with patch("aeonith.admission.build_opener", return_value=_BudgetFakeOpener()):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(
                    lambda rid: admit_request({"X-Aeonith-Request-Id": rid}, CONFIG),
                    identifiers,
                ))
        self.assertEqual([status for status, _ in results].count(None), 2)
        self.assertEqual([status for status, _ in results].count(429), 28)
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
