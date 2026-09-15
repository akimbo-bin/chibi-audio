#pragma once

#include <JuceHeader.h>
#include <atomic>
#include <memory>

class CaptureWriter final : private juce::Thread
{
public:
    explicit CaptureWriter(juce::String instanceId);
    ~CaptureWriter() override;

    void prepare(double sampleRate, int channelCount);
    void shutdown();

    void setCaptureRequested(bool shouldCapture) noexcept;
    bool isCaptureRequested() const noexcept;
    bool isRecording() const noexcept;

    void push(const juce::AudioBuffer<float>& buffer) noexcept;

    void setInstanceId(juce::String newInstanceId);
    juce::String getInstanceId() const;
    juce::File getLastCaptureFile() const;
    uint64_t getDroppedBlocks() const noexcept { return droppedBlocks.load(std::memory_order_acquire); }

private:
    static constexpr int threadedBufferSamples = 262144;

    void run() override;
    bool openCapture();
    void closeCapture();
    static juce::File getCaptureRoot();

    mutable juce::CriticalSection stateLock;
    juce::String instanceId;

    std::atomic<bool> requested { false };
    std::atomic<bool> recording { false };
    std::atomic<double> currentSampleRate { 48000.0 };
    std::atomic<int> currentChannels { 2 };
    std::atomic<uint64_t> droppedBlocks { 0 };

    juce::TimeSliceThread diskThread { "ChibiTap Disk Writer" };
    std::unique_ptr<juce::AudioFormatWriter::ThreadedWriter> sessionWriter;
    std::atomic<juce::AudioFormatWriter::ThreadedWriter*> activeWriter { nullptr };
    std::atomic<bool> writerInUse { false };

    juce::File currentFile;
    juce::File lastCaptureFile;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(CaptureWriter)
};
