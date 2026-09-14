import json, subprocess, glob, os
TEXT={"note","rationale","purpose"}
def walk(o,path=""):
    if isinstance(o,dict):
        for k,v in o.items():
            if k in TEXT and isinstance(v,str): yield path+"/"+k, v
            else: yield from walk(v,path+"/"+k)
    elif isinstance(o,list):
        for i,x in enumerate(o): yield from walk(x,path+"[%d]"%i)
for f in sorted(glob.glob("tools/crazysim_macos/scene_defs/*.json")):
    head=dict(walk(json.loads(subprocess.check_output(["git","show","HEAD:"+f]))))
    work=dict(walk(json.load(open(f))))
    for p,old in head.items():
        new=work.get(p)
        if new==old: continue
        kept = new.startswith(old)
        print(os.path.basename(f), p, "OLD_KEPT_AS_PREFIX" if kept else ("OLD_CONTAINED" if old in new else "OLD_LOST"), "old_len=%d new_len=%d"%(len(old),len(new)))
