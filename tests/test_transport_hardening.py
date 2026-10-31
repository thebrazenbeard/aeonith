"""Source-level credential and protocol ambiguity regressions."""

import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler

from aeonith.providers import _post_json, _strict_json


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, _amount):
        return b'{"choices":[]}'


class FakeOpener:
    def open(self, _request, timeout):
        return FakeResponse()


class TransportHardeningTests(unittest.TestCase):
    def test_rejects_duplicate_fields_at_any_json_depth(self):
        for raw in (
            '{"assessment":"FAILS","assessment":null}',
            '{"outer":{"source":"work","source":"provided_evidence"}}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _strict_json(raw)

    def test_transport_disables_environment_proxy_inheritance(self):
        with patch("aeonith.providers.build_opener", return_value=FakeOpener()) as builder:
            _post_json("http://localhost:4242/v1/chat/completions", None, 5,
                       {"messages": [{"role": "user", "content": "PRIVATE_SAMPLE"}]})
        handlers = builder.call_args.args
        explicit_proxies = [x for x in handlers if isinstance(x, ProxyHandler)]
        self.assertEqual(len(explicit_proxies), 1)
        self.assertEqual(explicit_proxies[0].proxies, {})


if __name__ == "__main__":
    unittest.main()
