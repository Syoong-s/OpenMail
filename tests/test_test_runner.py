"""Regression checks for actionable CI test failures and unchanged release failure status."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


# ==========================================
# Function: Verify the real test runner preserves results while exposing failed test details.
# Method: Execute disposable passing/failing suites in fresh interpreter processes.
# ==========================================
class TestRunnerTests(unittest.TestCase):
    # ==========================================
    # Function: Run the production CLI against an isolated fixture suite.
    # Method: Support embedded Windows Python by explicitly admitting the tools directory.
    # ==========================================
    def run_fixture(self, body):
        with tempfile.TemporaryDirectory(prefix='telemail-runner-') as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_probe.py').write_text(body, encoding='utf-8')
            output = root / 'reports'
            code = "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')"
            result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'tools'),
                                     str(ROOT / 'tools/run_tests.py'), '--output', str(output)],
                                    cwd=root, capture_output=True, encoding='utf-8', errors='replace', timeout=30)
            return result, json.loads((output / 'report.json').read_text()), (output / 'tests.txt').read_text(encoding='utf-8')

    # ==========================================
    # Function: Make both assertion failures and unexpected exceptions available in CI logs.
    # Method: Require a failing exit, unchanged report counts, saved log, and terminal tracebacks.
    # ==========================================
    def test_failed_suite_emits_details_and_remains_failed(self):
        body = '''import unittest
# ==========================================
# Function: Supply controlled failing fixture outcomes.
# Method: Raise an assertion and an unexpected exception in independent tests.
# ==========================================
class Probe(unittest.TestCase):
    # ==========================================
    # Function: Supply an assertion diagnostic.
    # Method: Use unittest's real failure handling.
    # ==========================================
    def test_assertion(self): self.fail('assertion-diagnostic-marker')
    # ==========================================
    # Function: Supply an exception diagnostic.
    # Method: Use unittest's real error handling.
    # ==========================================
    def test_exception(self): raise RuntimeError('exception-diagnostic-marker')
'''
        result, report, log = self.run_fixture(body)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report['ok'])
        self.assertEqual((report['run'], report['failures'], report['errors']), (2, 1, 1))
        self.assertEqual(report['excluded_suites'], [])
        for marker in ('test_assertion', 'test_exception', 'assertion-diagnostic-marker', 'exception-diagnostic-marker'):
            self.assertIn(marker, result.stderr)
            self.assertIn(marker, log)

    # ==========================================
    # Function: Keep successful runs quiet and preserve machine-readable reports.
    # Method: Execute one passing test and require zero status with no failure dump.
    # ==========================================
    def test_successful_suite_retains_success_report(self):
        body = '''import unittest
# ==========================================
# Function: Supply a controlled passing fixture.
# Method: Use a real unittest assertion.
# ==========================================
class Probe(unittest.TestCase):
    # ==========================================
    # Function: Succeed through normal test execution.
    # Method: Compare a known pair of values.
    # ==========================================
    def test_pass(self): self.assertEqual(1, 1)
'''
        result, report, log = self.run_fixture(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report['ok'])
        self.assertEqual(report['run'], 1)
        self.assertEqual(result.stderr, '')
        self.assertIn('test_pass', log)


if __name__ == '__main__':
    unittest.main()
