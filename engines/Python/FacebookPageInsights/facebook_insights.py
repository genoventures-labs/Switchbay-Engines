#!/usr/bin/env python3
"""Read-only Facebook Page analytics via Meta Graph API."""
from __future__ import annotations
import argparse,json,os,sys,urllib.error,urllib.parse,urllib.request
from datetime import datetime,timedelta,timezone
from typing import Any,Dict,List,Optional

VERSION="v25.0"
PAGE_FIELDS="id,name,username,link,fan_count,followers_count,category,verification_status"
PAGE_METRICS="page_impressions,page_impressions_unique,page_post_engagements,page_fans,page_views_total"
POST_FIELDS="id,message,created_time,permalink_url,shares,reactions.summary(true),comments.summary(true)"
POST_METRICS="post_impressions,post_impressions_unique,post_engaged_users,post_clicks"

def noneish(v:Any)->Optional[str]:
    if v is None:return None
    s=str(v).strip()
    return None if s.lower() in {"","none","null"} else s

def integer(v:Any,default:int,lo:int=1,hi:int=100)->int:
    try:return max(lo,min(int(float(noneish(v) or default)),hi))
    except (TypeError,ValueError):return default

def csv(v:Any,default:str)->str:
    return ",".join(x.strip() for x in (noneish(v) or default).split(",") if x.strip())

def date(v:Any,days:int)->str:
    return noneish(v) or (datetime.now(timezone.utc)-timedelta(days=days)).date().isoformat()

class GraphError(RuntimeError):
    def __init__(self,message:str,status:Optional[int]=None,details:Any=None):
        super().__init__(message);self.status=status;self.details=details

class Client:
    def __init__(self,token:str,version:str,timeout:int):
        if not token:raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN is required")
        self.token=token;self.version=version.lstrip("/");self.timeout=timeout
        self.base=f"https://graph.facebook.com/{self.version}"
    def _url(self,path:str,params:Dict[str,Any])->str:
        clean={k:v for k,v in params.items() if noneish(v) is not None};clean["access_token"]=self.token
        return f"{self.base}/{path.lstrip('/')}?{urllib.parse.urlencode(clean)}"
    def _read(self,url:str)->Dict[str,Any]:
        req=urllib.request.Request(url,headers={"User-Agent":"Switchbay-FacebookInsights/1.0"})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r:return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body=e.read().decode(errors="replace")
            try:
                detail=json.loads(body).get("error",{});msg=detail.get("message",str(detail))
            except json.JSONDecodeError:detail=body;msg=body or str(e)
            raise GraphError(msg,e.code,detail) from e
        except urllib.error.URLError as e:raise GraphError(f"Network error: {e.reason}") from e
    def get(self,path:str,**params:Any)->Dict[str,Any]:return self._read(self._url(path,params))
    def paged(self,path:str,limit:int,**params:Any)->List[Dict[str,Any]]:
        out=[];page=self.get(path,limit=min(limit,100),**params);pages=5
        while True:
            out.extend(page.get("data",[]));nxt=page.get("paging",{}).get("next");pages-=1
            if len(out)>=limit or not nxt or pages<=0:break
            page=self._read(nxt)
        return out[:limit]

def config(a:argparse.Namespace):
    token=noneish(getattr(a,"access_token",None)) or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN","")
    page=noneish(getattr(a,"page_id",None)) or os.getenv("FACEBOOK_PAGE_ID","")
    version=noneish(getattr(a,"api_version",None)) or os.getenv("FACEBOOK_GRAPH_API_VERSION",VERSION)
    if not page:raise ValueError("FACEBOOK_PAGE_ID is required")
    return Client(token,version,integer(getattr(a,"timeout",None),30,5,120)),page

def flatten(rows):
    return {"latest":{m.get("name","unknown"):(m.get("values") or [{}])[-1].get("value") for m in rows},"metrics":rows}

def status(a):
    c,p=config(a);return {"ok":True,"engine":"facebook-page-insights","api_version":c.version,"page":c.get(p,fields="id,name"),"read_only":True}

def page_profile(a):
    c,p=config(a);fields=csv(a.fields,PAGE_FIELDS);return {"ok":True,"page":c.get(p,fields=fields),"fields":fields.split(",")}

