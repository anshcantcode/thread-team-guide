"""Fetch/reuse the SHA-pinned b10930 source archive without Git remote operations."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cached', type=Path)
    args = parser.parse_args()
    config = json.loads((Path(__file__).resolve().parents[1] / 'config/fdb3-linux-build.json').read_text())
    with args.output.open('xb') as target:
        if args.cached and args.cached.is_file():
            with args.cached.open('rb') as source:
                shutil.copyfileobj(source, target)
        else:
            with urllib.request.urlopen(config['llama_source_url'], timeout=60) as response:
                shutil.copyfileobj(response, target)
    with args.output.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != config['llama_source_sha256']:
            raise ValueError('Wrong llama.cpp source archive; preserve failed download and stop')


if __name__ == '__main__':
    main()
