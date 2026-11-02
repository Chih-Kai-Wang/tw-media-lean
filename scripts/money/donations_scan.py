import sys, os, json, zipfile, csv, io, collections, re
sys.path.insert(0, sys.argv[1])
from roster import ROSTER, BAN2OUTLET, NAME_PATTERNS, OWNERS
root=sys.argv[2]
man=json.load(open(os.path.join(root,'download_manifest.json')))
csv.field_size_limit(10**9)
def num(x):
    try: return float(str(x).replace(',','') or 0)
    except: return 0.0
agg=collections.defaultdict(lambda:[0,0.0])   # (title, direction, outlet, legal_or_matched_name, recipient) -> n,total
own=collections.defaultdict(lambda:[0,0.0])
stats=[]
for m in man:
    p=os.path.join(root,m['file'])
    rec={'dataset_id':m['dataset_id'],'title':m['title'],'idx':m['idx'],'bytes':os.path.getsize(p) if os.path.exists(p) else 0,'incomes_rows':0,'expenditures_rows':0,'ok':False}
    try: z=zipfile.ZipFile(p)
    except Exception as e:
        rec['error']=str(e)[:80]; stats.append(rec); continue
    rec['ok']=True
    for n in z.namelist():
        base=os.path.basename(n)
        if base not in ('incomes.csv','expenditures.csv'): continue
        direction='income' if base=='incomes.csv' else 'expenditure'
        txt=z.read(n).decode('utf-8-sig','replace')
        rd=csv.DictReader(io.StringIO(txt))
        cnt=0
        for r in rd:
            cnt+=1
            who=(r.get('捐贈者／支出對象') or '').strip(); ban=(r.get('身分證／統一編號') or '').strip()
            amt=num(r.get('收入金額')) if direction=='income' else num(r.get('支出金額'))
            recip=(r.get('擬參選人／政黨') or '').strip()
            outlet=BAN2OUTLET.get(ban.zfill(8)) if ban.isdigit() else None
            how='統編'
            if not outlet and '公共電視' in who and not re.fullmatch(r'\d{8}',ban): outlet,how='公視','名稱'
            if not outlet and not re.fullmatch(r'\d{8}',ban):
                for o,pats in NAME_PATTERNS.items():
                    if any(pt in who for pt in pats) and re.search('公司|基金會|電視|報|傳媒|媒體|社',who):
                        outlet,how=o,'名稱(未核對統編)'; break
            if outlet:
                k=(m['title'],direction,outlet,who if how!='統編' else ban+' '+who,recip,how,r.get('收支科目',''))
                agg[k][0]+=1; agg[k][1]+=amt
            if direction=='income' and who in OWNERS:
                k=(m['title'],who,recip,r.get('收支科目',''))
                own[k][0]+=1; own[k][1]+=amt
        rec[direction+'s_rows' if False else ('incomes_rows' if direction=='income' else 'expenditures_rows')]=cnt
    stats.append(rec)
out=sys.argv[3]
with open(os.path.join(out,'media_matches_aggregated.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['dataset_title','direction','outlet','counterparty(統編 名稱)','recipient_or_payer(擬參選人／政黨)','match_method','收支科目','n_rows','total_ntd'])
    for k,v in sorted(agg.items()): w.writerow(list(k)+[v[0],round(v[1])])
with open(os.path.join(out,'owner_name_matches_aggregated.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['dataset_title','donor_name(exact match, homonyms possible, UNVERIFIED)','recipient','收支科目','n_rows','total_ntd'])
    for k,v in sorted(own.items()): w.writerow(list(k)+[v[0],round(v[1])])
json.dump(stats,open(os.path.join(out,'file_stats.json'),'w'),ensure_ascii=False,indent=1)
print('files',len(stats),'ok',sum(s['ok'] for s in stats),'incomes',sum(s['incomes_rows'] for s in stats),'exp',sum(s['expenditures_rows'] for s in stats))
print('media matches',len(agg),'owner matches',len(own))
