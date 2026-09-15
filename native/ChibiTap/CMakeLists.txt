cmake_minimum_required(VERSION 3.22)
project(ChibiTap VERSION 0.1.0 LANGUAGES C CXX)

include(FetchContent)

set(CHIBITAP_JUCE_DIR "" CACHE PATH "Optional local JUCE checkout")
if(CHIBITAP_JUCE_DIR)
    add_subdirectory("${CHIBITAP_JUCE_DIR}" JUCE)
else()
    FetchContent_Declare(
        JUCE
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG 9.0.2
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(JUCE)
endif()

juce_add_plugin(ChibiTap
    COMPANY_NAME "Akimbo"
    BUNDLE_ID "com.akimbo.chibitap"
    PLUGIN_MANUFACTURER_CODE Akmb
    PLUGIN_CODE CbTp
    FORMATS VST3
    PRODUCT_NAME "ChibiTap"
    DESCRIPTION "Transparent Chibi Audio capture tap"
    VST3_CATEGORIES Fx Analyzer
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD FALSE
)

juce_generate_juce_header(ChibiTap)

target_sources(ChibiTap PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginProcessor.h
    Source/CaptureWriter.cpp
    Source/CaptureWriter.h
)

target_compile_features(ChibiTap PRIVATE cxx_std_20)

target_compile_definitions(ChibiTap PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
)

target_link_libraries(ChibiTap PRIVATE
    juce::juce_audio_processors
    juce::juce_audio_utils
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)

juce_add_console_app(ChibiTapCoreTests PRODUCT_NAME "ChibiTapCoreTests")
juce_generate_juce_header(ChibiTapCoreTests)
target_sources(ChibiTapCoreTests PRIVATE Tests/ChibiTapCoreTests.cpp Source/PluginProcessor.cpp Source/PluginProcessor.h Source/CaptureWriter.cpp Source/CaptureWriter.h)
target_compile_features(ChibiTapCoreTests PRIVATE cxx_std_20)
target_compile_definitions(ChibiTapCoreTests PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(ChibiTapCoreTests PRIVATE juce::juce_audio_processors juce::juce_audio_utils juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)

juce_add_console_app(ChibiTapVst3SmokeTest PRODUCT_NAME "ChibiTapVst3SmokeTest")
juce_generate_juce_header(ChibiTapVst3SmokeTest)
target_sources(ChibiTapVst3SmokeTest PRIVATE Tests/ChibiTapVst3SmokeTest.cpp)
target_compile_features(ChibiTapVst3SmokeTest PRIVATE cxx_std_20)
target_compile_definitions(ChibiTapVst3SmokeTest PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_PLUGINHOST_VST3=1)
target_link_libraries(ChibiTapVst3SmokeTest PRIVATE juce::juce_audio_processors juce::juce_audio_utils juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
