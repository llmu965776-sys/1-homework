"""Local reproducibility check; reads archived records, makes no API calls.
Run: python 05_独立复算.py
"""
from pathlib import Path
from decimal import Decimal as D
import json,csv
root=Path(__file__).resolve().parent
r=json.loads((root/'data/01_八次费用复算.json').read_text(encoding='utf-8'))
assert len(r)==8 and len({x['anonymous_id'] for x in r})==8
fees=[]
for x in r:
 f=(D(x['input_tokens'])*D(x['input_rate_per_million'])+D(x['output_tokens'])*D(x['output_rate_per_million']))/D(1000000)
 assert x['cache_hit_tokens']==0 and f==D(x['reference_fee_cny'])==D(x['recalculated_fee_cny'])
 fees.append(f)
total=sum(fees,D(0));assert total==D('.0155928')
assert sum(x['input_tokens'] for x in r)==21420
assert sum(x['output_tokens'] for x in r)==1618
old=D('6836158028.21')/D(85724597);new=D('6965677978.67')/D(92664612)
sc=json.loads((root/'data/07_情景假设与结果.json').read_text(encoding='utf-8'))
for x in sc['rows']:
 human=D(x['wage_scenario_cny_per_hour'])*D(x['minutes_scenario'])/60
 c=human+total/8
 assert human==D(x['human_scenario_cny']) and c==D(x['partial_total_cny'])
 assert (total/8)*D('.5')/c==D(x['total_drop_ratio_after_API_half'])
with (root/'data/02_校准评价记录_非最终双评.csv').open(encoding='utf-8-sig') as f: ratings=list(csv.DictReader(f))
assert len(ratings)==8 and sum(x['当前门槛判定']=='通过' for x in ratings)==3
print(json.dumps({'API参考费用合计_元':str(total),'平均每次参考费用_元':str(total/8),'2024类别平均收入':str(old),'2025类别平均收入':str(new),'类别均值同比_百分比':str((new/old-1)*100),'情景校验':'通过；时间和工资是假设，非实测','质量状态':'3/8仅当前校准视图；D独立评分未收，非最终合格率'},ensure_ascii=False,indent=2))
