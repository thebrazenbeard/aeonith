"""Deterministic tests for the zero-cost, process-local public ingress budget."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from aeonith.funnel_limits import LocalAdmission


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class LocalAdmissionTests(unittest.TestCase):
    def test_inflight_cap_and_idempotent_release(self):
        limiter = LocalAdmission(max_inflight=2)
        first, delay = limiter.begin_review()
        self.assertIsNotNone(first)
        self.assertEqual(delay, 0)
        second, _ = limiter.begin_review()
        self.assertIsNotNone(second)
        denied, delay = limiter.begin_review()
        self.assertIsNone(denied)
        self.assertEqual(delay, 1)
        first.release()
        first.release()  # A double finally/release must not create extra slots.
        third, delay = limiter.begin_review()
        self.assertIsNotNone(third)
        self.assertEqual(delay, 0)
        denied, _ = limiter.begin_review()
        self.assertIsNone(denied)
        second.release()
        third.release()

    def test_hourly_review_quota_ages_out_without_sleep(self):
        clock = Clock()
        limiter = LocalAdmission(max_reviews_per_hour=2, clock=clock)
        for _ in range(2):
            reservation, _ = limiter.begin_review()
            self.assertIsNotNone(reservation)
            reservation.release()
        denied, delay = limiter.begin_review()
        self.assertIsNone(denied)
        self.assertEqual(delay, 3600)
        clock.now = 3599.2
        denied, delay = limiter.begin_review()
        self.assertIsNone(denied)
        self.assertEqual(delay, 1)
        clock.now = 3600.0
        admitted, delay = limiter.begin_review()
        self.assertIsNotNone(admitted)
        self.assertEqual(delay, 0)
        admitted.release()

    def test_failed_auth_lockout_does_not_extend_on_excess(self):
        clock = Clock()
        limiter = LocalAdmission(max_auth_failures_per_minute=2, clock=clock)
        self.assertEqual(limiter.auth_attempt_allowed(), (True, 0))
        limiter.record_auth_failure()
        self.assertEqual(limiter.auth_attempt_allowed(), (True, 0))
        limiter.record_auth_failure()
        self.assertEqual(limiter.auth_attempt_allowed(), (False, 60))
        clock.now = 30.0
        limiter.record_auth_failure()  # Denied floods must not refresh lockout.
        self.assertEqual(limiter.auth_attempt_allowed(), (False, 30))
        clock.now = 60.0
        self.assertEqual(limiter.auth_attempt_allowed(), (True, 0))

    def test_failed_auth_and_authorized_review_budgets_are_independent(self):
        limiter = LocalAdmission(max_auth_failures_per_minute=1)
        limiter.record_auth_failure()
        self.assertEqual(limiter.auth_attempt_allowed()[0], False)
        review, _ = limiter.begin_review()
        self.assertIsNotNone(review)
        review.release()

    def test_reservation_is_context_manager_and_releases_on_exception(self):
        limiter = LocalAdmission(max_inflight=1)
        with self.assertRaisesRegex(RuntimeError, "test"):
            with limiter.begin_review()[0]:
                raise RuntimeError("test")
        reservation, _ = limiter.begin_review()
        self.assertIsNotNone(reservation)
        reservation.release()

    def test_exact_concurrent_cap_with_no_timing_assumptions(self):
        limiter = LocalAdmission(max_inflight=4)
        before = threading.Barrier(20)
        release = threading.Barrier(20)

        def attempt(_index):
            before.wait(timeout=5)
            reservation, _ = limiter.begin_review()
            admitted = reservation is not None
            release.wait(timeout=5)
            if reservation is not None:
                reservation.release()
            return admitted

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(attempt, range(20)))
        self.assertEqual(sum(outcomes), 4)
        reservation, _ = limiter.begin_review()
        self.assertIsNotNone(reservation)
        reservation.release()

    def test_invalid_configuration_rejected_before_any_request(self):
        for parameters in (
            {"max_inflight": 0},
            {"max_inflight": 17},
            {"max_reviews_per_hour": 0},
            {"max_reviews_per_hour": 10001},
            {"max_auth_failures_per_minute": 0},
            {"max_auth_failures_per_minute": 1001},
            {"max_inflight": True},
            {"clock": object()},
        ):
            with self.subTest(parameters=parameters), self.assertRaises((TypeError, ValueError)):
                LocalAdmission(**parameters)


if __name__ == "__main__":
    unittest.main()
