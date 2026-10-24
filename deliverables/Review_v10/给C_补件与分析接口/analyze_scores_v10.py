"""Offline pilot analysis for the four-dimension rubric. Never invokes an API.
Usage: python analyze_scores_v10.py --runs 02_八次核验数据.json --scores 03_裁定评分空表.csv --out results
Blank templates produce no quality estimate. Only complete adjudicated ratings are accepted.
"""
import argparse,csv,json
from pathlib import Path
from collections import defaultdict
from decimal import Decimal

FIELDS=['run_id','F','E','C','B','key_error','standard_u','factual_claims_present','citation_required','na_reason','adjudicated_by','reason','rule_version']
def empty(r):return all(not str(r.get(k,'')).strip() for k in FIELDS if k!='run_id')
def yn(r,k):
 v=str(r.get(k,'')).strip().lower()
 if v not in ('yes','no'):raise ValueError(k+' must be yes/no; blank is not no')
 return v=='yes'
def rating(r):
 if not r.get('adjudicated_by') or not r.get('rule_version') or not r.get('reason'):raise ValueError('Missing adjudicator, rule version or reason')
 if yn(r,'standard_u'):return None
 key=yn(r,'key_error');claims=yn(r,'factual_claims_present');cite=yn(r,'citation_required')
 scores=[]
 for dim in ['F','E','C','B']:
  x=str(r.get(dim,'')).strip().upper()
  if x=='NA':
   if dim not in ['F','E'] or (dim=='F' and claims) or (dim=='E' and cite) or not r.get('na_reason'):
    raise ValueError('Invalid NA in '+dim)
  elif x not in ['0','1','2']:raise ValueError('Invalid/blank score in '+dim)
  else:scores.append(int(x))
 return int(not key and all(v==2 for v in scores))

def analyze(runs,scores):
 if len({r['run_id'] for r in runs})!=len(runs):raise ValueError('Duplicate run IDs; this pilot interface expects one final attempt per slot')
 scoremap={r['run_id']:r for r in scores}
 if len(scoremap)!=len(scores) or set(scoremap)!={r['run_id'] for r in runs}:raise ValueError('Ratings must match all eight planned final attempts')
 pending=all(empty(r) for r in scores)
 if not pending and any(empty(r) for r in scores):raise ValueError('Partial ratings: retain original records; no silent exclusion')
 decisions={} if pending else {k:rating(v) for k,v in scoremap.items()}
 groups=defaultdict(list)
 for r in runs:groups[(r['model_family'],r['flow'])].append(r)
 output=[]
 for (model,flow),items in sorted(groups.items()):
  n=len(items);cost=sum((Decimal(r['reference_fee_cny']) for r in items),Decimal(0))
  p=None if pending else sum(decisions[r['run_id']]==1 for r in items)
  u=None if pending else sum(decisions[r['run_id']] is None for r in items)
  row={'model_family':model,'flow':flow,'planned_slots':n,'reference_fee_cny':str(cost),'actual_paid_cny':None,
   'ratings_status':'pending' if pending else 'adjudicated','pass_n':p,'standard_u_n':u,
   'all_slots_pass_rate_lower':None if pending else p/n,'all_slots_pass_rate_upper':None if pending else (p+u)/n,
   'resolved_subset_pass_rate':None if pending or n==u else p/(n-u),
   'cost_per_qualified':str(cost/Decimal(p)) if not pending and u==0 and p else None,
   'cost_per_qualified_best_case':str(cost/Decimal(p+u)) if not pending and p+u else None,
   'cost_per_qualified_worst_case':str(cost/Decimal(p)) if not pending and p else None,
   'zero_qualified_possible':None if pending else p==0,
   'note':'Two pilot questions only; all-slot costs retained, including U. No model ranking or formal inference.'}
  output.append(row)
 return output

def main():
 p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,required=True);p.add_argument('--scores',type=Path,required=True);p.add_argument('--out',type=Path,default=Path('analysis_v10'));a=p.parse_args()
 runs=json.loads(a.runs.read_text(encoding='utf-8'))
 with a.scores.open(encoding='utf-8-sig') as f:scores=list(csv.DictReader(f))
 output=analyze(runs,scores);a.out.mkdir(parents=True,exist_ok=True)
 (a.out/'条件汇总.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with (a.out/'条件汇总.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
 print('Offline analysis complete; quality status:',output[0]['ratings_status'])
if __name__=='__main__':main()
