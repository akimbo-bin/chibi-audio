#include "../Source/PluginProcessor.h"

#include <cmath>
#include <iostream>

namespace
{
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
}

int main()
{
    juce::ScopedJuceInitialiser_GUI juceInitialiser;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 256;

    ChibiTapAudioProcessor processor;
    processor.setPlayConfigDetails(2, 2, sampleRate, blockSize);
    processor.prepareToPlay(sampleRate, blockSize);

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

    auto* capture = dynamic_cast<juce::AudioParameterBool*>(processor.getParameters()[0]);
    if (capture == nullptr)
    {
        std::cerr << "FAIL: Capture parameter missing\n";
        return 2;
    }

    const auto startedAt = juce::Time::getCurrentTime();
    capture->setValueNotifyingHost(1.0f);
    processor.processBlock(buffer, midi);
    juce::Thread::sleep(30);

    for (int block = 0; block < 64; ++block)
    {
        for (int i = 0; i < blockSize; ++i)
        {
            const auto phase = block * blockSize + i;
            const auto value = static_cast<float>(0.5 * std::sin(2.0 * juce::MathConstants<double>::pi * 110.0 * phase / sampleRate));
            buffer.setSample(0, i, value);
            buffer.setSample(1, i, value * 0.5f);
        }
        processor.processBlock(buffer, midi);
    }

    capture->setValueNotifyingHost(0.0f);
    processor.processBlock(buffer, midi);
    juce::Thread::sleep(100);
    processor.releaseResources();

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

    juce::AudioFormatManager formats;
    formats.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader(formats.createReaderFor(newest));
    if (reader == nullptr)
    {
        std::cerr << "FAIL: Could not open capture WAV through JUCE reader\n";
        return 4;
    }

    if (reader->bitsPerSample != 32 || !reader->usesFloatingPointData)
    {
        std::cerr << "FAIL: WAV is not IEEE float32\n";
        return 5;
    }

    const auto samplesToRead = static_cast<int>(juce::jmin<int64>(reader->lengthInSamples, 4096));
    juce::AudioBuffer<float> captured(static_cast<int>(reader->numChannels), samplesToRead);
    if (!reader->read(&captured, 0, samplesToRead, 0, true, true))
    {
        std::cerr << "FAIL: Could not decode capture WAV\n";
        return 6;
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
        return 7;
    }

    std::cout << "PASS: transparent processing and non-zero float32 capture: "
              << newest.getFullPathName() << "\n";
    newest.deleteFile();
    return 0;
}
