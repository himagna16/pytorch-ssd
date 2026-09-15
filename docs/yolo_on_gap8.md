# Can a YOLO model run on our AI-deck? No, and I exported one to find out where it stops.

Written 2026-09-15, after MinHyuk suggested YOLOv11 nano as a baseline (he had
good results with it on a real drone) and David warned that he had trouble
getting YOLO models to quantize and advised reviewing the architecture first.

David's warning is right. The obstacle is earlier and more concrete than
quantization difficulty.

An earlier version of this note argued the point from the published
architecture. That version named the wrong mechanism, so this one replaces it.
The numbers below come from exporting the models and running them through our
own parser's accept rules.

## What our code generator does with a node

DORY converts a quantized ONNX graph into C for the GAP8. Its NEMO frontend
constructs the parser with two lists, in `dory/Frontend_frameworks/NEMO/Parser.py`
lines 38 and 39. The first is what passes the door:

```python
layers_accepted = ['Conv','Pad','Mul','Add','Div','Constant','AveragePool',
                   'GlobalAveragePool','MaxPool','Cast','Clip','Floor','Flatten',
                   'Gemm','MatMul','Shape','Gather','Unsqueeze','Concat',
                   'Reshape','Sigmoid','LogSoftmax']
layers_neglected = ['Cast','Floor','Flatten','Shape','Gather','Unsqueeze',
                    'Concat','Reshape','Sigmoid','LogSoftmax']
```

Anything outside the first list stops the build at
`Parser_ONNX_to_DORY.py` line 67, which is an assertion rather than a fallback.

The second list is the part worth knowing about. A neglected node passes the
assertion and is then dropped from the graph, with its output index rewired to
the previous node. Nothing warns you. That behaviour is correct for the nodes it
was written for: a Cast or a Flatten really is a no-op once the graph is
quantized. It is not correct for a node that carries information.

## What actually happens to YOLO

I exported YOLOv11 nano and YOLOv8 nano at 128x128, opset 13, and classified
every node against those two lists. Script and raw output in
`docs/eval_results/2026-09-15-yolo-ops/`.

| | YOLOv11n | YOLOv8n | our champion |
|---|---|---|---|
| nodes | 355 | 263 | 94 |
| distinct op types | 18 | 17 | 11 |
| rejected at the assertion | 21 | 16 | 0 |
| accepted but dropped | 112 | 85 | 30 |
| accepted and built | 222 | 162 | 64 |

Both YOLO exports stop at node 10, a `Split`. The rejected types are `Split`,
`Transpose`, `Softmax`, `Resize`, `Slice`, and `Sub`. `Resize` is the top-down
path of the feature pyramid and `Split` is the C2f-style block, so these are not
incidental nodes you can trim.

The second row is the one that would bite later. Of YOLOv11n's nodes, 112 are
accepted and then silently dropped: all 78 `Sigmoid`, all 21 `Concat`, 11
`Reshape`, and a `Shape` and `Gather`. If someone worked around the `Split` and
`Resize` rejections by rewriting the model, the build would stop failing and
start succeeding on a network with its skip connections deleted and every SiLU
reduced to a bare multiply, because SiLU is `x * sigmoid(x)` and the sigmoid half
is on the neglect list. A wrong network that compiles is worse than one that does
not.

Our champion is the control for this measurement. It has zero rejections, and
its 30 dropped nodes are 28 `Cast`, one `Floor`, and one `Flatten`, which are
exactly the no-ops the neglect list was written for.

## What to do instead

1. Do not put YOLO on the chip. Use it off the drone, where it is genuinely
   useful: labelling the real camera frames we capture, which is manual work
   today, and giving an upper bound on what a modern detector sees in our frames.
2. Extend DORY with the missing operators. That is a compiler project, and
   tiling a concat and a resize inside 512 KB of L2 is the hard part of it.
3. Build a detector out of the operators we do have, borrowing YOLO's loss and
   label assignment. At that point it is our architecture, not a YOLO.

Option 1 costs nothing and solves a problem we already have.

## Limits of this check

The export used default settings at 128x128 with opset 13 and no
simplification. A different opset, `simplify=True`, or an
end-to-end-NMS export would change the node census, and `onnx-simplifier` would
fold some of the `Shape` and `Gather` nodes away. It would not remove `Split`,
`Resize`, or the SiLU pairs, which is where the argument rests.

This says nothing about whether YOLOv11n would fit in time or power on a 64 mW
chip. That question only matters if the operator problem is solved first.
