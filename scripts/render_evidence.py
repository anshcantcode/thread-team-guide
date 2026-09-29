"""Export portable, interactive review evidence from measured reports, not mocks."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_matches(report):
    hashes = report.get('source_sha256_at_start', report.get('source_sha256', {}))
    core = {str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT/'thread_agent').glob('*.py')}
    return bool(hashes) and core <= hashes.keys() and all(
        (ROOT/name).exists() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())


def main():
    replay = json.loads((ROOT/'reports/theme5-replay.json').read_text())
    models = []
    paths = {*((ROOT/'reports').glob('theme5-acceptance-*-full.json')),
             *((ROOT/'reports').glob('theme5-acceptance-*-subset.json'))}
    for path in sorted(paths):
        report = json.loads(path.read_text())
        models.append({'model': report['model'], 'passed': sum(c['passed'] for c in report['cases']),
            'scope': 'Declared regression subset' if path.name.endswith('-subset.json') else 'Full development corpus',
            'report': path.name,
            'total': len(report['cases']), 'source_matches': source_matches(report),
            'corpus': report.get('corpus_file', 'evaluation/corpus.json'),
            'completed': report.get('completed', len(report['cases']) == 30 and not report.get('interrupted_by_provider')),
            'expected': report.get('expected_case_count', 30),
            'cases': [{k: c[k] for k in ('id', 'mode', 'passed', 'input', 'checks', 'responses', 'timing_ms')} for c in report['cases']]})
    data = {'scenario_count': replay['scenario_count'], 'executions': replay['executions'], 'seeds': replay['seeds'],
        'passed': replay['passed'], 'source_matches': source_matches(replay),
        'scenarios': [{k: c[k] for k in ('scenario', 'checks', 'trace', 'inputs', 'effects', 'state')} for c in replay['cases'] if c['seed'] == 0], 'models': models}
    template = (ROOT/'evaluation/evidence-template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=True).replace('<', '\\u003c').replace('&', '\\u0026')
    destination = ROOT/'reports/theme5-evidence.html'
    destination.write_text(template.replace('/*__EVIDENCE__*/null', payload), encoding='utf-8')
    print(destination)


if __name__ == '__main__': main()
