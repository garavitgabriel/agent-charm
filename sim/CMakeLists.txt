# Dex Charm macOS simulator: the shared ui/ on LVGL 8.3.11 in an SDL2 window, plus headless
# screenshots and the ctest suite.
#   cmake -S sim -B build/sim && cmake --build build/sim && ctest --test-dir build/sim
cmake_minimum_required(VERSION 3.20)
project(charm_sim C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

get_filename_component(CHARM_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
set(CHARM_UI_DIR "${CHARM_ROOT}/ui")
set(CHARM_EXAMPLES_DIR "${CHARM_ROOT}/contract/examples")

# ---- pinned dependencies (same versions the firmware pins) ----
include(FetchContent)
# SOURCE_SUBDIR points at a directory that does not exist, so FetchContent only downloads: we
# build LVGL ourselves against ui/lv_conf.h, and ArduinoJson is header-only.
FetchContent_Declare(lvgl
  URL https://github.com/lvgl/lvgl/archive/refs/tags/v8.3.11.tar.gz
  URL_HASH SHA256=83b7325a4b78cbb19a39f3ac75346c8086926d7faeab5ff2d825c20da0bbdb46
  SOURCE_SUBDIR _download_only
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_Declare(arduinojson
  URL https://github.com/bblanchon/ArduinoJson/archive/refs/tags/v7.4.2.tar.gz
  URL_HASH SHA256=681f703dd237f5b7f1dc1d7009a9cf246e88676b349572e73eae9154e8994a55
  SOURCE_SUBDIR _download_only
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_MakeAvailable(lvgl arduinojson)

# The live sim's WebSocket client (--connect). BSD-3-Clause; built plain ws:// only (no TLS yet,
# like the v0 server) and without zlib (permessage-deflate stays off, as on the device).
set(USE_TLS OFF CACHE BOOL "" FORCE)
set(USE_ZLIB OFF CACHE BOOL "" FORCE)
set(IXWEBSOCKET_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_Declare(ixwebsocket
  URL https://github.com/machinezone/IXWebSocket/archive/refs/tags/v11.4.6.tar.gz
  URL_HASH SHA256=c024334f8e45980836c67008979a884d6dcc5ef067dd2eb1fa7241f4c17ddc32
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_MakeAvailable(ixwebsocket)
if(TARGET ixwebsocket)
  target_compile_options(ixwebsocket PRIVATE -w)
endif()

file(GLOB_RECURSE LVGL_SOURCES CONFIGURE_DEPENDS "${lvgl_SOURCE_DIR}/src/*.c")
add_library(lvgl STATIC ${LVGL_SOURCES})
target_include_directories(lvgl SYSTEM PUBLIC "${lvgl_SOURCE_DIR}" "${CHARM_UI_DIR}")
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)
target_compile_options(lvgl PRIVATE -w)

add_library(arduinojson INTERFACE)
target_include_directories(arduinojson SYSTEM INTERFACE "${arduinojson_SOURCE_DIR}/src")

# ---- the shared UI, compiled exactly as firmware/ compiles it (../ui/*.cpp) ----
file(GLOB CHARM_UI_SOURCES CONFIGURE_DEPENDS "${CHARM_UI_DIR}/*.cpp")
add_library(charm_ui STATIC ${CHARM_UI_SOURCES})
target_include_directories(charm_ui PUBLIC "${CHARM_UI_DIR}")
target_link_libraries(charm_ui PUBLIC lvgl arduinojson)
target_compile_options(charm_ui PRIVATE -Wall -Wextra -Werror)

# ---- firmware's pure protocol logic (frames, backoff, keepalive, talk limit), compiled unchanged
# from firmware/lib/charm_core so the live sim behaves like the device ----
set(CHARM_CORE_DIR "${CHARM_ROOT}/firmware/lib/charm_core/src")
add_library(charm_core STATIC "${CHARM_CORE_DIR}/frames.cpp")
target_include_directories(charm_core PUBLIC "${CHARM_CORE_DIR}")
target_link_libraries(charm_core PUBLIC arduinojson)

# ---- sim support: framebuffer display + PNG writer (no SDL) ----
find_package(ZLIB REQUIRED)
add_library(sim_core STATIC src/sim_display.cpp src/png_write.cpp)
target_include_directories(sim_core PUBLIC src)
target_link_libraries(sim_core PUBLIC charm_ui ZLIB::ZLIB)
target_compile_options(sim_core PRIVATE -Wall -Wextra)

# ---- the simulator ----
find_package(SDL2 REQUIRED CONFIG)
add_executable(charm-sim src/main.cpp src/sim_host.cpp src/sim_script.cpp src/sim_live.cpp src/sim_audio.cpp)
target_link_libraries(charm-sim PRIVATE sim_core charm_core ixwebsocket SDL2::SDL2)
target_compile_definitions(charm-sim PRIVATE CHARM_EXAMPLES_DIR="${CHARM_EXAMPLES_DIR}")
target_compile_options(charm-sim PRIVATE -Wall -Wextra)

# ---- tests ----
enable_testing()
add_executable(charm-tests tests/test_ui.cpp tests/test_host.cpp)
target_link_libraries(charm-tests PRIVATE sim_core)
target_compile_definitions(charm-tests PRIVATE CHARM_EXAMPLES_DIR="${CHARM_EXAMPLES_DIR}")
target_compile_options(charm-tests PRIVATE -Wall -Wextra)
add_test(NAME ui_contract COMMAND charm-tests)
add_test(NAME sim_shots COMMAND charm-sim --shots "${CMAKE_CURRENT_BINARY_DIR}/test-shots")
add_test(NAME sim_replay COMMAND charm-sim --headless --replay "${CMAKE_CURRENT_SOURCE_DIR}/replays/talk.jsonl")

# The live sim against the real charm server (in-process, with the server's own fake STT/Dex/TTS
# imported from server/tests): one talk round trip from a WAV, headless. No network, no Hermes.
find_program(UV_EXECUTABLE uv)
if(UV_EXECUTABLE)
  add_test(NAME sim_live_integration
    COMMAND "${UV_EXECUTABLE}" run --project "${CHARM_ROOT}/server"
            python "${CHARM_ROOT}/scripts/integration_test.py" --sim $<TARGET_FILE:charm-sim>)
  set_tests_properties(sim_live_integration PROPERTIES TIMEOUT 180)
else()
  message(WARNING "uv not found: the sim_live_integration test is not registered (brew install uv)")
endif()
