import time, subprocess, urllib.parse, collections, os, tempfile
UA='twmedia-research/0.1 (+https://github.com/f0909172434)'
_last=collections.defaultdict(float)
def _wait(host,delay):
    w=_last[host]+delay-time.time()
    if w>0: time.sleep(w)
    _last[host]=time.time()
def get(url, params=None, delay=2.5, timeout=120, retries=2):
    """returns (status, bytes, content_type) via curl"""
    if params: url=url+('&' if '?' in url else '?')+urllib.parse.urlencode(params)
    host=urllib.parse.urlparse(url).netloc
    for a in range(retries+1):
        _wait(host,delay)
        fd,tmp=tempfile.mkstemp(); os.close(fd)
        p=subprocess.run(['curl','-sL','-m',str(timeout),'-A',UA,'-o',tmp,'-w','%{http_code}\t%{content_type}',url],capture_output=True,text=True)
        body=open(tmp,'rb').read(); os.unlink(tmp)
        try: code,ct=p.stdout.split('\t',1); code=int(code)
        except Exception: code,ct=-1,''
        if code==200: return code,body,ct
        if code in (403,429,404): return code,body,ct
        time.sleep(5*(a+1))
    return code,body,ct
def download(url, path, delay=2.5, timeout=600):
    host=urllib.parse.urlparse(url).netloc
    _wait(host,delay)
    p=subprocess.run(['curl','-sL','-m',str(timeout),'-A',UA,'-o',path,'-w','%{http_code}\t%{content_type}\t%{size_download}',url],capture_output=True,text=True)
    return p.stdout
def head(url, delay=2.5):
    host=urllib.parse.urlparse(url).netloc
    _wait(host,delay)
    p=subprocess.run(['curl','-sIL','-m','60','-A',UA,url],capture_output=True,text=True)
    return p.stdout
