import json, subprocess, glob, os, sys
TEXT = {"note","rationale","purpose"}
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k,v in o.items() if k not in TEXT}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o
def diff(a,b,path=""):
    out=[]
    if type(a)!=type(b): out.append((path,a,b)); return out
    if isinstance(a,dict):
        for k in set(a)|set(b):
            if k not in a or k not in b: out.append((path+"/"+k, a.get(k,"<absent>"), b.get(k,"<absent>")))
            else: out+=diff(a[k],b[k],path+"/"+k)
    elif isinstance(a,list):
        if len(a)!=len(b): out.append((path,"len %d"%len(a),"len %d"%len(b)))
        else:
            for i,(x,y) in enumerate(zip(a,b)): out+=diff(x,y,path+"[%d]"%i)
    else:
        if a!=b: out.append((path,a,b))
    return out
tot=0; textchanges=0
for f in sorted(glob.glob("tools/crazysim_macos/scene_defs/*.json")):
    head=json.loads(subprocess.check_output(["git","show","HEAD:"+f]))
    work=json.load(open(f))
    d=diff(strip(head),strip(work))
    dt=diff(head,work)
    textchanges+=len(dt)
    print(os.path.basename(f), "nontext_diffs=",len(d), "text_diffs=",len(dt), "keys:",[p.split('/')[-1] for p,_,_ in dt])
    for p,a,b in d: print("  NONTEXT", p, a, b)
    tot+=len(d)
print("TOTAL_NONTEXT", tot, "TOTAL_TEXT_FIELDS", textchanges)
