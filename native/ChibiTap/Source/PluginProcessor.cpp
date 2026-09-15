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
    captureWriter.setCaptureRequested(shouldCapture);

    // Deliberately read-only: ChibiTap never modifies the host audio buffer.
    captureWriter.push(buffer);
}

void ChibiTapAudioProcessor::getStateInformation(juce::MemoryBlock& destData)
{
    juce::XmlElement state("ChibiTapState");
    state.setAttribute("instanceId", instanceId);
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
    }

    if (captureParameter != nullptr)
        captureParameter->setValueNotifyingHost(0.0f);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ChibiTapAudioProcessor();
}
