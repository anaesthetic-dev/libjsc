# libjsc — Prebuilt JavaScriptCore SDK

Prebuilt **JavaScriptCore** C-API shared library SDK for **Windows x64** and **Linux x64**, built from [oven-sh/WebKit](https://github.com/oven-sh/WebKit) via GitHub Actions.

## Features

- **Official C-API (`<JavaScriptCore/JavaScript.h>`):** Exports the 117 public C-API symbols (`JSGlobalContextCreate`, `JSEvaluateScript`, `JSObjectGetTypedArrayBytesPtr`, etc.).
- **Windows x64 (`windows-x64-md`):**
  - `bin/JavaScriptCore.dll` + `lib/JavaScriptCore.lib` (import library)
  - Compiled with `clang-cl` and **Dynamic CRT (`/MD`)** (`MultiThreadedDLL`)
  - Includes ICU runtime DLLs in `bin/` and static `mimalloc` linked internally
- **Linux x64 (`linux-x64-ubuntu24.04`):**
  - `lib/libJavaScriptCore.so`
  - Compiled on Ubuntu 24.04 with `clang-21`, `-fPIC`, and `-ftls-model=global-dynamic`
  - Uses system allocator and system ICU (`libicu74`)
- **64-bit JIT Enabled:** Built with `PORT=JSCOnly`, `ENABLE_FTL_JIT=ON`, and `ENABLE_AOT=0`.

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

> **Note (Windows):** Copy the DLLs from `bin/` (`JavaScriptCore.dll` and `icu*.dll`) next to your executable or add `bin/` to `PATH`.
>
> **Note (Linux):** Ensure `libicu74` is installed (`sudo apt-get install libicu74` on Ubuntu 24.04).

## Building

- **GitHub Actions:** Run **Actions → Build JavaScriptCore SDK → Run workflow**, or push a `v*` tag to automatically build and publish a GitHub Release.
- **Pinned Revision:** `webkit-ref.txt` pins the exact `oven-sh/WebKit` commit used across both platforms.
- **Local Build:**
  ```sh
  git -c core.autocrlf=false clone https://github.com/oven-sh/WebKit.git webkit
  python scripts/build.py --source webkit --platform windows-x64-md --jobs 2
  # or on Linux:
  python scripts/build.py --source webkit --platform linux-x64-ubuntu24.04 --jobs 2
  ```

## License

JavaScriptCore and WTF are distributed under the terms of the LGPL v2+ and BSD licenses from the [WebKit project](https://github.com/oven-sh/WebKit). License notices are bundled in the `licenses/` directory of each SDK archive.