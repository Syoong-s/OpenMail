"""Version, provenance and test gates shared by local and GitHub release checks."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


# ==========================================
# Function: Read the application version without importing desktop dependencies.
# Method: Accept a three-component release version declared by the source package.
# ==========================================
def version():
    value = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (ROOT / 'maildesk/__init__.py').read_text())[1]
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Release version must be X.Y.Z')
    return value


# ==========================================
# Function: Associate every QA result with its exact commit and tested package.
# Method: Hash the bundle manifest and record the current GitHub workflow run identity.
# ==========================================
def provenance(bundle=None):
    try:
        result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        revision = result.stdout.strip() if result.returncode == 0 else None
    except OSError:
        revision = None
    manifest = Path(bundle) / 'manifest.json' if bundle else None
    return {'source_revision': revision,
            'github_run_id': os.environ.get('GITHUB_RUN_ID'),
            'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
            'bundle_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest and manifest.is_file() else None}


# ==========================================
# Function: Refuse an arbitrary branch, mismatching version tag or retargeted tag.
# Method: Require vX.Y.Z to match source and the checked-out tag commit in CI.
# ==========================================
def validate_tag(tag):
    if tag != 'v' + version():
        raise ValueError('Tag must match application version: v' + version())
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        target = subprocess.check_output(['git', 'rev-parse', 'refs/tags/' + tag + '^{commit}'], cwd=ROOT, text=True).strip()
        if target != provenance()['source_revision']:
            raise ValueError('Tag commit differs from checked-out source')
    return tag


# ==========================================
# Function: Require complete successful backend/native tests for each exact release bundle.
# Method: Reject missing suites, provider calls, stale manifests and foreign CI runs/commits.
# ==========================================
def validate_reports(backend, gui, bundle, require_ci=False):
    if (not backend.get('ok') or backend.get('excluded_suites') != [] or backend.get('run', 0) < 320
            or backend.get('failures') != 0 or backend.get('errors') != 0
            or not gui.get('ok') or len(set(gui.get('checks', []))) != 9 or gui.get('real_provider_calls') != 0):
        raise ValueError('Incomplete or failed backend/native tests')
    expected = provenance(bundle)
    for report in (backend, gui):
        context = report.get('provenance', {})
        if context.get('bundle_manifest_sha256') != expected['bundle_manifest_sha256']:
            raise ValueError('Test report belongs to a different bundle')
        if context.get('source_revision') != expected['source_revision']:
            raise ValueError('Test report belongs to a different source commit')
        if require_ci and (not expected['github_run_id'] or not expected['source_revision']
                           or context.get('github_run_id') != expected['github_run_id']):
            raise ValueError('Test report belongs to a different GitHub workflow run')
