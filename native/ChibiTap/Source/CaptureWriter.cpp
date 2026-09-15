#include "CaptureWriter.h"

namespace
{
juce::String safeId(juce::String value)
{
    auto cleaned = value.retainCharacters("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_");
    return cleaned.isNotEmpty() ? cleaned : juce::String("tap");
}
}

CaptureWriter::CaptureWriter(juce::String id)
    : juce::Thread("ChibiTap Capture Manager"),
      instanceId(safeId(std::move(id)))
{
}

CaptureWriter::~CaptureWriter()
{
    shutdown();
}

void CaptureWriter::prepare(double sampleRate, int channelCount)
{
    currentSampleRate.store(sampleRate > 0.0 ? sampleRate : 48000.0, std::memory_order_release);
    currentChannels.store(juce::jlimit(1, 2, channelCount), std::memory_order_release);

    if (!diskThread.isThreadRunning())
        diskThread.startThread();

    if (!isThreadRunning())
        startThread(juce::Thread::Priority::normal);
}

void CaptureWriter::shutdown()
{
    requested.store(false, std::memory_order_release);
    signalThreadShouldExit();
    notify();
    stopThread(3000);

    closeCapture();

    if (diskThread.isThreadRunning())
        diskThread.stopThread(3000);

    recording.store(false, std::memory_order_release);
}

void CaptureWriter::setCaptureRequested(bool shouldCapture) noexcept
{
    const auto previous = requested.exchange(shouldCapture, std::memory_order_acq_rel);
    if (previous != shouldCapture)
        notify();
}

bool CaptureWriter::isCaptureRequested() const noexcept
{
    return requested.load(std::memory_order_acquire);
}

bool CaptureWriter::isRecording() const noexcept
{
    return recording.load(std::memory_order_acquire);
}

void CaptureWriter::setInstanceId(juce::String newInstanceId)
{
    const juce::ScopedLock lock(stateLock);
    instanceId = safeId(std::move(newInstanceId));
}

juce::String CaptureWriter::getInstanceId() const
{
    const juce::ScopedLock lock(stateLock);
    return instanceId;
}

juce::File CaptureWriter::getLastCaptureFile() const
{
    const juce::ScopedLock lock(stateLock);
    return lastCaptureFile;
}

void CaptureWriter::push(const juce::AudioBuffer<float>& buffer) noexcept
{
    if (!recording.load(std::memory_order_acquire) || buffer.getNumChannels() <= 0 || buffer.getNumSamples() <= 0)
        return;

    writerInUse.store(true, std::memory_order_seq_cst);
    auto* writer = activeWriter.load(std::memory_order_seq_cst);

    if (writer != nullptr)
    {
        const auto channels = currentChannels.load(std::memory_order_acquire);
        const auto* left = buffer.getReadPointer(0);
        const auto* right = buffer.getNumChannels() > 1 ? buffer.getReadPointer(1) : left;
        const float* pointers[2] { left, right };

        if (!writer->write(pointers, buffer.getNumSamples()))
            droppedBlocks.fetch_add(1, std::memory_order_relaxed);

        juce::ignoreUnused(channels);
    }

    writerInUse.store(false, std::memory_order_seq_cst);
}

void CaptureWriter::run()
{
    while (!threadShouldExit())
    {
        const auto wantsCapture = requested.load(std::memory_order_acquire);

        if (wantsCapture && activeWriter.load(std::memory_order_acquire) == nullptr)
            openCapture();
        else if (!wantsCapture && activeWriter.load(std::memory_order_acquire) != nullptr)
            closeCapture();

        wait(10);
    }

    closeCapture();
}

bool CaptureWriter::openCapture()
{
    if (sessionWriter != nullptr)
        return true;

    auto root = getCaptureRoot();
    if (root.createDirectory().failed())
        return false;

    const auto timestamp = juce::Time::getCurrentTime().formatted("%Y%m%d-%H%M%S");
    const auto captureId = juce::Uuid().toString().substring(0, 8);
    const auto id = getInstanceId();
    const auto configuredTapId = getTapId();
    const auto tapLabel = configuredTapId > 0 ? "tap-" + juce::String(configuredTapId) + "-" : juce::String();
    currentFile = root.getChildFile("chibitap-" + tapLabel + id + "-" + timestamp + "-" + captureId + ".wav");

    std::unique_ptr<juce::OutputStream> output = currentFile.createOutputStream();
    if (output == nullptr)
        return false;

    juce::WavAudioFormat wav;
    const auto options = juce::AudioFormatWriterOptions {}
        .withSampleRate(currentSampleRate.load(std::memory_order_acquire))
        .withNumChannels(currentChannels.load(std::memory_order_acquire))
        .withBitsPerSample(32)
        .withSampleFormat(juce::AudioFormatWriterOptions::SampleFormat::floatingPoint);

    auto writer = wav.createWriterFor(output, options);
    if (writer == nullptr)
        return false;

    sessionWriter = std::make_unique<juce::AudioFormatWriter::ThreadedWriter>(
        writer.release(), diskThread, threadedBufferSamples);
    sessionWriter->setFlushInterval(static_cast<int>(currentSampleRate.load(std::memory_order_acquire)));

    droppedBlocks.store(0, std::memory_order_release);
    activeWriter.store(sessionWriter.get(), std::memory_order_release);
    recording.store(true, std::memory_order_release);
    return true;
}

void CaptureWriter::closeCapture()
{
    recording.store(false, std::memory_order_release);
    activeWriter.exchange(nullptr, std::memory_order_acq_rel);

    for (int i = 0; i < 2000 && writerInUse.load(std::memory_order_seq_cst); ++i)
        juce::Thread::sleep(1);

    if (sessionWriter != nullptr)
    {
        sessionWriter.reset();
        const juce::ScopedLock lock(stateLock);
        lastCaptureFile = currentFile;
    }

    currentFile = {};
}

juce::File CaptureWriter::getCaptureRoot()
{
    return juce::File::getSpecialLocation(juce::File::userHomeDirectory)
        .getChildFile(".chibi-audio")
        .getChildFile("chibitap")
        .getChildFile("captures");
}
