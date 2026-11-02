import sys, csv, re, os, json, datetime, urllib.parse, urllib.robotparser
sys.path.insert(0, sys.argv[1])
from polite import download, get, UA
catalog, outroot = sys.argv[2], sys.argv[3]
csv.field_size_limit(10**9)
rows=list(csv.DictReader(open(catalog,encoding='utf-8-sig')))
hits=[r for r in rows if re.search('政策宣導|政策及業務宣導|業務宣導|置入性|宣導.*廣告|媒體.*宣導',r['資料集名稱'])]
excl={'122841','20917','174263','11433','11434','22555','157886'}
hits=[r for r in hits if r['資料集識別碼'] not in excl]
robots={}
def allowed(u):
    pu=urllib.parse.urlparse(u); key=pu.scheme+'://'+pu.netloc
    if key not in robots:
        st,b,ct=get(key+'/robots.txt',delay=2.5,timeout=30,retries=0)
        rp=urllib.robotparser.RobotFileParser()
        txt=b.decode('utf-8','replace') if st==200 and 'html' not in ct.lower() else ''
        rp.parse(txt.splitlines()); robots[key]=(rp,st,bool(txt))
    rp=robots[key][0]
    return rp.can_fetch(UA,u)
EXT={'CSV':'csv','JSON':'json','XML':'xml','ZIP':'zip','ODS':'ods','XLSX':'xlsx','XLS':'xls','PDF':'pdf'}
manifest=[]
import collections as _c
fails=_c.Counter()
for r in hits:
    did=r['資料集識別碼']
    urls=[u.strip() for u in r['資料下載網址'].split(';')]
    fmts=[f.strip().upper() for f in r['檔案格式'].split(';')]
    pairs=[(i,u,fmts[i] if i<len(fmts) else '') for i,u in enumerate(urls) if u]
    has_csv=any(f=='CSV' for _,_,f in pairs)
    if has_csv: pairs=[p for p in pairs if p[2]=='CSV']
    elif any(f=='JSON' for _,_,f in pairs): pairs=[p for p in pairs if p[2] in ('JSON','ZIP','ODS','XLSX','XLS','其他','')]
    d=os.path.join(outroot,'raw',did); os.makedirs(d,exist_ok=True)
    for i,u,f in pairs:
        p=os.path.join(d,f'{i:03d}.{EXT.get(f,"bin")}')
        if os.path.exists(p) and os.path.getsize(p)>0: res='cached'
        elif not allowed(u): res='robots_disallow'
        elif fails[urllib.parse.urlparse(u).netloc]>=4: res='skipped_host_unresponsive'
        else:
            res=download(u,p,delay=2.5,timeout=40)
            h=urllib.parse.urlparse(u).netloc
            if res.startswith('000') or res.startswith('5'): fails[h]+=1
            else: fails[h]=0
        manifest.append({'dataset_id':did,'title':r['資料集名稱'],'agency':r['提供機關'],'idx':i,'format':f,'url':u,'file':os.path.relpath(p,outroot),'result':res,'license':r['授權方式'],'fields':r['主要欄位說明'],'downloaded':datetime.date.today().isoformat()})
        print(did,i,f,res,flush=True)
json.dump(manifest,open(os.path.join(outroot,'download_manifest.json'),'w'),ensure_ascii=False,indent=1)
json.dump({k:{'status':v[1],'has_rules':v[2]} for k,v in robots.items()},open(os.path.join(outroot,'robots_checked.json'),'w'),indent=1)
print('done',len(manifest))
