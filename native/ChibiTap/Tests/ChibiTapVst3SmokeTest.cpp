#include <JuceHeader.h>

#include <cmath>
#include <iostream>

namespace
{
juce::File captureRoot()
{
    return juce::File::getSpecialLocation(juce::File::userHomeDirectory)
        .getChildFile(".chibi-audio")
        .getChildFile("chibitap")
        .getChildFile("captures");
}

bool bufferMatches(const juce::AudioBuffer<float>& a, const juce::AudioBuffer<float>& b)
{
    if (a.getNumChannels() != b.getNumChannels() || a.getNumSamples() != b.getNumSamples())
        return false;
    for (int ch = 0; ch < a.getNumChannels(); ++ch)
        for (int i = 0; i < a.getNumSamples(); ++i)
            if (a.getSample(ch, i) != b.getSample(ch, i))
                return false;
    return true;
}

juce::File newestCaptureSince(juce::Time since)
{
    juce::Array<juce::File> files;
    captureRoot().findChildFiles(files, juce::File::findFiles, false, "*.wav");
    juce::File newest;
    for (const auto& file : files)
        if (file.getLastModificationTime() >= since
            && (!newest.existsAsFile() || file.getLastModificationTime() > newest.getLastModificationTime()))
            newest = file;
    return newest;
}
}

int main(int argc, char** argv)
{
    juce::ScopedJuceInitialiser_GUI juceInitialiser;
    if (argc != 2)
    {
        std::cerr << "Usage: ChibiTapVst3SmokeTest <ChibiTap.vst3 bundle>\n";
        return 64;
    }

    const juce::File bundle(juce::String::fromUTF8(argv[1]));
    if (!bundle.exists())
    {
        std::cerr << "FAIL: VST3 bundle does not exist: " << bundle.getFullPathName() << "\n";
        return 1;
    }

    juce::VST3PluginFormat format;
    juce::OwnedArray<juce::PluginDescription> descriptions;
    format.findAllTypesForFile(descriptions, bundle.getFullPathName());
    std::cout << "descriptions=" << descriptions.size() << "\n";
    for (auto* d : descriptions)
        std::cout << "plugin=" << d->name << " manufacturer=" << d->manufacturerName
                  << " version=" << d->version << "\n";

    if (descriptions.isEmpty())
    {
        std::cerr << "FAIL: VST3 wrapper could not be described\n";
        return 2;
    }

    juce::String error;
    auto instance = format.createInstanceFromDescription(*descriptions[0], 48000.0, 256, error);
    if (instance == nullptr)
    {
        std::cerr << "FAIL: VST3 wrapper could not be instantiated: " << error << "\n";
        return 3;
    }

    instance->setPlayConfigDetails(2, 2, 48000.0, 256);
    instance->prepareToPlay(48000.0, 256);

    juce::AudioBuffer<float> buffer(2, 256);
    for (int i = 0; i < buffer.getNumSamples(); ++i)
    {
        const auto v = static_cast<float>(0.25 * std::sin(2.0 * juce::MathConstants<double>::pi * 440.0 * i / 48000.0));
        buffer.setSample(0, i, v);
        buffer.setSample(1, i, -v);
    }
    juce::AudioBuffer<float> original;
    original.makeCopyOf(buffer);
    juce::MidiBuffer midi;
    instance->processBlock(buffer, midi);
    if (!bufferMatches(buffer, original))
    {
        std::cerr << "FAIL: hosted VST3 modified pass-through audio\n";
        return 4;
    }

    juce::AudioProcessorParameter* capture = nullptr;
    for (auto* parameter : instance->getParameters())
        if (parameter != nullptr && parameter->getName(128).equalsIgnoreCase("Capture"))
        {
            capture = parameter;
            break;
        }
    if (capture == nullptr)
    {
        std::cerr << "FAIL: hosted VST3 has no Capture parameter\n";
        return 5;
    }

    const auto started = juce::Time::getCurrentTime();
    capture->setValueNotifyingHost(1.0f);
    instance->processBlock(buffer, midi);
    juce::Thread::sleep(40);
    for (int block = 0; block < 96; ++block)
    {
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            const auto n = block * buffer.getNumSamples() + i;
            const auto v = static_cast<float>(0.5 * std::sin(2.0 * juce::MathConstants<double>::pi * 110.0 * n / 48000.0));
            buffer.setSample(0, i, v);
            buffer.setSample(1, i, v * 0.5f);
        }
        instance->processBlock(buffer, midi);
    }
    capture->setValueNotifyingHost(0.0f);
    instance->processBlock(buffer, midi);
    juce::Thread::sleep(150);
    instance->releaseResources();
    instance.reset();
    juce::Thread::sleep(50);

    const auto wav = newestCaptureSince(started);
    if (!wav.existsAsFile() || wav.getSize() <= 44)
    {
        std::cerr << "FAIL: hosted VST3 produced no capture WAV\n";
        return 6;
    }

    juce::AudioFormatManager formats;
    formats.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader(formats.createReaderFor(wav));
    if (reader == nullptr || reader->bitsPerSample != 32 || !reader->usesFloatingPointData)
    {
        std::cerr << "FAIL: hosted capture is not a readable float32 WAV\n";
        return 7;
    }

    const auto count = static_cast<int>(juce::jmin<int64>(reader->lengthInSamples, 4096));
    juce::AudioBuffer<float> captured(static_cast<int>(reader->numChannels), count);
    if (!reader->read(&captured, 0, count, 0, true, true))
    {
        std::cerr << "FAIL: hosted capture could not be decoded\n";
        return 8;
    }
    bool nonZero = false;
    for (int ch = 0; ch < captured.getNumChannels() && !nonZero; ++ch)
        for (int i = 0; i < captured.getNumSamples(); ++i)
            if (std::abs(captured.getSample(ch, i)) > 1.0e-5f)
            {
                nonZero = true;
                break;
            }
    if (!nonZero)
    {
        std::cerr << "FAIL: hosted capture contains only zeros\n";
        return 9;
    }

    std::cout << "PASS: VST3 wrapper scan, instantiate, transparent process, and float32 capture: "
              << wav.getFullPathName() << "\n";
    wav.deleteFile();
    return 0;
}
