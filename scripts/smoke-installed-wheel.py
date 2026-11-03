"""Offline HTTP smoke for the installed Aeonith wheel, not the source tree.

Run with an interpreter that has installed the freshly built wheel, from a
working directory outside the checkout. This never loads a model or listens
on a non-loopback address.
"""

from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import sysconfig
import threading

import aeonith
from aeonith.local_server import _asset_root, create_server


_SOURCE_PUBLIC = Path(__file__).resolve().parents[1] / "public"
_ASSETS = {
    "/": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
    "/docx-import-worker.js": "docx-import-worker.js",
}
_DIGEST_ENV = "AEONITH_STATIC_ASSET_SHA256_JSON"


def _assert_installed_package() -> None:
    package_file = Path(aeonith.__file__).resolve()
    package_root = Path(sysconfig.get_path("purelib")).resolve()
    if not package_file.is_relative_to(package_root):
        raise AssertionError(f"Aeonith must resolve from installed wheel: {package_file}")
    expected_assets = Path(sysconfig.get_path("data")).resolve() / "share" / "aeonith"
    actual_assets = _asset_root().resolve()
    if actual_assets != expected_assets:
        raise AssertionError(f"Static assets must resolve from installed wheel: {actual_assets}")


@contextmanager
def _loopback_server():
    server = create_server("127.0.0.1", 0, funnel_origin="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("ephemeral HTTP server did not terminate")


def _get(port: int, path: str) -> tuple[int, bytes]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def main() -> None:
    _assert_installed_package()
    originals = {name: (_SOURCE_PUBLIC / name).read_bytes()
                 for name in set(_ASSETS.values())}
    digests = {name: hashlib.sha256(content).hexdigest()
               for name, content in originals.items()}
    previous_policy = os.environ.get(_DIGEST_ENV)
    try:
        os.environ[_DIGEST_ENV] = json.dumps(digests, sort_keys=True)
        with _loopback_server() as port:
            for route, name in _ASSETS.items():
                status, body = _get(port, route)
                if status != 200:
                    raise AssertionError(f"installed wheel route {route} returned HTTP {status}")
                if body != originals[name]:
                    raise AssertionError(f"installed wheel asset mismatch: {route}")
            status, health = _get(port, "/healthz")
            if status != 200 or json.loads(health).get("status") != "ok":
                raise AssertionError("installed wheel health endpoint was not healthy")

        digests["app.js"] = "0" * 64
        os.environ[_DIGEST_ENV] = json.dumps(digests, sort_keys=True)
        with _loopback_server() as port:
            status, body = _get(port, "/app.js")
            if status != 503:
                raise AssertionError(f"wrong digest did not fail closed: HTTP {status}")
            if body == originals["app.js"]:
                raise AssertionError("mismatched asset bytes leaked")
    finally:
        if previous_policy is None:
            os.environ.pop(_DIGEST_ENV, None)
        else:
            os.environ[_DIGEST_ENV] = previous_policy

    print("PASS: installed wheel loopback assets and pinned SHA-256 fail-closed policy")


if __name__ == "__main__":
    main()
