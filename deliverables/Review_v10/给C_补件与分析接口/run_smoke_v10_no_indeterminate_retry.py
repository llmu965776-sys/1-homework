"""Two-question smoke experiment. Python standard library only; default is dry run."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time
from datetime import datetime, timezone, timedelta
from urllib import request, error, parse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / '材料'
A = ROOT / '给A'
D = ROOT / '给D'
BJT = timezone(timedelta(hours=8))
MODELS = {
    'DeepSeek': {'model': 'deepseek-flash', 'env': 'DEEPSEEK_API_KEY',
                 'url': 'https://api.deepseek.com/chat/completions',
                 'region': '账户地域待确认', 'thinking': {'type': 'disabled'}},
    '千问': {'model': 'qwen3.7-flash-2026-07-15', 'env': 'DASHSCOPE_API_KEY',
           'region': '华北2（北京）', 'enable_thinking': False},
}


def now():
    return datetime.now(BJT).isoformat(timespec='milliseconds')


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def env(name):
    # Also read User variables so an already running Codex process need not restart.
    value = os.environ.get(name, '')
    if not value and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                value = winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            pass
    return value.strip()


def validate():
    questions = [json.loads(x) for x in (DATA / '01_两题输入.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    if {q['question_id'] for q in questions} != {'P-A07', 'P-A08'} or len(questions) != 2:
        raise ValueError('Question scope changed')
    for q in questions:
        payload = {k: v for k, v in q.items() if k != 'payload_sha256'}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != q['payload_sha256']:
            raise ValueError('Question hash mismatch')
        if not q['question_time_bjt'] > q['evidence_cutoff_bjt']:
            raise ValueError('Evidence cutoff violation')
        if {'answer', 'gold', 'company_reply', 'candidate_class'} & q.keys():
            raise ValueError('Forbidden input field')
        for e in q['evidence']:
            if hashlib.sha256(e['text'].encode()).hexdigest() != e['text_sha256']:
                raise ValueError('Evidence hash mismatch')
            if not e['disclosure_date'] < q['evidence_cutoff_bjt'][:10]:
                raise ValueError('Evidence date violation')
    slots = read_csv(DATA / '03_八次调用记录_空白模板.csv')
    mapping = read_csv(DATA / '09_匿名映射_仅交A勿发D.csv')
    expected = {(q, m, f) for q in ('P-A07', 'P-A08') for m in MODELS for f in ('direct', 'boundary')}
    if len(slots) != 8 or {(s['question_id'], s['model_family'], s['flow']) for s in slots} != expected:
        raise ValueError('Invalid planned slots')
    if len(mapping) != 8 or {m['run_id'] for m in mapping} != {s['run_id'] for s in slots} or len({m['anonymous_id'] for m in mapping}) != 8:
        raise ValueError('Invalid anonymous mapping')
    return {q['question_id']: q for q in questions}, slots, mapping


def payload_for(q, slot, prompts):
    config = MODELS[slot['model_family']]
    # Fixed original question/evidence text; no official reply or web retrieval.
    model_input = {k: q[k] for k in ('company', 'question_time_bjt', 'evidence_cutoff_bjt', 'question', 'evidence') if k in q}
    return {'model': config['model'], 'temperature': 0, 'max_tokens': 2048, 'stream': False,
            **{k: config[k] for k in ('thinking', 'enable_thinking') if k in config},
            'messages': [{'role': 'system', 'content': prompts['common_system']},
                         {'role': 'user', 'content': prompts[slot['flow']] + '\n' + json.dumps(model_input, ensure_ascii=False)}]}


def endpoint(family):
    if family == 'DeepSeek':
        return MODELS[family]['url']
    base = env('DASHSCOPE_BASE_URL').rstrip('/')
    u = parse.urlparse(base)
    if u.scheme != 'https' or u.username or u.password or u.query or u.fragment or u.port not in (None, 443):
        raise ValueError('Invalid HTTPS Base URL')
    if u.hostname != 'dashscope.aliyuncs.com' and not re.fullmatch(r'[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com', u.hostname or ''):
        raise ValueError('Base URL is not a Beijing official endpoint')
    if u.path != '/compatible-mode/v1':
        raise ValueError('Base URL must end in /compatible-mode/v1')
    return base + '/chat/completions'


def fee(family, usage, called):
    i, o = usage.get('prompt_tokens'), usage.get('completion_tokens')
    if not isinstance(i, int) or not isinstance(o, int):
        return '', 'missing_usage'
    if family == 'DeepSeek':
        hit = usage.get('prompt_cache_hit_tokens')
        miss = usage.get('prompt_cache_miss_tokens')
        if not isinstance(hit, int) or not isinstance(miss, int) or hit + miss != i:
            return '', 'missing_or_inconsistent_cache_usage'
        # Audited execution dates. 2026-10-24 is Saturday and is off-peak.
        if called[:10] not in ('2026-10-23', '2026-10-24'):
            return '', 'price_or_holiday_review_required'
        dt = datetime.fromisoformat(called)
        minute = dt.hour * 60 + dt.minute
        peak = dt.weekday() < 5 and (540 <= minute < 720 or 840 <= minute < 1080)
        rates = (2, .04, 8) if peak else (1, .02, 4)
        return (miss * rates[0] + hit * rates[1] + o * rates[2]) / 1e6, 'public_CNY_peak' if peak else 'public_CNY_off_peak'
    hit = usage.get('prompt_tokens_details', {}).get('cached_tokens')
    if not isinstance(hit, int) or not 0 <= hit <= i:
        return '', 'missing_cache_usage'
    rates = (.2, .04, .8) if i <= 32000 else (.6, .12, 2.4) if i <= 256000 else (1.2, .24, 4.8) if i <= 1000000 else None
    if rates is None:
        return '', 'unpriced_tier'
    return ((i - hit) * rates[0] + hit * rates[1] + o * rates[2]) / 1e6, 'public_CNY_implicit_cache'


def parse_output(response, q, flow):
    choices = response.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, 'schema_error', {'finish_reason': '', 'operations': [], 'flags': ['missing_choice']}
    choice = choices[0]
    reason = choice.get('finish_reason', '')
    message = choice.get('message') or {}
    content = message.get('content') if isinstance(message, dict) else None
    log = {'finish_reason': reason, 'operations': [], 'flags': []}
    if not isinstance(content, str) or not content.strip():
        return None, 'empty_output', log
    try:
        obj = json.loads(content)
    except (ValueError, TypeError):
        return None, 'truncated' if reason == 'length' else 'parse_error', log
    if not isinstance(obj, dict) or not isinstance(obj.get('final_answer'), str) or not obj['final_answer'].strip() or not isinstance(obj.get('citations'), list) or not all(isinstance(x, str) for x in obj['citations']):
        return None, 'schema_error', log
    answer = {'final_answer': obj['final_answer'], 'citations': obj['citations']}
    if flow == 'boundary':
        b = obj.get('answerability')
        if not isinstance(b, dict) or any(not isinstance(b.get(k), list) or not all(isinstance(x, str) for x in b[k]) for k in ('supported', 'missing', 'limits')):
            log['flags'].append('answerability_schema_error')
        elif len(re.findall(r'[\u4e00-\u9fff]', ''.join(sum((b[k] for k in ('supported', 'missing', 'limits')), [])))) > 120:
            log['flags'].append('answerability_over_120')
    visible = re.sub(r'\[[^\]]*\]', '', answer['final_answer'])
    if len(re.findall(r'[\u4e00-\u9fff]', visible)) > 300:
        log['flags'].append('answer_over_300')
    valid_ids = {e['page_id'] for e in q['evidence']}
    if set(answer['citations']) - valid_ids:
        log['flags'].append('unknown_citation_id')
    # Flag leakage; never silently edit substantive investor replies.
    if re.search(r'deepseek|qwen|千问|深度求索|直接生成|边界判断', answer['final_answer'], re.I):
        log['flags'].append('possible_condition_leak_requires_review')
    status = 'truncated' if reason == 'length' else 'parsed_with_flags' if log['flags'] else 'parsed'
    return answer, status, log


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward Authorization to a redirect host.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    questions, slots, mapping = validate()
    prompts = json.loads((DATA / '02_提示词.json').read_text(encoding='utf-8'))
    order = list(slots)
    random.Random(20261023).shuffle(order)
    dump(A / '校验与执行计划.json', {'checked_at_bjt': now(), 'input_checks': 'passed', 'planned_slots': 8,
                                  'execution_order': [s['run_id'] for s in order], 'seed': 20261023,
                                  'network_calls_in_dry_run': 0, 'total_project_budget_yuan': 100,
                                  'scope': '2 questions only; no formal tasks'})
    for s in slots:
        dump(A / '请求预览' / (s['run_id'] + '.json'), payload_for(questions[s['question_id']], s, prompts))
    if not args.execute:
        print('输入校验通过；已保存8个去认证头的请求预览。没有调用API。')
        return
    if (A / '批次启动.json').exists():
        raise RuntimeError('批次已启动，禁止覆盖或自动重跑；先检查原始记录。')
    missing = [m['env'] for m in MODELS.values() if not env(m['env'])]
    if missing:
        raise RuntimeError('缺少本地环境变量：' + ','.join(missing))
    urls = {family: endpoint(family) for family in MODELS}
    dump(A / '批次启动.json', {'started_at_bjt': now(), 'models': {k: {'model': v['model'], 'url': urls[k]} for k, v in MODELS.items()},
                            'max_retries': 2, 'note': 'A started attempt without result is indeterminate; do not automatically repeat.'})
    rows, picked = [], {}
    fields = list(slots[0]) + ['finish_reason','output_status','price_url','price_checked_at_bjt','invoice_period',
                              'billing_note','processing_log_file','request_id','request_file','request_body_sha256']
    opener = request.build_opener(NoRedirect)
    for slot in order:
        family = slot['model_family']
        config = MODELS[family]
        body = payload_for(questions[slot['question_id']], slot, prompts)
        encoded = json.dumps(body, ensure_ascii=False).encode('utf-8')
        previous = ''
        for attempt in range(3):
            rid = slot['run_id'] + (f'-R{attempt}' if attempt else '')
            folder = A / '原始记录' / rid
            called = now()
            dump(folder / 'request.json', {'url': urls[family], 'method': 'POST', 'headers': {'Content-Type': 'application/json'}, 'body': body})
            row = {**slot, 'run_id': rid, 'status': 'submitted_indeterminate', 'model_id': config['model'],
                   'region': config['region'], 'called_at_bjt': called, 'retry_of': previous,
                   'parameters_json': json.dumps({k: v for k, v in body.items() if k != 'messages'}, ensure_ascii=False),
                   'request_file': str((folder / 'request.json').relative_to(ROOT)),
                   'request_body_sha256': hashlib.sha256(encoded).hexdigest(),
                   'price_url': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/' if family == 'DeepSeek' else 'https://help.aliyun.com/zh/model-studio/qwen3-7-flash',
                   'price_checked_at_bjt': '2026-10-24', 'actual_fee_yuan': '', 'invoice_period': ''}
            rows.append(row)
            write_csv(A / '八次运行_全部尝试.csv', rows, fields)
            req = request.Request(urls[family], data=encoded, headers={'Authorization': 'Bearer ' + env(config['env']), 'Content-Type': 'application/json'})
            start = time.perf_counter()
            code, raw, response_headers, network_error = None, b'', {}, ''
            try:
                with opener.open(req, timeout=120) as response:
                    code, raw, response_headers = response.status, response.read(), dict(response.headers)
            except error.HTTPError as exc:
                code, raw, response_headers = exc.code, exc.read(), dict(exc.headers)
            except (error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                network_error = type(exc).__name__  # Do not log secrets or request headers.
            row['latency_ms'] = round((time.perf_counter() - start) * 1000)
            (folder / 'response.bin').write_bytes(raw)
            dump(folder / 'transport.json', {'http_status': code, 'error_type': network_error,
                                           'request_id': response_headers.get('x-request-id', ''), 'finished_at_bjt': now()})
            row['raw_output_file'] = str((folder / 'response.bin').relative_to(ROOT))
            try:
                parsed_response = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                parsed_response = {}
            if not isinstance(parsed_response, dict):
                parsed_response = {}
            usage = parsed_response.get('usage') or {}
            dump(folder / 'usage.json', usage)
            row.update(input_tokens=usage.get('prompt_tokens', ''), output_tokens=usage.get('completion_tokens', ''),
                       cached_input_tokens=usage.get('prompt_cache_hit_tokens', usage.get('prompt_tokens_details', {}).get('cached_tokens', '')),
                       reasoning_tokens=usage.get('completion_tokens_details', {}).get('reasoning_tokens', ''),
                       model_version=parsed_response.get('model', ''), request_id=parsed_response.get('id', response_headers.get('x-request-id', '')))
            row['reference_price_fee_yuan'], row['billing_note'] = fee(family, usage, called)
            answer = None
            if code is not None and 200 <= code < 300:
                row['status'] = 'response_received'
                answer, output_status, log = parse_output(parsed_response, questions[slot['question_id']], slot['flow'])
                row['output_status'] = output_status
                row['finish_reason'] = log['finish_reason']
                dump(folder / 'processing.json', log)
                row['processing_log_file'] = str((folder / 'processing.json').relative_to(ROOT))
                if answer:
                    dump(folder / 'answer.json', answer)
                    row['final_answer_file'] = str((folder / 'answer.json').relative_to(ROOT))
            else:
                row.update(status='network_error' if network_error else 'http_error', http_error=network_error or str(code), output_status='no_scorable_output')
            picked[slot['run_id']] = (row, answer)
            write_csv(A / '八次运行_全部尝试.csv', rows, fields)
            # Network result is indeterminate: retain it and do not automatically repeat.
            retry = not network_error and (code == 429 or (code is not None and 500 <= code < 600))
            if not retry or attempt == 2:
                break
            previous = rid
            time.sleep(2 ** attempt)
        print(slot['run_id'] + ': ' + row['status'] + '/' + row['output_status'])
    anonymous = []
    for m in mapping:
        row, answer = picked[m['run_id']]
        m['status'] = row['status'] + '/' + row['output_status']
        # D receives only the required scoring view; no condition labels or checklist.
        anonymous.append({'anonymous_id': m['anonymous_id'], 'question_id': m['question_id'],
                          'final_answer': answer['final_answer'] if answer else '',
                          'citations_json': json.dumps(answer['citations'], ensure_ascii=False) if answer else '',
                          'output_status': '' if answer else row['output_status']})
    write_csv(A / '09_匿名映射_仅交A.csv', mapping, list(mapping[0]))
    leaked = [r for r in rows if r.get('processing_log_file') and 'possible_condition_leak_requires_review' in json.loads((ROOT / r['processing_log_file']).read_text(encoding='utf-8'))['flags']]
    destination = A / '匿名输出_标签泄露待复核.csv' if leaked else D / '匿名输出.csv'
    write_csv(destination, anonymous, ['anonymous_id','question_id','final_answer','citations_json','output_status'])
    dump(A / '批次结束.json', {'finished_at_bjt': now(), 'planned_slots': 8, 'attempts': len(rows),
                            'actual_fees': 'await_account_invoice', 'next': 'A reviews flags and sends only anonymous output to D'})


if __name__ == '__main__':
    main()
