# PlatformIO pre-script: compile the shared LVGL UI (../ui/*.cpp) into the firmware.
# The UI is owned by the UI/simulator batch and shared with sim/; the firmware only links it.
# Whatever .cpp files ../ui holds (the skeleton stub today, the real UI later) are built unchanged.
import os

Import("env")  # noqa: F821  (injected by PlatformIO/SCons)

ui_dir = os.path.normpath(os.path.join(env.subst("$PROJECT_DIR"), "..", "ui"))  # noqa: F821
if not os.path.isdir(ui_dir):
    raise SystemExit(f"shared UI directory not found: {ui_dir}")

env.BuildSources(os.path.join("$BUILD_DIR", "shared_ui"), ui_dir, src_filter="+<*.cpp> +<*.c>")  # noqa: F821
