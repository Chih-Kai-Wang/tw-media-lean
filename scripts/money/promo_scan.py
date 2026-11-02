import sys, os, json, csv, io, collections, re, zipfile
sys.path.insert(0, sys.argv[1])
from roster import NAME_PATTERNS
root=sys.argv[2]
man=json.load(open(os.path.join(root,'download_manifest.json')))
csv.field_size_limit(10**9)
def dec(b):
    for e in ('utf-8-sig','cp950','big5hkscs','utf-16'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','replace')
def num(x):
    s=re.sub(r'[^\d.\-]','',str(x))
    try: return float(s) if s not in ('','-','.') else 0.0
    except: return 0.0
def records(path,fmt,b):
    if fmt=='CSV' or path.endswith('.csv'):
        t=dec(b)
        if t.lstrip().startswith('<'): return None
        try: return list(csv.DictReader(io.StringIO(t,newline='')))
        except Exception: return None
    if fmt=='JSON' or path.endswith('.json'):
        try: j=json.loads(dec(b))
        except Exception: return None
        if isinstance(j,dict):
            for k in ('result','records','data','Data','items'):
                if isinstance(j.get(k),list): j=j[k]; break
            else:
                vals=[v for v in j.values() if isinstance(v,list)]
                j=vals[0] if vals else [j]
        return [r for r in j if isinstance(r,dict)] if isinstance(j,list) else None
    return None
YR=re.compile(r'^(年度|年|Year|資料所屬年度|執行年度|統計年份|year|年月|日期|資料年)',re.I)
per_ds=collections.OrderedDict()
outlet_tot=collections.defaultdict(lambda:collections.defaultdict(lambda:[0,0.0]))
for m in man:
    did=m['dataset_id']; d=per_ds.setdefault(did,{'title':m['title'],'agency':m['agency'],'files':0,'downloaded':0,'robots_blocked':0,'tabular_files':0,'rows':0,'index_only':False,'has_target_col':False,'years':set(),'outlet_rows':collections.Counter()})
    d['files']+=1
    if m['result']=='robots_disallow': d['robots_blocked']+=1; continue
    p=os.path.join(root,m['file'])
    if not os.path.exists(p) or os.path.getsize(p)==0: continue
    d['downloaded']+=1
    b=open(p,'rb').read()
    recs=records(p,m['format'],b)
    if recs is None: continue
    d['tabular_files']+=1; d['rows']+=len(recs)
    if recs:
        cols=list(recs[0].keys())
        if any(re.search('網址|連結|URL|Url|link|Link|路徑|FileUrl|檔案連結',str(c)) for c in cols) and not any('金額' in str(c) for c in cols): d['index_only']=True
        tcols=[c for c in cols if c and re.search('託播|托播|刊登|廠商|媒體名稱|對象',str(c))]
        if tcols: d['has_target_col']=True
        acol=next((c for c in cols if c and re.search('金額|AMOUNT|Amount|值',str(c))),None)
        ycols=[c for c in cols if c and YR.search(str(c).strip())]
    for r in recs:
        txt=' '.join(str(v) for v in r.values() if v is not None)
        for c in ycols[:1]:
            mm=re.match(r'\s*(\d{2,4})',str(r.get(c,'')))
            if mm:
                y=int(mm.group(1)); y=y+1911 if y<200 else (y//100+1911 if 1000<=y<2000 and len(mm.group(1))==4 and y<1300 else y)
                if 2000<=y<=2030: d['years'].add(y)
        for o,pats in NAME_PATTERNS.items():
            if any(pt in txt for pt in pats):
                d['outlet_rows'][o]+=1
                a=num(r.get(acol,0)) if acol else 0
                outlet_tot[o][did][0]+=1; outlet_tot[o][did][1]+=a
out=sys.argv[3]
with open(os.path.join(out,'dataset_summary.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['dataset_id','title','agency','resources','downloaded','robots_blocked','tabular_files','rows','index_only(links to PDF/ODS)','has_media_or_vendor_col','year_min','year_max','rows_mentioning_outlets'])
    for did,d in per_ds.items():
        ys=sorted(d['years'])
        w.writerow([did,d['title'],d['agency'],d['files'],d['downloaded'],d['robots_blocked'],d['tabular_files'],d['rows'],d['index_only'],d['has_target_col'],ys[0] if ys else '',ys[-1] if ys else '',json.dumps(dict(d['outlet_rows']),ensure_ascii=False)])
with open(os.path.join(out,'outlet_mentions_by_dataset.csv'),'w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['outlet','dataset_id','rows_mentioning','sum_amount_col_ntd(rough; rows may bundle several media)'])
    for o in NAME_PATTERNS:
        for did,(n,a) in sorted(outlet_tot[o].items(),key=lambda x:-x[1][0]): w.writerow([o,did,n,round(a)])
tot_rows=sum(d['rows'] for d in per_ds.values())
print('datasets',len(per_ds),'rows',tot_rows,'index_only',sum(d['index_only'] for d in per_ds.values()),'with target col',sum(d['has_target_col'] for d in per_ds.values()))
for o in NAME_PATTERNS: print(o, sum(v[0] for v in outlet_tot[o].values()), len(outlet_tot[o]))
