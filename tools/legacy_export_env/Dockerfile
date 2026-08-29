FROM --platform=linux/amd64 python:3.8.10-slim
RUN pip install --no-cache-dir torch==1.10.2+cpu torchvision==0.11.3+cpu -f https://download.pytorch.org/whl/cpu/torch_stable.html
RUN pip install --no-cache-dir numpy==1.24.4 onnx==1.17.0 onnxruntime==1.16.3 onnx-simplifier==0.4.36 pillow==10.4.0 tqdm==4.67.1 pytorch-nemo==0.0.8 pycocotools==2.0.7
