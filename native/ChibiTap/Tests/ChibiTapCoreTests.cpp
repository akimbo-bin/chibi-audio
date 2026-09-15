#include "../Source/PluginProcessor.h"

#include <cmath>
#include <iostream>

namespace
{
class TestPlayHead final : public juce::AudioPlayHead
{
public:
    Optional<PositionInfo> getPosition() const override
    {
        PositionInfo info;
        info.setIsPlaying(playing);
        info.setTimeInSamples(samplePosition);
        return info;
    }

    void setPlaying(bool value) noexcept { playing = value; }
    void advance(int samples) noexcept { samplePosition += samples; }

private:
    bool playing = false;
    int64_t samplePosition = 0;
};

bool buffersEqual(const juce::AudioBuffer<float>& a, const juce::AudioBuffer<float>& b)
{
    if (a.getNumChannels() != b.getNumChannels() || a.getNumSamples() != b.getNumSamples())
        return false;

    for (int channel = 0; channel < a.getNumChannels(); ++channel)
        for (int sample = 0; sample < a.getNumSamples(); ++sample)
            if (a.getSample(channel, sample) != b.getSample(channel, sample))
                return false;

    return true;
}

juce::File captureRoot()
{
    return juce::File::getSpecialLocation(juce::File::userHomeDirectory)
        .getChildFile(".chibi-audio")
        .getChildFile("chibitap")
        .getChildFile("captures");
}

juce::AudioProcessorParameter* findParameter(juce::AudioProcessor& processor, const juce::String& name)
{
    for (auto* parameter : processor.getParameters())
        if (parameter != nullptr && parameter->getName(128).equalsIgnoreCase(name))
            return parameter;

    return nullptr;
}
}

int main()
{
    juce::ScopedJuceInitialiser_GUI juceInitialiser;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 256;
    constexpr int playingBlocks = 64;
    constexpr int tapIdValue = 42;

    ChibiTapAudioProcessor processor;
    processor.setPlayConfigDetails(2, 2, sampleRate, blockSize);
    processor.prepareToPlay(sampleRate, blockSize);

    TestPlayHead playHead;
    processor.setPlayHead(&playHead);

    juce::AudioBuffer<float> buffer(2, blockSize);
    for (int i = 0; i < blockSize; ++i)
    {
        const auto value = static_cast<float>(0.25 * std::sin(2.0 * juce::MathConstants<double>::pi * 440.0 * i / sampleRate));
        buffer.setSample(0, i, value);
        buffer.setSample(1, i, -value);
    }

    juce::AudioBuffer<float> original;
    original.makeCopyOf(buffer);

    juce::MidiBuffer midi;
    processor.processBlock(buffer, midi);

    if (!buffersEqual(buffer, original))
    {
        std::cerr << "FAIL: ChibiTap modified the audio buffer\n";
        return 1;
    }

    auto* capture = findParameter(processor, "Capture");
    auto* tapId = dynamic_cast<juce::RangedAudioParameter*>(findParameter(processor, "Tap ID"));
    if (capture == nullptr || tapId == nullptr)
    {
        std::cerr << "FAIL: Capture or Tap ID parameter missing\n";
        return 2;
    }

    tapId->setValueNotifyingHost(tapId->convertTo0to1(static_cast<float>(tapIdValue)));
    const auto startedAt = juce::Time::getCurrentTime();
    capture->setValueNotifyingHost(1.0f);

    for (int block = 0; block < 8; ++block)
    {
        processor.processBlock(buffer, midi);
        playHead.advance(blockSize);
    }
    juce::Thread::sleep(40);

    playHead.setPlaying(true);
    for (int block = 0; block < playingBlocks; ++block)
    {
        for (int i = 0; i < blockSize; ++i)
        {
            const auto phase = block * blockSize + i;
            const auto value = static_cast<float>(0.5 * std::sin(2.0 * juce::MathConstants<double>::pi * 110.0 * phase / sampleRate));
            buffer.setSample(0, i, value);
            buffer.setSample(1, i, value * 0.5f);
        }
        processor.processBlock(buffer, midi);
        playHead.advance(blockSize);
    }

    playHead.setPlaying(false);
    for (int block = 0; block < 8; ++block)
    {
        buffer.clear();
        processor.processBlock(buffer, midi);
        playHead.advance(blockSize);
    }

    capture->setValueNotifyingHost(0.0f);
    processor.processBlock(buffer, midi);
    juce::Thread::sleep(120);
    processor.releaseResources();
    processor.setPlayHead(nullptr);

    juce::Array<juce::File> files;
    captureRoot().findChildFiles(files, juce::File::findFiles, false, "*.wav");

    juce::File newest;
    for (const auto& file : files)
        if (file.getLastModificationTime() >= startedAt && (!newest.existsAsFile() || file.getLastModificationTime() > newest.getLastModificationTime()))
            newest = file;

    if (!newest.existsAsFile() || newest.getSize() <= 44)
    {
        std::cerr << "FAIL: No capture WAV was produced\n";
        return 3;
    }

    if (!newest.getFileName().contains("tap-42-"))
    {
        std::cerr << "FAIL: Tap ID is missing from capture filename: " << newest.getFileName() << "\n";
        return 4;
    }

    juce::AudioFormatManager formats;
    formats.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader(formats.createReaderFor(newest));
    if (reader == nullptr)
    {
        std::cerr << "FAIL: Could not open capture WAV through JUCE reader\n";
        return 5;
    }

    if (reader->bitsPerSample != 32 || !reader->usesFloatingPointData)
    {
        std::cerr << "FAIL: WAV is not IEEE float32\n";
        return 6;
    }

    const auto expectedSamples = static_cast<int64_t>(playingBlocks * blockSize);
    if (reader->lengthInSamples != expectedSamples)
    {
        std::cerr << "FAIL: Transport gate wrote " << reader->lengthInSamples
                  << " samples; expected exactly " << expectedSamples << "\n";
        return 7;
    }

    const auto samplesToRead = static_cast<int>(juce::jmin<int64>(reader->lengthInSamples, 4096));
    juce::AudioBuffer<float> captured(static_cast<int>(reader->numChannels), samplesToRead);
    if (!reader->read(&captured, 0, samplesToRead, 0, true, true))
    {
        std::cerr << "FAIL: Could not decode capture WAV\n";
        return 8;
    }

    bool foundNonZero = false;
    for (int channel = 0; channel < captured.getNumChannels() && !foundNonZero; ++channel)
        for (int sample = 0; sample < captured.getNumSamples(); ++sample)
            if (std::abs(captured.getSample(channel, sample)) > 1.0e-5f)
            {
                foundNonZero = true;
                break;
            }

    if (!foundNonZero)
    {
        std::cerr << "FAIL: Capture WAV contains only zeros\n";
        return 9;
    }

    std::cout << "PASS: transparent processing, transport-gated exact length, Tap ID, and float32 capture: "
              << newest.getFullPathName() << "\n";
    newest.deleteFile();
    return 0;
}