def page_insights(a):
    c,p=config(a);metrics=csv(a.metrics,PAGE_METRICS);since=date(a.since,28);until=noneish(a.until) or datetime.now(timezone.utc).date().isoformat();period=noneish(a.period) or "day"
    d=c.get(f"{p}/insights",metric=metrics,period=period,since=since,until=until)
    return {"ok":True,"page_id":p,"window":{"since":since,"until":until,"period":period},**flatten(d.get("data",[]))}

def list_posts(a):
    c,p=config(a);limit=integer(a.limit,25,1,100);fields=csv(a.fields,POST_FIELDS);since=date(a.since,28);until=noneish(a.until) or datetime.now(timezone.utc).date().isoformat();posts=c.paged(f"{p}/posts",limit,fields=fields,since=since,until=until);out=[]
    for post in posts:
        r=post.get("reactions",{}).get("summary",{}).get("total_count",0);m=post.get("comments",{}).get("summary",{}).get("total_count",0);s=post.get("shares",{}).get("count",0)
        out.append({**post,"summary":{"reactions":r,"comments":m,"shares":s,"visible_engagement":r+m+s}})
    return {"ok":True,"page_id":p,"count":len(out),"window":{"since":since,"until":until},"posts":out}

def post_insights(a):
    c,_=config(a);post=noneish(a.post_id)
    if not post:raise ValueError("post_id is required")
    return {"ok":True,"post_id":post,**flatten(c.get(f"{post}/insights",metric=csv(a.metrics,POST_METRICS)).get("data",[]))}

def compare_periods(a):
    c,p=config(a);metrics=csv(a.metrics,PAGE_METRICS);days=integer(a.days,28,1,365);end=datetime.now(timezone.utc).date();cur_start=end-timedelta(days=days);prev_end=cur_start;prev_start=prev_end-timedelta(days=days)
    def totals(start,stop):
        rows=c.get(f"{p}/insights",metric=metrics,period="day",since=start.isoformat(),until=stop.isoformat()).get("data",[]);out={}
        for m in rows:out[m.get("name","unknown")]=sum(float(v["value"]) for v in m.get("values",[]) if isinstance(v.get("value"),(int,float)))
        return out
    cur,prev=totals(cur_start,end),totals(prev_start,prev_end);comparison={}
    for n in sorted(set(cur)|set(prev)):
        x,y=cur.get(n,0),prev.get(n,0);comparison[n]={"current":x,"previous":y,"absolute_change":x-y,"percent_change":None if y==0 else round((x-y)/y*100,2)}
    return {"ok":True,"page_id":p,"days":days,"current_window":{"since":cur_start.isoformat(),"until":end.isoformat()},"previous_window":{"since":prev_start.isoformat(),"until":prev_end.isoformat()},"comparison":comparison,"note":"Non-numeric metric values are excluded from summed comparisons."}

def common(p):
    p.add_argument("--page_id",default=None);p.add_argument("--access_token",default=None);p.add_argument("--api_version",default=None);p.add_argument("--timeout",default="30")

def main():
    root=argparse.ArgumentParser();sub=root.add_subparsers(dest="tool",required=True)
    p=sub.add_parser("status");common(p);p.set_defaults(fn=status)
    p=sub.add_parser("page_profile");common(p);p.add_argument("--fields",default=None);p.set_defaults(fn=page_profile)
    p=sub.add_parser("page_insights");common(p);p.add_argument("--metrics",default=None);p.add_argument("--period",default="day");p.add_argument("--since",default=None);p.add_argument("--until",default=None);p.set_defaults(fn=page_insights)
    p=sub.add_parser("list_posts");common(p);p.add_argument("--fields",default=None);p.add_argument("--limit",default="25");p.add_argument("--since",default=None);p.add_argument("--until",default=None);p.set_defaults(fn=list_posts)
    p=sub.add_parser("post_insights");common(p);p.add_argument("--post_id",required=True);p.add_argument("--metrics",default=None);p.set_defaults(fn=post_insights)
    p=sub.add_parser("compare_periods");common(p);p.add_argument("--metrics",default=None);p.add_argument("--days",default="28");p.set_defaults(fn=compare_periods)
    a=root.parse_args()
    try:print(json.dumps(a.fn(a),indent=2,ensure_ascii=False))
    except (ValueError,GraphError) as e:
        payload={"ok":False,"error":str(e),"type":e.__class__.__name__}
        if isinstance(e,GraphError):payload.update({"status":e.status,"details":e.details})
        print(json.dumps(payload,indent=2,ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
if __name__=="__main__":main()
