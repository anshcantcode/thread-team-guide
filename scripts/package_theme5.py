"""Create and verify a local source/evidence archive; does not publish or tag it."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    names = {name for name in tracked if name}
    patterns = ['reports/theme5-*.json','reports/theme5-evidence.html','reports/verification-expanded.json',
        'reports/independent-acceptance-initial.json','reports/independent-development-*.json',
        'reports/independent-fresh-six-initial.json','reports/native-live-*-session.json',
        'reports/android-release-microphone-check.json','reports/android17-gemini-research.md',
        'reports/reviewer/round*-review.md','reports/reviewer/round*-results.json',
        'reports/reviewer/round*-manual-review.json','reports/reviewer/acceptance-slice/**/*',
        'reports/reviewer/acceptance-slice-2/**/*','reports/reviewer/round*-frozen/**/*',
        'reports/reviewer/*.py']
    for pattern in patterns:
        names.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern) if p.is_file() and '__pycache__' not in p.parts)
    payloads = {}
    for name in sorted(names):
        path = ROOT/name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('A package member is missing or outside the workspace: '+name)
        if path.name == '.env' or any(part in ('.runtime','.venv','data','node_modules','.git') for part in Path(name).parts):
            raise ValueError('Private/runtime files must not be included: '+name)
        content = path.read_bytes()
        if re.search(rb'AIza[0-9A-Za-z_-]{35}',content):
            raise ValueError('Credential-shaped text found; archive was not written: '+name)
        payloads[name] = content
    record = {'format':'THREAD source and evidence package v1','git_revision':revision,
        'scope':'Workspace source bytes plus selected measured evidence. Local review archive, not an official submission.',
        'limitations':['Organizer transport compatibility and Docker execution remain unverified unless a later report explicitly proves them.',
            'Includes historical failed reports; compare core hashes and review dates before making claims.',
            'Team identity, signed forms, final presentation/video and official release tag are separate team steps.'],
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}}
    folder = ROOT/'reports/packages'
    folder.mkdir(parents=True,exist_ok=True)
    destination = folder/f'THREAD-source-evidence-{revision[:7]}.zip'
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,content in payloads.items(): archive.writestr('THREAD/'+name,content)
        archive.writestr('THREAD/PACKAGE_MANIFEST.json',json.dumps(record,indent=2))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name,digest in record['files'].items():
            assert hashlib.sha256(archive.read('THREAD/'+name)).hexdigest()==digest
    result = {'archive':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
              'files':len(record['files']),'bytes':destination.stat().st_size,'verified':True,'git_revision':revision}
    (folder/'latest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
