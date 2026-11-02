import sys, json, os, datetime
sys.path.insert(0, sys.argv[1])
from polite import get
out=sys.argv[2]; os.makedirs(out,exist_ok=True)
roster={'52570683':'自由時報企業','03799802':'聯合報','70763439':'聯合線上','03798509':'中國時報文化事業','23530522':'時報資訊','97178489':'中天電視','18556774':'中國電視事業','24328949':'東森新媒體控股(ETtoday)','84305300':'聯利媒體(TVBS)','23740512':'三立電視','96975768':'民間全民電視','16080795':'民視文化事業','86121480':'東森電視事業','20516997':'中華電視','54340511':'國風傳媒(風傳媒)','42868209':'精鏡傳媒(鏡週刊)','83726795':'鏡電視'}
B='https://data.gcis.nat.gov.tw/od/data/api/'
res={}
for ban,name in roster.items():
    rec={}
    for key,api in [('basic','5F64D864-61CB-4D0D-8AD9-492047CC1EA6'),('directors','4E5F7653-1B91-4DDC-99D5-468530FAE396')]:
        st,b,_=get(B+api,{'$format':'json','$filter':f'Business_Accounting_NO eq {ban}','$skip':0,'$top':100},delay=3)
        try: rec[key]=json.loads(b.decode('utf-8'))
        except Exception: rec[key]={'error':st,'body':b[:200].decode('utf-8','replace')}
    res[ban]={'label':name,**rec}
    print(ban,name,len(rec.get('directors',[])) if isinstance(rec.get('directors'),list) else rec.get('directors'),flush=True)
json.dump(res,open(os.path.join(out,'gcis_basic_and_directors.json'),'w'),ensure_ascii=False,indent=1)
json.dump({'dataset':'經濟部商業發展署 公司登記 開放資料 API (GCIS)','urls':{'basic':B+'5F64D864-61CB-4D0D-8AD9-492047CC1EA6','directors':B+'4E5F7653-1B91-4DDC-99D5-468530FAE396','keyword_search':B+'6BBA2268-1367-4B42-9CCA-BC17499EBE8C'},'doc':'https://data.gcis.nat.gov.tw/od/rule','license':'政府資料開放授權條款第1版','downloaded':datetime.date.today().isoformat(),'n_companies':len(res),'note':'snapshot of current registry (董監事 and 持股 as of download date), not historical'},open(os.path.join(out,'SOURCES.json'),'w'),ensure_ascii=False,indent=1)
