# Memex: Agentic RAG System (Second Brain)

> **"A Self-Evolving, Neural-Cognitive Knowledge System."**
> *Designed for high-fidelity context retention and active cognition.*

---

## 🚀 Key Features

Memex is not just a document retrieval library; it uses **Distributed Cognition Architecture** to simulate human cognitive processes. It solves the core pain points of traditional RAG: "Retrieval-Induced Forgetting" and "Semantic Loss from Slicing".

### 1. 🧬 Parent-Child Indexing
Traditional RAG slices documents into chunks, losing context. Memex uses a **Dual-Layer Indexing Architecture**:
- **Layer 1 (Parent)**: Stores the complete original archive for macro-semantics.
- **Layer 2 (Child)**: Stores atomized knowledge chunks.
- **Context Injection**: Before storage, every chunk is injected with its parent's metadata (Filename, Date, Chapter). Even an isolated sentence like "It cost $50" becomes "**[2023 Financial Report - Project A]** It cost $50."

### 2. 🌱 Gardener Agent
A knowledge base shouldn't be a static landfill; it needs a gardener.
- **Autonomous Regression**: A background agent (Running on NAS / Nightly).
- **Semantic Refactoring**: Scans raw data ingested yesterday and uses advanced models (Gemini 1.5 Pro / Claude 3.5 Sonnet) to perform **Semantic Splitting** and **Metadata Completion**.
- **Continuous Evolution**: Dead data from yesterday becomes living knowledge tomorrow.

### 3. ⚗️ Nightly Distillation
Memex features a **Hippocampal Replay Mechanism** similar to human sleep.
- **Daily Briefing**: The `ChatDistiller` wakes up at 2 AM to analyze all T-1 conversations.
- **Memory Compression**: Distills lengthy chat logs into concise "Daily Insights" and "Todos".
- **Knowledge Fusion**: These insights are re-ingested into the knowledge base as long-term memory.

---

## 🏗️ Architecture

<!-- Architecture Diagram Placeholder -->
> [!NOTE]
> **Architecture Diagram Placeholder**
> (See `.ai/AI_MAP.md` for the single source of truth regarding system architecture)

### The Neural Loop

1.  **Node A: Neural Router (Prefrontal Cortex)**
    *   **Intent Recognition**: No blind searching. The Router uses **Chain of Thought (CoT)** to determine if the user wants to `search`, `chat`, or `analyze`.
    *   **Self-Reflection**: If intent is ambiguous, it triggers the `Hesitation Protocol` to ask clarifying questions instead of guessing.

2.  **Node B: Hippocampus (Memory & Retrieval)**
    *   **Hybrid Search**: Dense Vector + Sparse Keyword + Re-ranker (BGE-M3).
    *   **Temporal Anchoring**: Injects `Current Server Time` during retrieval to give AI a sense of time.

3.  **Node C: Neural Refiner (Cognitive Check)**
    *   **Void Guardrail**: If search yields zero results, the system circuit-breaks the LLM call to prevent hallucination, falling back to a "Recent Files Browser" mode.

---

## 🛠️ Tech Stack

*   **Backend**: Python 3.11 + FastAPI (Async High Performance)
*   **Database**: PostgreSQL 16 + `pgvector`
*   **AI Engine**: Multi-Provider Support (Gemini Pro, Claude 3.5 Sonnet, Qwen/DashScope)
*   **Vector Search**: BGE-M3 (Embedding) + BGE-Reranker-V2-M3 (ONNX Runtime)

---

## 💻 Development & Environment

### Running on NAS
Designed for **High-Availability NAS** environments (Synology/QNAP/Unraid).
- **Docker-First**: All components are containerized.
- **Volume Mapping**: Direct mapping to physical NAS storage.
- **Resource Optimization**: ONNX Runtime optimization for NAS CPU/RAM constraints.

### 🤖 AI-Native Development
Built with **Human-in-the-loop** methodology, code co-authored by Advanced AI Agents.

| Role | Tool / Model | Status |
| :--- | :--- | :--- |
| **Integrator** | **Cursor (Auto Mode)** | Primary Editor |
| **Architect** | **Antigravity Claude 3 Opus 4.5** | System Design |
| **Engineer** | **Antigravity Google Gemini 3.0 Pro** | Implementation |

> "Code written by AI, for AI, curated by Human."

---

## 📂 Project Structure

See [doc/PROJECT_STRUCTURE.md](doc/PROJECT_STRUCTURE.md) for the full directory tree.

*   `src/services/agents/`: Cognitive Agents (Router, Retrieval)
*   `src/plugins/`: Plugin System (Gardener, Archiver)
*   `src/models/`: Dual-Layer Indexing Data Models
*   `.ai/`: **Critical** - Architecture Source of Truth

---

## ⚡ Quick Start

1.  **Configuration**
    ```bash
    cp .env.example .env
    # Fill in OpenAI / DashScope / Gemini API Keys
    ```

2.  **Launch (NAS/Docker)**
    ```bash
    docker-compose -f docker-compose.nas.yml up -d --build
    ```

3.  **Initialize Database**
    ```bash
    docker exec -it memex-backend python scripts/init_database.py
    ```

---

*Memex © 2025 - Designed for the Age of AI.*
