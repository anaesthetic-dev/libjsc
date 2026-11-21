set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_BUILD_TYPE release)
# Release-specific flags follow vcpkg's default /O2.
set(VCPKG_C_FLAGS_RELEASE "/Gy /Gw /O1")
set(VCPKG_CXX_FLAGS_RELEASE "/Gy /Gw /O1")
