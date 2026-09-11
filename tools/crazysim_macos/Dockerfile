# CrazySim MuJoCo backend for Apple Silicon: no ROS, no Gazebo, no GPU.
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git python3 python3-pip ca-certificates \
      libosmesa6 libgl1 procps && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir mujoco numpy scipy jinja2 tomli cflib
RUN git config --global url."https://github.com/".insteadOf git@github.com:
WORKDIR /root
RUN git clone https://github.com/gtfactslab/CrazySim.git && cd CrazySim && \
    git submodule update --init --recursive crazyflie-firmware
# SITL build needs pkg-config and a bare `python`; installed after the clone
# so the slow submodule layers stay cached.
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /root/CrazySim/crazyflie-firmware/sitl_make/build
# Build only the firmware; `all` would also build the Gazebo plugin (needs Gazebo).
RUN cmake .. && make -j"$(nproc)" cf2
WORKDIR /root/CrazySim/crazyflie-firmware
ENV MUJOCO_GL=osmesa
CMD ["bash"]
