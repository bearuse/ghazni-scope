# Ghazni Scope for ESP-IDF (docs/ESP-IDF.md): the FreeRTOS recorder, a port
# (esp_timer clock, UART0), and the trace macros put into ESP-IDF's FreeRTOS.
#   in your project's CMakeLists.txt, before project():
#     set(EXTRA_COMPONENT_DIRS <ghazni-scope>/targets/esp-idf)
#   sdkconfig: CONFIG_FREERTOS_USE_TRACE_FACILITY=y
set(scope ${CMAKE_CURRENT_LIST_DIR}/../../..)
idf_component_register(
    SRCS ${scope}/targets/freertos/scope_freertos.c scope_port_esp.c
    INCLUDE_DIRS ${scope}/targets/freertos ${scope}/include
    REQUIRES freertos esp_timer esp_driver_uart)
# your code: the API only (FreeRTOS gets the macros, below)
target_compile_definitions(${COMPONENT_LIB} PUBLIC SCOPE_API_ONLY)
# ESP-IDF makes some 20 mutexes and semaphores of its own before app_main, and
# a dozen tasks: room for them and yours
target_compile_definitions(${COMPONENT_LIB} PRIVATE SCOPE_ESP_COMPONENT SCOPE_MAX_OBJECTS=96 SCOPE_MAX_TASKS=48)

# ESP-IDF's FreeRTOSConfig.h cannot take our header at its end: FreeRTOS's own
# sources get it first (-include). FreeRTOS.h only defines the trace macros
# nobody defined, so ours stay.
idf_component_get_property(freertos_lib freertos COMPONENT_LIB)
target_compile_options(${freertos_lib} PRIVATE
    "SHELL:-include ${scope}/targets/freertos/scope_freertos.h" -DSCOPE_FORCE_INCLUDE)
