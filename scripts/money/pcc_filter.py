import sys, os, json, glob, csv, collections, re
sys.path.insert(0, sys.argv[1])
from roster import BAN2OUTLET, BAN2NAME
root=sys.argv[2]
ban2out=dict(BAN2OUTLET); ban2name=dict(BAN2NAME)
recs={}
for p in glob.glob(os.path.join(root,'raw','*','*.json')):
    for r in json.load(open(p)).get('records',[]):
        k=(r['unit_id'],r['job_number'],r['filename'])
        recs.setdefault(k,r)
rows=[]
for (uid,job,fn),r in recs.items():
    co=r['brief'].get('companies') or {}
    idk=co.get('id_key') or {}; nmk=co.get('name_key') or {}
    for ban in co.get('ids') or []:
        if ban not in ban2out: continue
        slots={x.split(':')[1] for x in idk.get(ban,[]) if x.startswith('投標廠商:')}
        names=[nm for nm,ks in nmk.items() if any(k.startswith('投標廠商:') and k.split(':')[1] in slots for k in ks)]
        won=any(any(('得標廠商' in k and '未得標' not in k) for k in nmk.get(nm,[])) for nm in names)
        lost=any(any('未得標' in k for k in nmk.get(nm,[])) for nm in names)
        rows.append({'date':r['date'],'year':str(r['date'])[:4],'type':r['brief'].get('type'),'title':r['brief'].get('title'),'unit_id':uid,'unit_name':r.get('unit_name'),'job_number':job,'filename':fn,'ban':ban,'vendor':ban2name[ban],'outlet':ban2out[ban],'role':'得標' if won else ('未得標' if lost else '投標/其他'),'tender_api_url':r.get('tender_api_url'),'url':'https://pcc-api.openfun.app'+r.get('url','')})
print('unique announcements',len(recs),'roster hits',len(rows))
out=os.path.join(root,'derived'); os.makedirs(out,exist_ok=True)
with open(os.path.join(out,'roster_hits_all.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(sorted(rows,key=lambda x:(x['outlet'],x['date'])))
c=collections.Counter((x['outlet'],x['type'],x['role']) for x in rows)
aw=[x for x in rows if x['type']=='決標公告' and x['role']=='得標' and x['date']>=20120101]
print('award winners >=2012:',len(aw),'unique tenders',len({(x['unit_id'],x['job_number'],x['filename']) for x in aw}))
byo=collections.Counter(x['outlet'] for x in aw); print(byo)
yr=collections.Counter(x['year'] for x in aw); print(sorted(yr.items()))
def cat(t):
    t=t or ''
    if re.search('訂閱|訂購.*報|報紙|期刊|雜誌|書報',t): return '報紙/期刊訂閱'
    if re.search('宣導|廣告|行銷|推廣|託播|媒體|露出|置入|專題|形象|節目|轉播|直播|影片|影音|活動',t): return '宣導/廣告/活動/節目'
    if re.search('資料庫|新聞稿|圖片|授權|新聞服務|即時新聞|影像',t): return '資料庫/授權'
    return '其他'
cc=collections.Counter((x['outlet'],cat(x['title'])) for x in aw)
json.dump({'unique_announcements':len(recs),'roster_hits':len(rows),'by_outlet_type_role':{'|'.join(k):v for k,v in c.items()},'award_winner_rows_2012plus':len(aw),'by_outlet':byo,'by_year':dict(sorted(yr.items())),'by_outlet_category':{'|'.join(k):v for k,v in cc.items()},'roster':ban2name},open(os.path.join(out,'summary.json'),'w'),ensure_ascii=False,indent=1)
with open(os.path.join(out,'award_winners_2012plus.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(aw[0].keys())+['category']); w.writeheader()
    for x in sorted(aw,key=lambda x:(x['outlet'],x['date'])): w.writerow({**x,'category':cat(x['title'])})
print(sorted(cc.items()))
