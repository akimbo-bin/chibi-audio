#include "PluginProcessor.h"

ChibiTapAudioProcessor::ChibiTapAudioProcessor()
    : juce::AudioProcessor(
          BusesProperties()
              .withInput("Input", juce::AudioChannelSet::stereo(), true)
              .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      instanceId(juce::Uuid().toString()),
      captureWriter(instanceId)
{
    auto parameter = std::make_unique<juce::AudioParameterBool>(
        juce::ParameterID { "capture", 1 },
        "Capture",
        false);

    captureParameter = parameter.get();
    addParameter(parameter.release());

    auto tapId = std::make_unique<juce::AudioParameterInt>(
        juce::ParameterID { "tap_id", 1 },
        "Tap ID",
        0,
        9999,
        0);

    tapIdParameter = tapId.get();
    addParameter(tapId.release());
}

ChibiTapAudioProcessor::~ChibiTapAudioProcessor()
{
    captureWriter.shutdown();
}

void ChibiTapAudioProcessor::prepareToPlay(double sampleRate, int)
{
    captureWriter.prepare(sampleRate, getTotalNumInputChannels());
}

void ChibiTapAudioProcessor::releaseResources()
{
    captureWriter.setCaptureRequested(false);
}

bool ChibiTapAudioProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const
{
    const auto input = layouts.getMainInputChannelSet();
    const auto output = layouts.getMainOutputChannelSet();

    if (input != output)
        return false;

    return input == juce::AudioChannelSet::mono()
        || input == juce::AudioChannelSet::stereo();
}

void ChibiTapAudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    const auto shouldCapture = captureParameter != nullptr && captureParameter->get();
    const auto configuredTapId = tapIdParameter != nullptr ? tapIdParameter->get() : 0;
    captureWriter.setTapId(configuredTapId);
    captureWriter.setCaptureRequested(shouldCapture);

    auto transportAllowsCapture = true;
    if (auto* hostPlayHead = getPlayHead())
    {
        if (const auto position = hostPlayHead->getPosition())
            transportAllowsCapture = position->getIsPlaying();
        else
            transportAllowsCapture = false;
    }

    // Deliberately read-only: ChibiTap never modifies the host audio buffer.
    if (shouldCapture && transportAllowsCapture)
        captureWriter.push(buffer);
}

void ChibiTapAudioProcessor::getStateInformation(juce::MemoryBlock& destData)
{
    juce::XmlElement state("ChibiTapState");
    state.setAttribute("instanceId", instanceId);
    state.setAttribute("tapId", tapIdParameter != nullptr ? tapIdParameter->get() : 0);
    copyXmlToBinary(state, destData);
}

void ChibiTapAudioProcessor::setStateInformation(const void* data, int sizeInBytes)
{
    if (auto state = getXmlFromBinary(data, sizeInBytes))
    {
        const auto restoredId = state->getStringAttribute("instanceId");
        if (restoredId.isNotEmpty())
        {
            instanceId = restoredId;
            captureWriter.setInstanceId(instanceId);
        }

        const auto restoredTapId = juce::jlimit(0, 9999, state->getIntAttribute("tapId", 0));
        if (tapIdParameter != nullptr)
            tapIdParameter->setValueNotifyingHost(tapIdParameter->convertTo0to1(static_cast<float>(restoredTapId)));
        captureWriter.setTapId(restoredTapId);
    }

    if (captureParameter != nullptr)
        captureParameter->setValueNotifyingHost(0.0f);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ChibiTapAudioProcessor();
}
