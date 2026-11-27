# The FreeRTOS demo (../common/demo.c) on ESP32 with Ghazni Scope.
#   idf.py set-target esp32 && idf.py build      (or: make -C .. esp32, in Docker)
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/../../targets/esp-idf)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(scope_demo)
