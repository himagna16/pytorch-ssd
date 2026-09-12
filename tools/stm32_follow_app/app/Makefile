# Crazyflie out-of-tree app build (real hardware), same layout as the firmware's
# examples/app_stm_gap8_cpx. Point CRAZYFLIE_BASE at a crazyflie-firmware checkout:
#   make CRAZYFLIE_BASE=/path/to/crazyflie-firmware
#   make CRAZYFLIE_BASE=/path/to/crazyflie-firmware cload
CRAZYFLIE_BASE ?= $(error Set CRAZYFLIE_BASE to your crazyflie-firmware checkout)
OOT_CONFIG := $(PWD)/app-config
include $(CRAZYFLIE_BASE)/tools/make/oot.mk
