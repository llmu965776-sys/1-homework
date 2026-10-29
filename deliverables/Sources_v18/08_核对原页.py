"""Verify the 11 raw questions against included PDF pages. No network or API calls.
Requires PyMuPDF (import fitz). Run: python 08_核对原页.py
"""
from pathlib import Path
import json,re,unicodedata
import fitz

root=Path(__file__).resolve().parent
rows=json.loads((root/'02_逐题核验.json').read_text(encoding='utf-8'))
def normalized(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))

assert len(rows)==11 and len({r['question_id'] for r in rows})==11
for r in rows:
    with fitz.open(root/r['selection_file']) as doc:
        original_page=doc[r['selection_physical_page']-1].get_text()
        assert normalized(r['question_raw']) in normalized(original_page),r['question_id']
    assert r['question_time_bjt'] is None
    assert r['evidence_cutoff_bjt'] is None
    assert not r['strict_time_eligible']
print('11题均与选编原页匹配；逐题提交时间和证据截止保留缺失；没有API调用。')
