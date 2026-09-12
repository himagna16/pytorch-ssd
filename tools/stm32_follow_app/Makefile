# Host build + tests for the portable STM32 follow controller.
#   make            unit tests + shared libraries for the safety simulator
#   make sim-quick  named timelines (40 runs each) + one small Monte Carlo
#   make sim-full   what tests/results/ was produced with (slow, ~10-20 min)
CC      ?= cc
CFLAGS  ?= -std=c99 -Wall -Wextra -Werror -pedantic -Wshadow -Wdouble-promotion -O2
PY      ?= python3
B       := tests/build

all: unit app-test libs

$(B):
	mkdir -p $(B)

$(B)/test_follow_controller: tests/test_follow_controller.c follow_controller.c follow_controller.h tests/vendor/follow_packet.h | $(B)
	$(CC) $(CFLAGS) -Itests/vendor -o $@ tests/test_follow_controller.c follow_controller.c -lm

$(B)/libfollowctl.so: follow_controller.c follow_controller.h tests/ctl_shim.c | $(B)
	$(CC) $(CFLAGS) -fPIC -shared -o $@ follow_controller.c tests/ctl_shim.c

$(B)/libfp.so: tests/fp_shim.c tests/vendor/follow_packet.h tests/vendor/app_config.h | $(B)
	$(CC) $(CFLAGS) -fPIC -shared -Itests/vendor -o $@ tests/fp_shim.c

unit: $(B)/test_follow_controller
	./$(B)/test_follow_controller

# the Crazyflie app's state machine on the host, against stub firmware headers
$(B)/app_host_test: tests/app_host_test.c app/src/follow_app.c follow_controller.c follow_controller.h tests/app_stubs/firmware_stubs.h | $(B)
	$(CC) $(CFLAGS) -Wno-unused-function -DCONFIG_PLATFORM_SITL=1 -Itests/app_stubs -o $@ tests/app_host_test.c follow_controller.c

app-test: $(B)/app_host_test
	./$(B)/app_host_test

libs: $(B)/libfollowctl.so $(B)/libfp.so

sim-quick: libs
	cd tests && $(PY) safety_sim_review6_c.py checks && $(PY) safety_sim_review6_c.py timelines 40 && $(PY) safety_sim_review6_c.py mc0 40 100

sim-full: libs
	cd tests && ./run_sim_all.sh

clean:
	rm -rf $(B)

.PHONY: all unit app-test libs sim-quick sim-full clean
