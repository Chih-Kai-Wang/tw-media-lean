import sys, os, json, csv, glob, hashlib, re, collections
root=sys.argv[1]
aw=list(csv.DictReader(open(os.path.join(root,'derived','award_winners_2012plus.csv'),encoding='utf-8')))
def money(s):
    s=re.sub(r'[^\d.]','',str(s or ''))
    try: return float(s) if s else None
    except: return None
out=[]; fetched=0; missing=0
for a in aw:
    fn=os.path.join(root,'tender_detail',hashlib.md5(f"{a['unit_id']}|{a['job_number']}".encode()).hexdigest()+'.json')
    if not os.path.exists(fn): missing+=1; continue
    fetched+=1
    try: d=json.load(open(fn))
    except Exception: continue
    rec=next((r for r in d.get('records',[]) if r.get('filename')==a['filename']),None)
    if not rec: a2={**a,'vendor_award_ntd':'','total_award_ntd':'','note':'announcement not in detail'}; out.append(a2); continue
    det=rec.get('detail',{}) or {}
    slot=None
    for k,v in det.items():
        if re.match(r'投標廠商:投標廠商\d+:廠商代碼$',k) and str(v).strip()==a['ban']: slot=k.split(':')[1]
    va=money(det.get(f'投標廠商:{slot}:決標金額')) if slot else None
    tot=None
    for k in ('決標資料:總決標金額','已公告資料:總決標金額'):
        if k in det: tot=money(det[k]); break
    out.append({**a,'vendor_award_ntd':va if va is not None else '','total_award_ntd':tot if tot is not None else '','note':'' if va is not None else 'no per-vendor amount'})
with open(os.path.join(root,'derived','award_amounts_sample.csv'),'w',newline='',encoding='utf-8') as f:
    if out:
        w=csv.DictWriter(f,fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
s=collections.defaultdict(lambda:[0,0.0])
for o in out:
    if o['vendor_award_ntd']!='': s[o['outlet']][0]+=1; s[o['outlet']][1]+=float(o['vendor_award_ntd'])
print('award rows',len(aw),'with detail',fetched,'missing',missing,'parsed amount',sum(v[0] for v in s.values()))
for k,v in sorted(s.items(),key=lambda x:-x[1][1]): print(k,v[0],round(v[1]))
