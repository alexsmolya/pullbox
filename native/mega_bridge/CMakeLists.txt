cmake_minimum_required(VERSION 3.20)

project(pullbox_mega_bridge LANGUAGES CXX)

if(NOT MEGA_SDK_SOURCE_DIR)
    message(FATAL_ERROR "MEGA_SDK_SOURCE_DIR is required")
endif()

set(ENABLE_SYNC OFF CACHE BOOL "" FORCE)
set(ENABLE_CHAT OFF CACHE BOOL "" FORCE)
set(ENABLE_MEDIA_FILE_METADATA OFF CACHE BOOL "" FORCE)
set(ENABLE_DRIVE_NOTIFICATIONS OFF CACHE BOOL "" FORCE)
set(ENABLE_JAVA_BINDINGS OFF CACHE BOOL "" FORCE)
set(ENABLE_QT_BINDINGS OFF CACHE BOOL "" FORCE)
set(ENABLE_SDKLIB_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ENABLE_SDKLIB_TESTS OFF CACHE BOOL "" FORCE)
set(ENABLE_SDKLIB_WERROR OFF CACHE BOOL "" FORCE)
set(USE_FREEIMAGE OFF CACHE BOOL "" FORCE)
set(USE_FFMPEG OFF CACHE BOOL "" FORCE)
set(USE_LIBUV OFF CACHE BOOL "" FORCE)
set(USE_PDFIUM OFF CACHE BOOL "" FORCE)
set(USE_READLINE OFF CACHE BOOL "" FORCE)
set(USE_OPENSSL ON CACHE BOOL "" FORCE)

list(APPEND CMAKE_MODULE_PATH "${MEGA_SDK_SOURCE_DIR}/cmake/modules/packages")
add_subdirectory("${MEGA_SDK_SOURCE_DIR}" mega-sdk EXCLUDE_FROM_ALL)

add_executable(pullbox-mega-bridge main.cpp)
target_compile_features(pullbox-mega-bridge PRIVATE cxx_std_17)
target_compile_options(
    pullbox-mega-bridge
    PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
)
target_link_libraries(pullbox-mega-bridge PRIVATE MEGA::SDKlib)

install(TARGETS pullbox-mega-bridge RUNTIME DESTINATION bin)
