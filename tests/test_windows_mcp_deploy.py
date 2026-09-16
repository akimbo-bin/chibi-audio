from pathlib import Path


RUNNER = Path("deploy/windows/run-chibi-audio-mcp.ps1")
BOOTSTRAP = Path("deploy/windows/bootstrap-chibi-audio-mcp.ps1")
TUNNEL_INSTALLER = Path("deploy/windows/install-openai-tunnel-client.ps1")
RUNBOOK = Path("deploy/CHATGPT_AUDIO_MCP.md")


def test_windows_runner_defaults_writes_off_and_uses_stdio_only():
    source = RUNNER.read_text(encoding="utf-8")
    assert "[switch]$AllowWrites" in source
    assert "CHIBI_AUDIO_MCP_ALLOW_WRITES = if ($AllowWrites) { '1' } else { '0' }" in source
    assert "--transport stdio" in source
    assert "streamable-http" not in source
    assert "127.0.0.1:18765" in source or "LivePort = 18765" in source
    assert "chibi_audio.mcp_server_sections" in source


def test_windows_runner_does_not_launch_or_automate_ableton():
    source = RUNNER.read_text(encoding="utf-8").lower()
    assert "start-process" not in source
    assert "ableton live" not in source
    assert "sendkeys" not in source
    assert "mouse" not in source


def test_bootstrap_only_prepares_dedicated_python_environment():
    source = BOOTSTRAP.read_text(encoding="utf-8").lower()
    assert ".venv-audio-mcp" in source
    assert "-m venv" in source
    assert "pip install -e" in source
    assert "analysis,mcp" in source
    assert "chibi_audio.mcp_server" not in source
    assert "127.0.0.1:18765" not in source


def test_tunnel_installer_is_pinned_and_verifies_published_digest():
    source = TUNNEL_INSTALLER.read_text(encoding="utf-8")
    assert "$version = 'v0.0.14'" in source
    assert "tunnel-client-$version-windows-amd64.zip" in source
    assert "784ab8da7b5a88f0109f1fd8aaf0a1c86067430b896dddf307ef7e3cc49fa1a5" in source
    assert "Get-FileHash -Algorithm SHA256" in source
    assert "Invoke-WebRequest" in source
    assert "tunnel-client.exe" in source


def test_tunnel_installer_does_not_create_profile_or_persist_service():
    source = TUNNEL_INSTALLER.read_text(encoding="utf-8").lower()
    assert "tunnel-client init" not in source
    assert "tunnel-client run" not in source
    assert "runtime api key" in source
    assert "new-service" not in source
    assert "register-scheduledtask" not in source


def test_tunnel_runbook_keeps_live_loopback_and_tunnel_outbound():
    source = RUNBOOK.read_text(encoding="utf-8")
    assert "127.0.0.1:18765" in source
    assert "No inbound firewall rule" in source
    assert "stdio child process" in source
    assert "CHIBI_AUDIO_MCP_ALLOW_WRITES=0" in source
    assert "capture_section" in source
    assert "capture_section_evidence" in source
