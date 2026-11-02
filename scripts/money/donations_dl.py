import sys, csv, re, os, json, datetime, urllib.parse
sys.path.insert(0, sys.argv[1])
from polite import download
catalog, outroot = sys.argv[2], sys.argv[3]
csv.field_size_limit(10**9)
rows=[r for r in csv.DictReader(open(catalog,encoding='utf-8-sig')) if r['提供機關']=='監察院' and '政治獻金' in r['資料集名稱']]
skip=re.compile(r'里長|村\(里\)|鄉\(鎮|區民代表|區長|專戶許可|鄉長|鎮長|市長補選|議員補選')
keep=[r for r in rows if not skip.search(r['資料集名稱']) or ('立法委員' in r['資料集名稱'])]
os.makedirs(outroot,exist_ok=True)
manifest=[]
for r in sorted(keep,key=lambda r:r['資料集識別碼']):
    did=r['資料集識別碼']; urls=[u for u in r['資料下載網址'].split(';') if u.strip()]
    d=os.path.join(outroot,'zips',did); os.makedirs(d,exist_ok=True)
    for i,u in enumerate(urls):
        p=os.path.join(d,f'{i:02d}.zip')
        if os.path.exists(p) and os.path.getsize(p)>0: res='cached'
        else: res=download(u,p,delay=3)
        manifest.append({'dataset_id':did,'title':r['資料集名稱'],'idx':i,'url':u,'file':os.path.relpath(p,outroot),'result':res,'license':r['授權方式'],'downloaded':datetime.date.today().isoformat()})
        print(did,i,res,flush=True)
json.dump(manifest,open(os.path.join(outroot,'download_manifest.json'),'w'),ensure_ascii=False,indent=1)
print('done',len(manifest))
