"""The manuscript CLI emits UTF-8 bytes independently of the console locale."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


MODULE = Path(__file__).resolve().parents[1] / "aeonith" / "text_input.py"


class TextInputEncodingTests(unittest.TestCase):
    def test_utf8_pipe_is_independent_of_stdout_encoding(self):
        for encoding in ("ascii", "cp1252"):
            for passage in ("A bell rang.\n", "星の光 🌊\r\nÉcho…\n"):
                with self.subTest(encoding=encoding, passage=passage):
                    env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8="0")
                    result = subprocess.run(
                        [sys.executable, "-X", "utf8=0", str(MODULE), "--input", "-"],
                        input=passage.encode("utf-8"),
                        env=env, capture_output=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout.endswith(b"\n"))
                    self.assertFalse(result.stdout.endswith(b"\r\n"))
                    self.assertEqual(json.loads(result.stdout.decode("utf-8"))["work"]["text"], passage)


if __name__ == "__main__":
    unittest.main()
