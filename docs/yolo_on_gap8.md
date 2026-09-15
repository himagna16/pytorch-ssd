# Can a YOLO model run on our AI-deck? Not through this pipeline.

Written 2026-09-15, after MinHyuk suggested YOLOv11 nano as a baseline (he had
good results with it on a real drone) and David warned that he had trouble
getting YOLO models to quantize and advised reviewing the architecture first.

David's warning is right, and the reason is harder than "difficult to quantize".
Our deployment path cannot represent the architecture at all.

## What our code generator accepts

DORY converts a quantized ONNX graph into C for the GAP8. Its parser declares
the complete set of node kinds it understands, in
`dory/Parsers/Parser_ONNX_to_DORY.py` line 44:

```python
self.layers_supported_by_DORY_Frontend_IR = [
    "Convolution", "Pooling", "FullyConnected",
    "Addition", "QAddition", "Relu", "BNRelu", "Requant",
]
```

Anything else stops the build. Line 67 is an assertion, not a fallback:

```python
assert (node_iterating.op_type in self.layers_accepted), f"{node_iterating.op_type} not supported by DORY"
```

The NEMO frontend's `rules.json` rewrites only eight patterns, all of them
combinations of the same operators: Relu, BNRelu, PadConvolution, PadPooling,
QAdd.

So the pipeline supports convolutions, pooling, fully connected layers,
residual adds, and ReLU. That is the whole vocabulary.

## What a YOLOv11-class architecture needs

From the published architecture rather than from an export we ran ourselves (see
the caveat below), a YOLOv11 nano graph relies on at least:

| Operator | Used for | In our set? |
|---|---|---|
| Concat | the neck, every feature-pyramid join | no |
| Split | the C2f / C3k2 blocks | no |
| Resize or Upsample | the top-down pyramid path | no |
| SiLU (Sigmoid times input) | the default activation throughout | no |
| Sigmoid | the detection head | no |
| Elementwise Mul | part of SiLU and the attention blocks | no |

Concat and Upsample are not exotic operations. They are how a feature pyramid is
built, and a YOLO without its neck is not a YOLO. Replacing SiLU with ReLU is
routine and would need retraining; removing the concatenations is a different
architecture.

## What this means

Trying this through our pipeline would fail at the DORY assert, not after a long
quantization struggle. The realistic options, in order of cost:

1. Do not put YOLO on the chip. Use it off the drone, where it is genuinely
   useful: labelling the real camera frames we capture, which is otherwise manual
   work, and giving an upper bound on what a modern detector sees in our frames.
2. Extend DORY with the missing operators. That is a compiler project, not a
   model project, and the concat and resize tiling on 512 KB of L2 is the hard
   part.
3. Design a YOLO-shaped detector out of the eight operators we do have. At that
   point it is our own architecture that borrows YOLO's loss and label
   assignment, not a YOLO.

Option 1 is worth doing regardless of the rest. It costs nothing and it solves a
real problem we have.

## What this note does not establish

We did not export a YOLOv11 nano to ONNX and enumerate its actual nodes against
the parser. The operator list above comes from the published architecture, so
treat it as the reason to check rather than as the check itself. If someone wants
to close this properly it is about twenty minutes: export the model to ONNX, list
the distinct `op_type` values, and compare against line 44. That is exactly the
architecture review David asked for, and it would turn this note into a
measurement.

We also have not measured what YOLOv11 nano would cost in time or power on a
64 mW chip, which is a separate question and only matters if the operator
problem is solved first.
