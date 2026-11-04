"""Pure synthetic tests: Windows readiness reporting never starts WSL or a model."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from subprocess import CompletedProcess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experimental import windows_native_memory_gate as subject


class WindowsMemoryGateTests(unittest.TestCase):
    def test_pre_wsl_above_host_floor_is_still_not_training_qualified(self):
        report = subject.assess(7457, ["Ollama.exe", "python.exe"])
        self.assertTrue(report["host_memory_floor_met"])
        self.assertEqual(report["wsl_state"], "unproven")
        self.assertEqual(report["wsl_memavailable_mib"], None)
        self.assertEqual(report["status"], "HOLD_NOT_QUALIFIED")
        self.assertFalse(report["model_load_qualified"])
        self.assertFalse(report["training_authorized"])
        self.assertEqual(report["observed_workloads"], {"ollama.exe": 1, "python.exe": 1})

    def test_below_host_floor_and_unknown_process_inventory_fail_closed(self):
        for processes in ([], None):
            with self.subTest(processes=processes):
                report = subject.assess(4700, processes)
                self.assertFalse(report["host_memory_floor_met"])
                self.assertEqual(report["status"], "HOLD_NOT_QUALIFIED")
        missing = subject.assess(None, None)
        self.assertIsNone(missing["host_memory_floor_met"])
        self.assertFalse(missing["model_load_qualified"])

    def test_process_hint_does_not_claim_wsl_memavailable(self):
        report = subject.assess(9000, ["vmmemWSL.exe", "llama-server.exe"])
        self.assertEqual(report["wsl_state"], "process_hint_only")
        self.assertIsNone(report["wsl_memavailable_mib"])
        self.assertFalse(report["wsl_load_qualified"])
        self.assertEqual(report["observed_workloads"], {"llama-server.exe": 1})

    def test_tasklist_csv_requires_structured_rows(self):
        text = '"vmmemWSL.exe","414","Console","1","1,001 K"\n"ollama.exe","213","Console","1","5,005 K"\n'
        self.assertEqual(subject.parse_tasklist_csv(text), ["vmmemwsl.exe", "ollama.exe"])
        for malformed in ('ERROR: access denied', '"one-field"\n', '"python.exe","no-pid","Console","1","1 K"'):
            with self.subTest(malformed=malformed):
                with self.assertRaises(subject.MemoryGateError):
                    subject.parse_tasklist_csv(malformed)

    def test_tasklist_csv_ignores_only_legitimate_system_idle_pid_zero(self):
        # Actual native tasklist /FO CSV /NH starts with a PID-zero Idle row.
        # Its presence must not hide subsequent running workloads.
        native_csv = (
            '"System Idle Process","0","Services","0","8 K"\n'
            '"System","4","Services","0","2,104 K"\n'
            '"aeonith.exe","2224","Services","0","21,008 K"\n'
            '"ollama.exe","5300","Console","1","3,004,128 K"\n'
        )
        processes = subject.parse_tasklist_csv(native_csv)
        self.assertEqual(processes, ["system", "aeonith.exe", "ollama.exe"])
        report = subject.assess(7323, processes)
        self.assertTrue(report["process_inventory_available"])
        self.assertEqual(report["observed_workloads"], {"ollama.exe": 1})
        self.assertEqual(report["status"], "HOLD_NOT_QUALIFIED")
        for invalid in (
            '"ollama.exe","0","Console","1","3,004 K"\n',
            '"System Idle Process","-1","Services","0","8 K"\n',
            '"System Idle Process","zero","Services","0","8 K"\n',
            '"System Idle Process","0","Services","0","8 K"\n'
            '"System Idle Process","0","Services","0","8 K"\n',
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(subject.MemoryGateError):
                    subject.parse_tasklist_csv(invalid)

    def test_collect_uses_read_only_windows_observations_without_wsl_launch(self):
        with (patch.object(subject, "read_windows_available_mib", return_value=7457) as memory,
              patch.object(subject, "list_windows_processes", return_value=["ollama.exe"]) as processes):
            report = subject.collect(platform_name="nt")
        memory.assert_called_once_with()
        processes.assert_called_once_with()
        self.assertEqual(report["status"], "HOLD_NOT_QUALIFIED")
        self.assertEqual(report["windows_available_physical_mib"], 7457)

    def test_tasklist_executable_uses_trusted_absolute_system_directory(self):
        """A fake tasklist.exe in the process CWD/PATH must never be invoked."""
        def system_directory(target, capacity):
            target.value = "C:\\Windows\\System32"
            return len(target.value)

        def windows_directory(target, capacity):
            target.value = "C:\\Windows"
            return len(target.value)

        kernel = SimpleNamespace(GetSystemDirectoryW=system_directory,
                                 GetWindowsDirectoryW=windows_directory)
        fake_winapi = SimpleNamespace(kernel32=kernel)
        result = CompletedProcess(["tasklist"], 0, '"ollama.exe","2224","Console","1","2,000 K"\n')
        with (patch.object(subject.ctypes, "windll", fake_winapi, create=True),
              patch.object(subject.subprocess, "run", return_value=result) as run):
            self.assertEqual(subject.list_windows_processes(), ["ollama.exe"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "C:\\Windows\\System32\\tasklist.exe")
        self.assertEqual(argv[1:], ["/FO", "CSV", "/NH"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_untrusted_system_directory_has_no_executable_search_fallback(self):
        def windows_directory(target, capacity):
            target.value = "C:\\Windows"
            return len(target.value)

        for hostile_path in (
            "\\\\attacker\\share", "C:\\Users\\Public",
            "C:\\Windows\\System32\\..\\Temp", "C:\\Windows\\Temp\\..\\System32",
            "D:\\Windows\\System32", "C:\\Windows\\SysWOW64",
            "C:\\Windows\\System32\\", "C:\\Windows\\.\\System32",
        ):
            with self.subTest(hostile_path=hostile_path):
                def hostile_directory(target, capacity):
                    target.value = hostile_path
                    return len(target.value)

                fake_winapi = SimpleNamespace(kernel32=SimpleNamespace(
                    GetSystemDirectoryW=hostile_directory,
                    GetWindowsDirectoryW=windows_directory))
                with (patch.object(subject.ctypes, "windll", fake_winapi, create=True),
                      patch.object(subject.subprocess, "run") as run):
                    with self.assertRaises(subject.MemoryGateError):
                        subject.list_windows_processes()
                run.assert_not_called()

    def test_noncanonical_windows_root_or_unavailable_root_api_fails_closed(self):
        def system_directory(target, capacity):
            target.value = "C:\\Windows\\System32"
            return len(target.value)

        for windows_root in ("C:\\Windows\\..\\Windows", "C:\\Users\\Public", "\\\\host\\share"):
            with self.subTest(windows_root=windows_root):
                def injected_root(target, capacity):
                    target.value = windows_root
                    return len(target.value)

                kernel = SimpleNamespace(GetWindowsDirectoryW=injected_root,
                                         GetSystemDirectoryW=system_directory)
                with (patch.object(subject.ctypes, "windll",
                                   SimpleNamespace(kernel32=kernel), create=True),
                      patch.object(subject.subprocess, "run") as run):
                    with self.assertRaises(subject.MemoryGateError):
                        subject.list_windows_processes()
                    run.assert_not_called()

        kernel = SimpleNamespace(GetSystemDirectoryW=system_directory)
        with (patch.object(subject.ctypes, "windll",
                           SimpleNamespace(kernel32=kernel), create=True),
              patch.object(subject.subprocess, "run") as run):
            with self.assertRaises(subject.MemoryGateError):
                subject.list_windows_processes()
            run.assert_not_called()

    def test_default_cli_refuses_and_no_probe_without_inspect(self):
        output = StringIO()
        with (patch.object(subject, "collect", side_effect=AssertionError("would probe")),
              redirect_stdout(output)):
            code = subject.main([])
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "NOT_EXECUTED")
        self.assertFalse(report["model_loaded"])
        self.assertEqual(report["optimizer_steps"], 0)


if __name__ == "__main__":
    unittest.main()
