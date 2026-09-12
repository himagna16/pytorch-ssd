# Adds the follow app to CrazySim's SITL cf2 target. Included at the end of
# crazyflie-firmware/sitl_make/CMakeLists.txt by sim/Dockerfile.sitl.
# The SITL CMake build has no Kbuild/Kconfig, so the app layer (app_handler.c,
# which starts appMain in its own task) and the CONFIG_APP_* values are added here.
get_filename_component(FOLLOW_APP_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
target_sources(cf2 PRIVATE
  ${CF2_SITL_SRCS_DIR}/modules/src/app_handler.c
  ${FOLLOW_APP_ROOT}/app/src/follow_app.c
  ${FOLLOW_APP_ROOT}/app/src/follow_controller_unit.c)
target_compile_definitions(cf2 PUBLIC CONFIG_APP_ENABLE=1 CONFIG_APP_PRIORITY=1 CONFIG_APP_STACKSIZE=2048)
