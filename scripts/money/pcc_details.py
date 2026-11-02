# Usage: python scripts/money/pcc_details.py scripts/money data/external/money/procurement_pcc
# Fetch /api/tender detail for each unique (unit_id, job_number) among roster award winners 2012+.
# Random (seeded) order so a partial run is an unbiased sample. Resumable: skips existing files.
import sys, os, json, csv, random, hashlib
sys.path.insert(0, sys.argv[1])
from polite import get
root=sys.argv[2]
rows=list(csv.DictReader(open(os.path.join(root,'derived','award_winners_2012plus.csv'),encoding='utf-8')))
jobs=sorted({(r['unit_id'],r['job_number']) for r in rows})
random.Random(42).shuffle(jobs)
d=os.path.join(root,'tender_detail'); os.makedirs(d,exist_ok=True)
print('jobs',len(jobs),flush=True)
done=0
for uid,job in jobs:
    fn=os.path.join(d,hashlib.md5(f'{uid}|{job}'.encode()).hexdigest()+'.json')
    if os.path.exists(fn): done+=1; continue
    for attempt in range(6):
        st,b,_=get('https://pcc-api.openfun.app/api/tender',{'unit_id':uid,'job_number':job},delay=6)
        if st not in (403,429): break
        print('HTTP',st,'- waiting 10 min',flush=True)  # rate limited: back off instead of giving up
        import time; time.sleep(600)
    if st!=200:
        print('HTTP',st,uid,job,flush=True)
        if st in (403,429): break
        continue
    open(fn,'wb').write(b); done+=1
    if done%200==0: print('done',done,flush=True)
print('finished',done,flush=True)
