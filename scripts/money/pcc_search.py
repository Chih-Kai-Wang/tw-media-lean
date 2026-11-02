import sys, os, json
sys.path.insert(0, sys.argv[1])
from polite import get
out=sys.argv[2]
qs=['中央通訊社','自由時報','聯合報','聯合線上','中國時報','中時','旺旺','中天電視','中國電視','東森','ETtoday','聯利媒體','TVBS','三立電視','民間全民電視','民視','公共電視','中華電視','風傳媒','鏡傳媒','鏡電視','精鏡','鏡週刊']
API='https://pcc-api.openfun.app/api/searchbycompanyname'
for q in qs:
    d=os.path.join(out,'raw',q); os.makedirs(d,exist_ok=True)
    page=1
    while True:
        p=os.path.join(d,f'page_{page:04d}.json')
        if os.path.exists(p):
            j=json.load(open(p))
        else:
            st,b,_=get(API,{'query':q,'page':page},delay=3)
            if st!=200: print(q,page,'HTTP',st,flush=True); break
            j=json.loads(b.decode('utf-8'))
            open(p,'w').write(json.dumps(j,ensure_ascii=False))
        tp=j.get('total_pages',0)
        if page==1: print(q,'total',j.get('total_records'),'pages',tp,flush=True)
        if page>=tp: break
        page+=1
print('done')
