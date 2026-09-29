"""Summarize every attempted case, rejecting raw fallback passes and retaining gaps."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time


def judged_pass(evaluation):
    requests=evaluation.get('judge_requests',[])
    native=evaluation.get('native_judge_calls')
    return (evaluation.get('strict',{}).get('passed') is True
        and evaluation.get('judge_enabled') is True and not evaluation.get('infrastructure_error')
        and bool(requests) and all(r.get('valid') is True and r.get('status_code')==200 for r in requests)
        and (native is None or len(native)==len(requests)
             and all(r.get('outcome')=='success' and r.get('inference_requests')==1
                     and r.get('native_response',{}).get('truncated') is not True for r in native)))


def summarize(path):
    report=json.loads((path/'report.json').read_text(encoding='utf-8'))
    cases=[]
    counts=Counter()
    for index,case in enumerate(report['cases']):
        directory=path/f'case-{index:03d}'
        def read(name):
            file=directory/name
            return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        inference,evaluation=read('inference/result.json'),read('evaluation.json')
        valid=(case['status']=='completed' and inference.get('status')=='completed' and judged_pass(evaluation))
        if case['status']!='completed' or evaluation.get('infrastructure_error'):
            category='infrastructure'
        elif valid:
            category='valid_local_strict_pass'
        elif evaluation.get('strict',{}).get('checks',{}).get('tool_selection',{}).get('passed') is False:
            category='tool_selection'
        else:
            category='arguments_or_response'
        counts[category]+=1
        cases.append({'index':index,'recording':case['recording'],'category':category,
            'valid_local_strict_pass':valid,'raw_strict_pass':evaluation.get('strict',{}).get('passed'),
            'failure_reason':case.get('failure_reason'),'inference_error':inference.get('error_type'),
            'model_error_types':[r.get('error_type') for r in inference.get('model_requests',[]) if r.get('outcome')=='error'],
            'actual_tool_count':len(inference.get('actual_tool_calls',[])) if inference else None,
            'tool_journal':case.get('tool_journal'),
            'tool_accounting':case.get('tool_accounting'),
            'actual_tools':[c['function'] for c in inference.get('actual_tool_calls',[])],
            'evidence_directory':directory.as_posix(),
            'disposition':'No repair validated on this frozen run; preserve evidence.'})
    return {'run_id':report['run_id'],'recorded_at':time.time(),'status':report['status'],
        'qualification':False,'expected':100,'attempted':len(cases),'unattempted':100-len(cases),
        'counts':dict(counts),'cases':cases,
        'limitations':['Local judge is not the organizer judge.','Infrastructure failures are not valid passes.',
                       'Categories are mechanical triage, not established root causes.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=summarize(args.run)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('run_id','status','attempted','unattempted','counts')}))
