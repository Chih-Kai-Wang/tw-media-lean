import sys, json
sys.path.insert(0, sys.argv[1])
from polite import get
out=sys.argv[2]
kws=['自由時報','聯合報','聯合線上','經濟日報','中國時報','旺旺中時','中時','中天電視','中國電視','東森','聯利媒體','聯意製作','三立電視','民間全民電視','民視','中華電視','風傳媒','鏡傳媒','鏡電視','鏡週刊','鏡新聞','時報資訊','華視']
res={}
for k in kws:
    allr=[]
    for skip in (0,50,100):
        st,b,_=get('https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C',{'$format':'json','$filter':f'Company_Name like {k} and Company_Status eq 01','$skip':skip,'$top':50},delay=3)
        try: r=json.loads(b.decode('utf-8'))
        except Exception: print(k,'ERR',st,b[:100]); r=[]
        allr+=r
        if len(r)<50: break
    res[k]=allr
    print(k,len(allr),flush=True)
json.dump(res,open(out,'w'),ensure_ascii=False,indent=1)
