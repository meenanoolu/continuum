# Continuum

**A personal multi-agent system that grows into superintelligence for the individual.**

Continuum forces technical makers to finish real projects with genuine understanding.  
It learns each user’s unique patterns of losing momentum and skipping depth, then actively counters them.

> Built during the **Meta Global AI Developer Hackathon** (Oct 27 – Nov 4, 2026)

---

## The Problem

Most builders don’t fail from lack of ideas.  
They lose momentum in the middle, skip understanding, and leave useful work unfinished.

Existing tools generate code or answers.  
They do not protect completion or force real understanding.

---

## How Continuum Works

1. You point it at a project. The **Orchestrator** requires a short, concrete plan for *only the next meaningful piece of work*.
2. The plan is broken into clear steps and assigned to specialized Workers (Code, Research, Test).
3. After every important step the **Gate** locks. The next step cannot start until:
   - A structured reflection is written
   - A plain-language explanation is produced
   - Any missing concept triggers a short required learning path
4. If repeated difficulty appears, the Orchestrator revises the remaining plan.
5. Everything is stored in long-term **personal memory**. Over time Continuum learns *your* specific patterns and adapts.

This is the beginning of personal superintelligence — a system that grows with the individual.

---

## Model Architecture

| Component              | Model                        | Provider          | Purpose                              |
|------------------------|------------------------------|-------------------|--------------------------------------|
| Orchestrator           | Muse Spark 1.3               | Meta Model API    | Planning, gate decisions, revision   |
| Reflection & Explanation | Muse Spark 1.3            | Meta Model API    | Forces understanding                 |
| Learning Path          | Muse Spark 1.3               | Meta Model API    | Targeted teaching                    |
| Workers (Code/Research/Test) | Muse Spark Open         | Baseten           | Execution & tool use                 |
| Coding tool            | Muse Code                    | Meta              | Available to Code Worker             |

---

## What Was Built During the Hackathon

- Full gated multi-agent loop (Orchestrator → Workers → Gate)
- Persistent personal memory that already influences behavior
- Plan revision on repeated difficulty
- Specialized Workers with open-weight inference via Baseten
- Interactive CLI
- End-to-end demonstration on real projects (SlothPrep + FirstStep related work)

All core logic was created between October 27 and November 4, 2026.

---

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # add your keys
python -m src.main