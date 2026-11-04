"""Fail publication on private runtime files, home paths, credentials or unknown files.

This focused release gate complements dependency scanning and manual review; it
is not a complete detector for every form of personal information or secret.
"""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from package_release import ROOT as PACKAGE_ROOT, PREFIX, source_paths

PATTERNS = {
    'private key': rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----',
    'GitHub token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'AWS access key': rb'AKIA[0-9A-Z]{16}',
    'home directory': rb'/(?:home|Users)/[^/\s"\x27]+',
    'Windows user directory': rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s"\x27]+',
    'mounted personal workspace': rb'/run'+rb'/media/',
    'private LAN address': rb'\b192\.168\.\d{1,3}\.\d{1,3}\b',
}


def check_content(name,data):
    # Preserve upstream authors' attribution and licensing exactly.
    if name=='THIRD-PARTY-NOTICES.txt':return
    for label,pattern in PATTERNS.items():
        if re.search(pattern,data):
            raise ValueError(f'{name}: possible {label}; inspect locally before release')


def check_archive(path):
    expected={p.relative_to(PACKAGE_ROOT).as_posix() for p in source_paths()}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:raise ValueError('Corrupt archive')
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive entries')
        for entry in archive.infolist():
            parts=PurePosixPath(entry.filename).parts
            if not parts or parts[0]!=PREFIX or '..' in parts or '\\' in entry.filename:
                raise ValueError('Unsafe archive path')
            name='/'.join(parts[1:])
            built=name.startswith(('frontend/build/','quest/site/'))
            binary=name in ('deskdanced/target/release/deskdanced','deskdanced/target/release/deskdanced.exe')
            if name not in expected and not built and not binary:
                raise ValueError(f'File outside release allowlist: {name}')
            if built and PurePosixPath(name).suffix not in {'.js','.css','.html','.json','.svg','.png','.ico','.txt'}:
                raise ValueError(f'Unexpected built asset: {name}')
            check_content(name,archive.read(entry))
        required={PREFIX+'/'+name for name in expected}
        if not required.issubset(set(names)):raise ValueError('Incomplete archive')


def audit_git():
    result=subprocess.run(['git','ls-files','--cached','-z'],cwd=ROOT,capture_output=True,check=True)
    allowed={p.relative_to(ROOT).as_posix() for p in source_paths()}
    tracked=set(result.stdout.decode().split('\0'))-{''}
    unexpected=tracked-allowed
    if unexpected:raise ValueError('Unexpected tracked files: '+', '.join(sorted(unexpected)))
    missing=allowed-tracked
    if missing:raise ValueError('Source files missing from Git index: '+', '.join(sorted(missing)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,action='append',default=[])
    parser.add_argument('--git',action='store_true')
    args=parser.parse_args()
    paths=source_paths()
    for path in paths:check_content(path.relative_to(ROOT).as_posix(),path.read_bytes())
    if args.git:audit_git()
    for path in args.archive:check_archive(path)
    print(f'Release audit passed: {len(paths)} source files, {len(args.archive)} archive(s).')


if __name__=='__main__':main()
