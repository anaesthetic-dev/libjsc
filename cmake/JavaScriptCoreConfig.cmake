get_filename_component(_jsc_root "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
if(NOT TARGET JavaScriptCore::JavaScriptCore)
    add_library(JavaScriptCore::JavaScriptCore SHARED IMPORTED)
    set_target_properties(JavaScriptCore::JavaScriptCore PROPERTIES
        INTERFACE_INCLUDE_DIRECTORIES "${_jsc_root}/include")
    if(WIN32)
        set_target_properties(JavaScriptCore::JavaScriptCore PROPERTIES
            IMPORTED_IMPLIB "${_jsc_root}/lib/JavaScriptCore.lib"
            IMPORTED_LOCATION "${_jsc_root}/bin/JavaScriptCore.dll")
    else()
        set_target_properties(JavaScriptCore::JavaScriptCore PROPERTIES
            IMPORTED_LOCATION "${_jsc_root}/lib/libJavaScriptCore.so")
    endif()
endif()
unset(_jsc_root)
