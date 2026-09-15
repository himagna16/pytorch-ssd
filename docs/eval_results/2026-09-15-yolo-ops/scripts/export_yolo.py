import sys, json, os
from pathlib import Path
SCR = Path(sys.argv[1]); os.chdir(SCR)
sys.path.insert(0, str(SCR/"ultra_target"))
from ultralytics import YOLO
import onnx, ultralytics

out = {"ultralytics_version": ultralytics.__version__}
for name in ["yolo11n.pt", "yolov8n.pt"]:
    try:
        m = YOLO(name)
        p = m.export(format="onnx", imgsz=128, opset=13, simplify=False, dynamic=False)
        g = onnx.load(str(p)).graph
        ops = {}
        for n in g.node:
            ops[n.op_type] = ops.get(n.op_type, 0) + 1
        out[name] = {"onnx": str(p), "n_nodes": len(g.node), "ops": dict(sorted(ops.items()))}
        print(name, "ok", len(g.node), "nodes")
    except Exception as e:
        out[name] = {"error": f"{type(e).__name__}: {e}"}
        print(name, "FAILED", e)
json.dump(out, open(SCR/"yolo_ops.json","w"), indent=1)
