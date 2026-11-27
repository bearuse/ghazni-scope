idf_component_register(SRCS main.c ../../common/demo.c
                       INCLUDE_DIRS . ../../common
                       REQUIRES ghazni_scope esp_driver_gptimer)
target_compile_definitions(${COMPONENT_LIB} PRIVATE DEMO_STACK=3072)
