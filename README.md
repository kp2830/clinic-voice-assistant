# CareDesk — Clinic Appointment Voice Assistant (multi-agent handoffs)

A tiny patient-support agent for a fictional clinic, built with
**LangChain / LangGraph** multi-agent **handoffs**, traced to **LangSmith** — and
served as both a **text chat** and a real-time **Pipecat voice bot** from the
same graph.

It demonstrates the **"agents as graph nodes"** pattern (what we've been calling
*Option A*): a **triage** front desk plus three specialists —
**cancellation**, **visit credits**, and **booking** — each a distinct node in the
graph. The patient stays "inside" a specialist across turns because the active
agent is stored in state, not because execution pauses there.

> The graph re-enters at `START` every turn and routes straight to the
> `active_agent`. State remembers where the conversation is — the engine does
> not freeze you inside a node.

```
START ──(route_initial: active_agent or "triage")──► triage ──┐
                                                              ├─► cancellation ─┐
                                                              ├─► credits ──────┼─► (route_after_agent) ─► END
                                                              └─► booking ──────┘            ▲
                                                  specialists ── transfer_to_triage ─────────┘
```

Each agent's handoff tools (`transfer_to_cancellation`, …) return a
`Command(goto=..., graph=Command.PARENT)` that jumps to a sibling node and
updates `active_agent`. This is the LangChain
["Multiple agent subgraphs"](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)
handoff pattern.

## What it does

- **Cancel an appointment** — give any patient ID; the upcoming visit is cancelled and its credit refunded.
- **Check visit credits** — returns a mock breakdown (general consult / specialist consult / lab test).
- **Book an appointment** — lists a mock doctor schedule and spends one credit per booking.

All data is **mocked in-process** (`mock_data.py`). There is no database or
external API: any patient ID works, and tool side effects mutate an
in-memory dict that resets when the server restarts.

## Layout

```
src/clinic_support/
├── graph.py                 # the 4 agents wired as nodes + routing (the core)
├── tools.py                 # business tools + transfer_to_* handoff tools
├── prompts.py               # one system prompt per agent
├── mock_data.py             # in-memory patient store
├── server.py                # FastAPI text chat: GET / (page) + POST /chat
├── voice.py                 # Pipecat voice bot (same graph, spoken)
├── langgraph_llm_service.py # adapter: runs the graph as Pipecat's LLM stage
└── static/
    └── index.html           # the chat box
```

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd clinic-voice-assistant
uv sync
cp .env.example .env      # then fill in keys
```

Set in `.env`:

- `ANTHROPIC_API_KEY` — required; the agent runs on `anthropic:claude-sonnet-4-6`.
- `OPENAI_API_KEY` — required for the **voice bot** (speech-to-text and
  text-to-speech run on OpenAI).
- `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` — optional, to see the
  handoffs in the trace tree. `LANGSMITH_PROJECT` defaults to
  `clinic-voice-assistant`.

## Run

```bash
uv run clinic-voice-assistant
```

Open http://127.0.0.1:8000 and chat. Try:

- "I need to cancel my appointment" → watch the badge switch to **cancellation**,
  then give any ID.
- "How many visit credits do I have left?" → **credits**.
- "I'd like to book an appointment" → **booking**, then "show me the slots"; it asks
  for the date before booking.
- Mid-conversation, switch intent ("actually, how many credits do I have?") —
  the specialist hands you back to triage, which re-routes you.

## Talk to it (voice)

The same graph also runs as a real-time **Pipecat** voice bot — the agent
doesn't change, it just gets ears and a mouth:

```bash
uv run python -m clinic_support.voice
```

Open the URL it prints (default http://localhost:7860), click **Connect**, allow
the mic, and talk. The flow is STT → the LangGraph brain → TTS, with barge-in
(interrupt the bot mid-sentence). Here the graph runs **statelessly**: Pipecat's
context is the source of truth, and the active specialist is recovered from the
transcript each turn, so interruptions never corrupt routing state.

`voice.py` is the whole story — the only real change from the text app is that
the LLM stage is `LangGraphLLMService` (our graph) instead of a stock model.

## Evaluation

```bash
uv run clinic-support-eval
```

Runs a handful of scripted conversations through the graph and checks:

- **Latency** — time per test case (in the terminal table).
- **Routing correctness** — did the graph land on the right specialist
  (including a mid-conversation intent switch, exercising `transfer_to_triage`
  and re-routing, not just a single handoff).
- **Hallucination** — for credits/booking, the agent's reply is checked
  against `mock_data` directly (the actual credit counts and appointment names),
  not against hardcoded expected numbers — so it's really checking "did the
  agent say what's true," not "did it match a fixture."

It also runs one **exploratory** case with no pass/fail: a request outside
all three specialists' scope (e.g. a billing-reimbursement question). Triage's
current prompt has no "hand off to a human" option, so this documents a real
gap rather than asserting behavior that doesn't exist — worth reading before
extending the prompts.

Requires `ANTHROPIC_API_KEY` — this calls the real model, not a mock.

## What you see in LangSmith

With `LANGSMITH_TRACING=true`, LangChain/LangGraph trace themselves
automatically — no extra wiring needed. One trace per turn (text or voice): a
handoff shows the triage agent calling a `transfer_to_*` tool, then the
specialist node running and replying, so the routing decision and the
specialist's work sit side by side in the tree. Voice conversations are
recorded to a local WAV file (path logged on disconnect) for manual review.
