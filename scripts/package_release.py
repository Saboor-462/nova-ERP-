"""Build a source-only release ZIP: python -m scripts.package_release --output ..\\nova_erp-release.zip

Allowlist-based: databases, backups, secrets, .env, reference photos, and uploaded documents are never included.
"""
import argparse
from pathlib import Path
import zipfile
from nova.config import ROOT

TOP_LEVEL = ['app.py', 'setup_admin_windows.bat', 'reset_demo.py', 'README.md', 'CHANGELOG.md', 'AUDIT_REPORT.md', 'PROJECT_CONTEXT.md', 'requirements.txt',
             'requirements-dev.txt', 'pytest.ini', 'run_windows.bat', 'setup_windows.bat', 'test_windows.bat', '.gitignore',
             '.env.example', '.streamlit/config.toml', '.streamlit/secrets.example.toml']
FOLDERS = {'nova': {'.py'}, 'scripts': {'.py'}, 'tests': {'.py', '.sql'}, 'docs': {'.md', '.sql'}}
FORBIDDEN_SUFFIXES = ('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3', '.dump', '.bak', '.pdf', '.png', '.jpg', '.jpeg')
FORBIDDEN_NAMES = ('.env', 'secrets.toml')


def release_files(root=ROOT):
    files = [root / name for name in TOP_LEVEL if (root / name).is_file()]
    for folder, suffixes in FOLDERS.items():
        files += sorted(p for p in (root / folder).rglob('*')
                        if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    files += [root / 'assets/nova_logo.jpeg'] if (root / 'assets/nova_logo.jpeg').exists() else []
    fonts = ['DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LICENSE.txt']
    files += [root / 'assets/fonts' / name for name in fonts if (root / 'assets/fonts' / name).exists()]
    for path in files:
        if path.relative_to(root).as_posix() == 'assets/nova_logo.jpeg':
            continue
        relative = path.relative_to(root).as_posix()
        if path.name in FORBIDDEN_NAMES or relative.lower().endswith(FORBIDDEN_SUFFIXES):
            raise SystemExit(f'Refusing to package sensitive file: {relative}')
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a source-only release ZIP (no databases, backups, secrets, or documents).')
    parser.add_argument('--output', required=True, help='New .zip path outside the project folder.')
    args = parser.parse_args(argv)
    target = Path(args.output).resolve()
    if target.exists():
        raise SystemExit('Destination already exists; choose a new filename.')
    if ROOT in target.parents:
        raise SystemExit('Write the release outside the project folder so it cannot include itself.')
    files = release_files()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f'nova_erp/{path.relative_to(ROOT).as_posix()}')
    print(f'Release created with {len(files)} files: {target}')


if __name__ == '__main__':
    main()
