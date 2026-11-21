# libjsc — Prebuilt JavaScriptCore SDK

Prebuilt **JavaScriptCore** C-API shared library SDK for **Windows x64** and **Linux x64**, built from [oven-sh/WebKit](https://github.com/oven-sh/WebKit) via GitHub Actions.

## Features

- **Official C-API (`<JavaScriptCore/JavaScript.h>`):** Exports public C-API functions (`JSGlobalContextCreate`, `JSEvaluateScript`, `JSObjectGetTypedArrayBytesPtr`, etc.) and data such as `kJSClassDefinitionEmpty`. Windows data exports are marked `DATA` in the module definition file.
- **Windows x64 (`windows-x64-md`):**
  - `bin/JavaScriptCore.dll` + `lib/JavaScriptCore.lib` (import library)
  - Compiled with `clang-cl` and **Dynamic CRT (`/MD`)** (`MultiThreadedDLL`)
  - Single DLL for Windows 10/11. ICU and `mimalloc` are statically linked inside `JavaScriptCore.dll`.
  - The bundled ICU profile selects 37 languages in [icu/filters.json](icu/filters.json). Intl uses locale fallback for omitted languages. The profile retains Unicode normalization and properties, and omits dictionary-based word segmentation data and legacy converters.
- **Linux x64 (`linux-x64-ubuntu24.04`):**
  - `lib/libJavaScriptCore.so`
  - Compiled on Ubuntu 24.04 with `clang-21`, `-fPIC`, and `-ftls-model=global-dynamic`. The library retains its dynamic exports and ships stripped.
  - Uses system allocator and system ICU (`libicu74`)
- **64-bit JIT and WebAssembly:** Built with `PORT=JSCOnly`, `ENABLE_FTL_JIT=ON`, `ENABLE_WEBASSEMBLY=ON`, and `ENABLE_AOT=0`.
- **Size optimization:** Both platforms build Release with `NDEBUG`, per-function and per-data sections, and ThinLTO. The LLInt extractors compile as native objects for offlineasm.

## Quick Start (CMake)

Download the archive for your platform from **GitHub Releases** (or workflow artifacts) and extract it:

```cmake
cmake_minimum_required(VERSION 3.24)
project(my_app LANGUAGES CXX)

find_package(JavaScriptCore CONFIG REQUIRED)

add_executable(my_app main.cpp)
target_link_libraries(my_app PRIVATE JavaScriptCore::JavaScriptCore)
```

Configure CMake pointing `CMAKE_PREFIX_PATH` to the extracted SDK directory:

```sh
cmake -S . -B build -DCMAKE_PREFIX_PATH=/path/to/javascriptcore-sdk
cmake --build build --config Release
```

```cpp
#include <JavaScriptCore/JavaScript.h>
#include <cstdio>

int main() {
    JSGlobalContextRef ctx = JSGlobalContextCreate(nullptr);
    JSStringRef script = JSStringCreateWithUTF8CString("21 * 2");
    JSValueRef result = JSEvaluateScript(ctx, script, nullptr, nullptr, 1, nullptr);
    std::printf("%.0f\n", JSValueToNumber(ctx, result, nullptr));
    JSStringRelease(script);
    JSGlobalContextRelease(ctx);
    return 0;
}
```

> **Note (Windows):** Copy `bin/JavaScriptCore.dll` next to your executable (or add `bin/` to `PATH`). No external ICU DLLs are required.
>
> **Note (Linux):** Ensure `libicu74` is installed (`sudo apt-get install libicu74` on Ubuntu 24.04).

## Building

- **GitHub Actions:** Push to `main`, or run **Actions → Build JavaScriptCore SDK → Run workflow**. After both platforms build successfully, the workflow creates the next patch version (`v1.0.1` → `v1.0.2`), its tag, and the release automatically. No manual tag or release is needed. Existing stable tags for the same commit are reused; reruns upload assets with replacement instead of failing when a release already exists. Manual `vMAJOR.MINOR.PATCH` tags remain supported.
- **Pinned Revision:** `webkit-ref.txt` pins the exact `oven-sh/WebKit` commit used across both platforms.
- **Windows build:** In an x64 MSVC developer shell with LLVM 22.1.8, Ninja, Python, and `VCPKG_INSTALLATION_ROOT` set, generate the ICU overlay and install it into the workspace. The overlay follows the vcpkg port's ICU version and builds filtered data from that release's source data archive.
  ```powershell
  git -c core.autocrlf=false clone https://github.com/oven-sh/WebKit.git webkit
  git -C webkit checkout (Get-Content webkit-ref.txt)
  python scripts/prepare_icu_overlay.py
  & "$env:VCPKG_INSTALLATION_ROOT/vcpkg.exe" install icu:x64-windows --classic --host-triplet=x64-windows --x-install-root="$PWD/vcpkg_installed" --overlay-triplets="$PWD/triplets" --overlay-ports="$PWD/build/overlay-ports"
  $env:ICU_ROOT = "$PWD/vcpkg_installed/x64-windows"
  python scripts/build.py --source webkit --platform windows-x64-md --jobs 2
  ```
- **Linux build:** Use Clang, lld, and LLVM binutils version 21, the system ICU development headers, and the build dependencies listed in the GitHub Actions workflow.
  ```sh
  git -c core.autocrlf=false clone https://github.com/oven-sh/WebKit.git webkit
  git -C webkit checkout "$(cat webkit-ref.txt)"
  python scripts/build.py --source webkit --platform linux-x64-ubuntu24.04 --jobs 2
  ```

Each build checks the linked library before packaging. Windows caps the embedded ICU package at 12 MB. Linux requires the full ELF symbol table to be stripped. `build-info.json` and the GitHub Actions job summary include the resulting sizes. CI also runs the packaged SDK example, which checks hot JavaScript execution, Wasm, Intl, Unicode, and the typed-array C API.

## License

JavaScriptCore and WTF are distributed under the terms of the LGPL v2+ and BSD licenses from the [WebKit project](https://github.com/oven-sh/WebKit). License notices are bundled in the `licenses/` directory of each SDK archive.
