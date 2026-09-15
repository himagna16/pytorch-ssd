import sys, json, onnx
sys.path.insert(0, "/Users/saimaruvada/Downloads/drone/dory")
ACC = ['Conv','Pad','Mul','Add','Div','Constant','AveragePool','GlobalAveragePool','MaxPool','Cast','Clip','Floor','Flatten','Gemm','MatMul','Shape','Gather','Unsqueeze','Concat','Reshape','Sigmoid','LogSoftmax']
NEG = ['Cast','Floor','Flatten','Shape','Gather','Unsqueeze','Concat','Reshape','Sigmoid','LogSoftmax']
for f in sys.argv[1:]:
    g = onnx.load(f).graph
    from collections import Counter
    c = Counter(n.op_type for n in g.node)
    rej = {k:v for k,v in c.items() if k not in ACC}
    neg = {k:v for k,v in c.items() if k in NEG}
    real= {k:v for k,v in c.items() if k in ACC and k not in NEG}
    first = next((n.op_type for n in g.node if n.op_type not in ACC), None)
    idx   = next((i for i,n in enumerate(g.node) if n.op_type not in ACC), None)
    print(f"\n=== {f} : {len(g.node)} nodes, {len(c)} distinct op types ===")
    print(f"  REJECTED by the assert ({sum(rej.values())} nodes): {rej}")
    print(f"  ACCEPTED but NEGLECTED, i.e. dropped ({sum(neg.values())} nodes): {neg}")
    print(f"  ACCEPTED and built ({sum(real.values())} nodes): {real}")
    print(f"  first node to hit the assert: #{idx} {first}")
