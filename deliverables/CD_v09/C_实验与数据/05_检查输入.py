from pathlib import Path
import json, hashlib, csv
p=Path(__file__).resolve().parent
rows=[json.loads(x) for x in (p/'01_两题输入.jsonl').read_text(encoding='utf-8').splitlines()]
assert {r['question_id'] for r in rows}=={'P-A07','P-A08'}
for r in rows:
    digest=r.pop('payload_sha256')
    raw=json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()==digest
    assert r['question_time_bjt']>r['evidence_cutoff_bjt']
    assert not ({'answer','gold','candidate_class','company_reply'} & set(r))
    for e in r['evidence']:
        assert hashlib.sha256(e['text'].encode()).hexdigest()==e['text_sha256']
        assert e['disclosure_date']<r['evidence_cutoff_bjt'][:10]
with (p/'03_八次调用记录_空白模板.csv').open(encoding='utf-8-sig') as f: runs=list(csv.DictReader(f))
assert len(runs)==8
assert len({(x['question_id'],x['model_family'],x['flow']) for x in runs})==8
assert all(x['status']=='not_run' and x['actual_fee_yuan']=='' for x in runs)
print('输入哈希、时点和8个待运行槽位校验通过。本脚本没有发起API调用。')
