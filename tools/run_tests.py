"""Run all backend tests with disposable profile paths and a machine-readable result."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


# ==========================================
# Function: Run complete backend discovery without reading the user's TeleMail profile.
# Method: Redirect profile homes, preserve every test, and expose failed tracebacks alongside saved reports.
# ==========================================
def main():
    sys.dont_write_bytecode = True
    root = Path.cwd()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'tests'))
    sys.path.insert(0, str(root / 'tools'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=root / '.runtime/backend-tests')
    parser.add_argument('--bundle', type=Path, default=root / ('dist/TeleMail-Windows-amd64' if os.name == 'nt' else 'dist/TeleMail-Linux-amd64'))
    parser.add_argument('--qa-openssl-dir', type=Path, help='Existing test-only OpenSSL CLI directory, for Windows TLS fixtures')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        os.environ['TELEMAIL_WINDOWS_RUNTIME'] = str(args.bundle.resolve() / 'runtime')
    with tempfile.TemporaryDirectory(prefix='maildesk-tests-') as temporary:
        profile = Path(temporary)
        for name in ('APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            folder = profile / name
            folder.mkdir()
            os.environ[name] = str(folder)
        if args.qa_openssl_dir:
            os.environ['PATH'] = str(args.qa_openssl_dir.resolve()) + os.pathsep + os.environ.get('PATH', '')
            config = profile / 'openssl.cnf'
            config.write_text('[req]\ndistinguished_name=dn\n[dn]\n')
            os.environ['OPENSSL_CONF'] = str(config)
        with (args.output / 'tests.txt').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.discover(str(root / 'tests')))
        report = {'ok': result.wasSuccessful(), 'platform': sys.platform, 'python': sys.version.split()[0],
                  'run': result.testsRun, 'skipped': len(result.skipped), 'failures': len(result.failures),
                  'errors': len(result.errors), 'excluded_suites': []}
        from release_context import provenance
        report['provenance'] = provenance(args.bundle)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if not result.wasSuccessful():
            print((args.output / 'tests.txt').read_text(encoding='utf-8'), file=sys.stderr)
        print(json.dumps(report))
        return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
