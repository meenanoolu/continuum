# Continuum

**Ship with AI. Own what you ship.**

Continuum is a multi-agent coding system that helps you build software without losing sight of how it works. AI agents plan, implement and test changes, but you must understand each step before moving forward.

## Why Continuum?

AI can generate code faster than you can understand it. Continuum makes understanding part of the development process:

- **Plan:** Break a task into small, understandable steps.
- **Build:** Let Code, Test and Research workers implement each step.
- **Verify:** Independently check the changes and collect evidence.
- **Understand:** Explain the code and answer questions at a learning Gate before continuing.
- **Adapt:** Use local learning memory to focus future Gates on concepts that need more work.

## How it works

1. Describe a task or attach an existing project.
2. The Orchestrator creates a step-by-step plan.
3. A worker implements the current step using tools in the project workspace.
4. Continuum checks the result and captures the code diff.
5. You explain the change and answer questions based on the implementation.
6. If you need more practice, Continuum provides a focused learning path and a new retry question. The next step stays locked until you pass.

## Features

- Multi-agent workflow with Code, Test and Research workers.
- Independent verification instead of relying only on worker summaries.
- Learning Gates with explain-back prompts, evidence-grounded questions and retry paths.
- Adaptive local memory that can adjust later questions and identify prerequisite concepts.
- Project screenshots and diagrams as planning context.
- Model-call tracing with provider, model, latency and available usage metadata.
- Local project sessions that can be resumed.

### Voice input and transcription

Continuum supports push-to-talk voice input through **Muse Voice Transcribe 1.0**. You can record and transcribe:

- Initial project and task descriptions.
- Explain-back responses and answers at the learning Gate.

The browser records audio and sends it to `POST /api/transcribe`. The backend uses `ffmpeg` to convert it to mono, 16-bit WAV at 16 kHz, then sends it to Meta's ASR endpoint in `PUSH_TO_TALK` mode. The transcript is inserted into the text field, where you can edit it before submitting.

Recordings stop after 45 seconds. The endpoint rejects empty or very short recordings and files larger than 8 MB. Voice input requires microphone permission, `ffmpeg`, network access and a configured Meta API key. Typing is always available; Continuum does not provide a separate voice-conversation interface.

## Architecture

```text
Browser UI
  |-- Task input (typed or transcribed)
  |-- Execution events, evidence and learning Gate
  |
FastAPI (src/api.py)
  |-- Orchestrator (src/orchestrator.py)
  |     |-- Planning and worker routing
  |     `-- Workflow progression
  |-- Agent and workers (src/agent.py, src/workers/)
  |     |-- Tool-calling loop
  |     `-- Workspace operations and verification
  |-- Gate (src/gate.py)
  |-- Local learning memory (src/memory/)
  |-- Model clients (src/models/)
  `-- Voice transcription (/api/transcribe)
       `-- ffmpeg -> Meta Muse Voice Transcribe
```

The frontend uses plain HTML, CSS and JavaScript.

## Models and services

| Component | Model or service | Purpose |
|---|---|---|
| Planning and learning Gate | Muse Spark 1.3 (Meta Model API) | Plans, questions, evaluations and learning paths |
| Image understanding | Muse Spark vision | Interprets attached screenshots and diagrams |
| Worker loop | Muse Spark Open (Baseten) | Code, Test and Research tasks |
| Optional coding delegate | Muse Code CLI | Delegates coding when enabled |
| Voice transcription | Muse Voice Transcribe 1.0 | Converts speech to editable text |

## Getting started

### Requirements

- Python 3.10+
- Meta Model API key
- Baseten API key
- `ffmpeg` on `PATH` (voice transcription only)

### Install

```bash
git clone https://github.com/meenanoolu/continuum.git
cd continuum
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

Add your API keys to `.env`:

```dotenv
META_API_KEY=your_meta_model_api_key
BASETEN_API_KEY=your_baseten_api_key
```

Start the application:

```bash
python -m src.api
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

To check live provider configuration before starting:

```bash
python scripts/smoke_live.py
```

## Run tests

```bash
python -m pytest
```

The offline test suite uses a deterministic fake model and does not require live API credits. To run the UI in fake-model mode:

```bash
# macOS / Linux
CONTINUUM_FAKE_LLM=1 python -m src.api

# Windows PowerShell
$env:CONTINUUM_FAKE_LLM = "1"
python -m src.api
```

Fake-model mode is for local testing and does not support live voice transcription.

## Configuration

See `.env.example` for all settings. The main variables are:

| Variable | Purpose |
|---|---|
| `META_API_KEY` | Meta model and voice transcription authentication |
| `BASETEN_API_KEY` | Worker model authentication |
| `USE_MUSE_CODE` | Enables optional Muse Code CLI delegation when set to `1` |
| `CONTINUUM_FAKE_LLM` | Enables deterministic fake-model mode when set to `1` |

## Limitations

- **Local and single-user:** Sessions and learning memory are stored locally. Accounts and multi-user synchronization are not currently supported.
- **Execution safety:** The local sandbox applies restrictions and resource limits, but it is not a strong security boundary. Use an isolated container or disposable environment for untrusted code.
- **Model-dependent evaluation:** Gate quality depends on model output and provider availability.
- **External services:** Live planning, workers and transcription require their respective providers, credentials and network access.

