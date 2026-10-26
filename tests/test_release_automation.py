"""Release safety gates independent of GitHub credentials or live publishing."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_context_test', ROOT / 'tools/release_context.py')
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


# ==========================================
# Function: Verify release provenance rejects stale, foreign or failed QA evidence.
# Method: Exercise production gates with synthetic report identities and no GitHub access.
# ==========================================
class ReleaseGateTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare a valid current-run report pair for mutation-based rejection checks.
    # Method: Supply backend totals, nine native checks and the exact tested manifest identity.
    # ==========================================
    def setUp(self):
        self.identity = {'source_revision': 'commit-one', 'github_run_id': 'run-one', 'bundle_manifest_sha256': 'manifest-one'}
        self.backend = {'ok': True, 'excluded_suites': [], 'run': 320, 'failures': 0, 'errors': 0,
                        'provenance': dict(self.identity)}
        self.gui = {'ok': True, 'checks': ['check-' + str(i) for i in range(9)],
                    'real_provider_calls': 0, 'provenance': dict(self.identity)}

    # ==========================================
    # Function: Accept complete tests from the current commit, package and workflow run.
    # Method: Compare both reports against the same independently supplied identity.
    # ==========================================
    def test_accept_current_ci_evidence(self):
        with patch.object(context, 'provenance', return_value=self.identity):
            context.validate_reports(self.backend, self.gui, ROOT, require_ci=True)

    # ==========================================
    # Function: Refuse reuse of reports from another build, commit or workflow run.
    # Method: Mutate each provenance field on each report while keeping test counts successful.
    # ==========================================
    def test_reject_stale_or_foreign_evidence(self):
        for report_name in ('backend', 'gui'):
            for key in self.identity:
                with self.subTest(report=report_name, field=key):
                    backend, gui = deepcopy(self.backend), deepcopy(self.gui)
                    (backend if report_name == 'backend' else gui)['provenance'][key] = 'different'
                    with patch.object(context, 'provenance', return_value=self.identity), self.assertRaises(ValueError):
                        context.validate_reports(backend, gui, ROOT, require_ci=True)

    # ==========================================
    # Function: Refuse incomplete backend testing and real provider interactions.
    # Method: Mutate meaningful gate fields even when a caller leaves ok set to true.
    # ==========================================
    def test_reject_failures_exclusions_and_provider_calls(self):
        for field, value in [('run', 1), ('errors', 1), ('failures', 1), ('excluded_suites', ['suite'])]:
            backend = deepcopy(self.backend)
            backend[field] = value
            with self.subTest(field=field), patch.object(context, 'provenance', return_value=self.identity), self.assertRaises(ValueError):
                context.validate_reports(backend, self.gui, ROOT, require_ci=True)
        gui = deepcopy(self.gui)
        gui['real_provider_calls'] = 1
        with patch.object(context, 'provenance', return_value=self.identity), self.assertRaises(ValueError):
            context.validate_reports(self.backend, gui, ROOT, require_ci=True)

    # ==========================================
    # Function: Refuse a CI approval that has no authenticated workflow-run identity.
    # Method: Keep otherwise matching local reports and remove run metadata.
    # ==========================================
    def test_local_reports_cannot_approve_ci_release(self):
        identity = dict(self.identity, github_run_id=None)
        backend, gui = deepcopy(self.backend), deepcopy(self.gui)
        backend['provenance'] = gui['provenance'] = identity
        with patch.object(context, 'provenance', return_value=identity), self.assertRaises(ValueError):
            context.validate_reports(backend, gui, ROOT, require_ci=True)

    # ==========================================
    # Function: Refuse version tags unrelated to the checked-out application version.
    # Method: Check semantic version equality before any publication operation.
    # ==========================================
    def test_tag_matches_application_version(self):
        with patch.dict('os.environ', {'GITHUB_ACTIONS': 'false'}):
            self.assertEqual(context.validate_tag('v' + context.version()), 'v' + context.version())
            for tag in ('main', 'v999.0.0', 'v0.55.0;echo unexpected'):
                with self.subTest(tag=tag), self.assertRaises(ValueError):
                    context.validate_tag(tag)
