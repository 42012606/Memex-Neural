# Memex Architecture Map — Source of Truth (2025-12-18 Updated)

> **⚠️ CRITICAL FOR AI AGENTS**: This is the **ONLY** source of truth for the system architecture. Trust this over `README.md` for technical details (file paths, class names, column names).
> **Key Changes**: **ChatDistiller** (Daily Reports); **Hybrid Slicing** (Recursive+Semantic); **TextTools** utility.

## 0) 📍 Codebase File Index (Core Responsibilities)

| File Path | Primary Responsibility | Key Components |
| :--- | :--- | :--- |
| `src/services/ai/dashscope_provider.py` | **核心**: 承载所有 LLM/Vision 交互逻辑，包括 Prompt 管理 (Metadata/Vision/Embedding) | `analyze_file`, `recognize_image` |
| `src/models/vector_node.py` | **核心**: 定义父子索引结构 (Child Chunks)，支撑细粒度检索 | `VectorNode` |
| `src/plugins/gardener_plugin.py` | **Gardener Agent**: Background refinement service. Uses **Hybrid Slicing** (Recursive + AI) to split Archives. | `RefinerAgent`, `semantic_split`, `context_enrich` |
| `src/services/chat_distiller.py` | **Chat Distiller**: Nightly service that summarizes T-1 chat history into Daily Reports. | `ChatDistiller`, `run_daily_distillation` |
| `src/services/ai/openai_provider.py` | **AI Driver**: OpenAI 兼容协议适配器 (含 Thinking Mode 解析) | `OpenAIProvider`, `chat`, `analyze_file` |
| `src/services/ai/dashscope_provider.py` | **AI Driver**: 阿里通义千问适配器 (含多模态/语音) | `DashscopeProvider`, `chat`, `recognize_image` |
| `src/services/distillation.py` | **Nightly Job**: 负责对话蒸馏与文件简报生成 | `DistillationService`, `distill_daily_report` |
| `src/utils/text_tools.py` | **Text Utils**: Lightweight RecursiveCharacterTextSplitter for safe mechanical slicing. | `RecursiveCharacterTextSplitter` |
| `src/services/agents/router_agent.py` | **核心**: 意图识别路由器 V3，支持 Search/Chat/Export/Analyze 等多维意图。 | `neural_route`, `_parse_intent` |
| `src/services/export_service.py` | **Export Service**: 批量打包服务，负责将多个 Archives 融合为单文件导出。 | `export_as_markdown` |
| `src/services/agents/retrieval_agent.py` | 负责向量检索、Parent-Child 聚合、Local Rerank + **Keyword Verification** (Root Cause Fix) | `hybrid_search`, `search_by_vector` |
| `src/services/ai/rerank_provider.py` | **Rerank Service**: 封装 BGE-M3 模型 (ONNX Runtime Preferred / PyTorch Fallback) | `RerankService`, `rerank` |
| `src/services/context_memory.py` | **Memory Service**: Rolling Summary & Sliding Window context management. | `ContextMemoryService`, `generate_rolling_summary`, `build_context_with_memory` |
| `src/main.py` | FastAPI Entry, Lifespan (DB/Scheduler), Routes. | `app`, `lifespan` |
| `src/api/storage_endpoints.py` | **[NEW] Storage API**: File Browser (Browse/Delete), Preview (Text/OCR Fallback). | `browse_directory`, `delete_physical_file` |
| `src/core/events.py` | **Event Bus**: Decoupled messaging system. | `EventBus`, `Event` |
| `src/core/plugins.py` | **Plugin System**: Modular logic loader. | `PluginManager` |
| `src/plugins/core_archiver.py` | **Archiver**: Handles file moves/renaming. | `CoreArchiverPlugin` |
| `src/plugins/core_vectorizer.py` | **Vectorizer**: Embeds full archives with Metadata Injection (Title/Tags). | `CoreVectorizerPlugin` |
| `scripts/export_onnx.py` | **Ops Tool**: Exports PyTorch Re-ranker models to ONNX. | `export_onnx` |
| `src/services/ai_service.py` | **Model Pool**: Unified AI interface with Failover & TTS. | `AIService`, `synthesize_audio` |
| `src/core/prompt_manager.py` | **PromptOps**: Manages dynamic system prompts (DB + Cache). | `PromptManager`, `get_prompt` |
| `src/models/prompt_config.py` | **Prompt Model**: Storage for prompt versions. | `PromptConfig` |
| `src/api/prompts.py` | **Prompt API**: Endpoints for Prompt Laboratory. | `/api/prompts` |
| `web/js/app.js` | **Frontend**: Vue3 Dual-View (Chat/Voice), Viewport Logic, Dashboard. | `app`, `setupMobileViewport` |
| `web/js/audio_manager.js` | **Audio Service**: Handling Recording (MediaRecorder) & Playback (Howler/Native). | `startRecording`, `playAudioBase64` |
| `src/services/nightly_jobs.py` | **Scheduler**: Nightly cron tasks (Maintenance/Reporting). | `run_nightly_jobs` |
| `src/core/config_definitions.py` | **Config Schema**: Central registry for System Settings UI. | `get_all_definitions` |

## 1) Tech & Runtime
- **Backend**: FastAPI + Uvicorn (Python 3.11)
- **DB**: PostgreSQL 16 + pgvector
  - `archives.embedding`: `vector(1024)` (Full Doc)
  - `vector_nodes.embedding`: `vector(1024)` (New/Atomic Chunk)
- **AI**: Multi-Provider (Gemini/DashScope/OpenAI) via `ai_models` table.
- **Orchestration**: `docker-compose`.

## 2) Data Model (The Reality)
### Core Entities
- **`archives`** (`src/models/archive.py`)
  - **Concept**: The "Parent" Document.
  - `id`: PK.
  - `full_text`: Complete content.
  - `embedding`: `Vector(1024)` (Coarse retrieval).
  - `meta_data`: JSONB (semantic date, tags).

- **`vector_nodes`** (`src/models/vector_node.py`)
  - **Concept**: The "Child" Atomic Chunk (**Parent-Child Indexing**).
  - `id`: PK.
  - `parent_archive_id`: FK to `archives.id`.
  - `content`: Semantically split & context-enriched text.
  - `embedding`: `Vector(1024)` (**High-Res Retrieval**).
  - `chunk_index`: Sequence order.

- **`users`** (`src/models/user.py`)
  - `id`: PK (1=Admin).
  - `username`, `hashed_password`.

### Control Entities
- **`proposals`** (`src/models/proposal.py`): Pending actions (e.g., "Refine Archive #123") waiting for user `approve`/`reject`.
- **`ai_models`** (`src/models/ai_config.py`): Configuration for Router, Reasoning, Retrieval models.

## 3) Services & Logical Flows

### A. Ingestion Loop (The "Gardener" Flow)
1. **Upload**: User uploads file -> `FileProcessor` creates PENDING `archives` record.
2. **Event**: `FILE_UPLOADED` emitted.
3. **Archiver**: `CoreArchiverPlugin` moves file, renames (Semantic Rename), updates DB -> `ARCHIVE_COMPLETED`.
4. **Vectorizer**: `CoreVectorizerPlugin` embeds full text (1024 dim).
5. **Gardener (Nightly/Background)**:
   - `RefinerAgent` scans `archives` without `vector_nodes`.
   - **Semantic Split**: Breaks text into logical chunks.
   - **Context Enrichment**: Adds parent metadata (filename, date) to each chunk (De-contextualization fix).
   - **Proposal**: Creates a `refine_archive` proposal.
   - **Execution**: Upon user approval, `VectorNode` records are created and embedded (1024 dim).

### B. Router Loop (The "Neural" Flow)
1. **Input**: User Query + History Summary.
2. **Analysis (`RouterAgent.neural_route`)**:
   - **Chain of Thought (CoT)**: Internal reasoning (<50 words) regarding user intent.
   - **Self-Reflection (Hesitation)**: If confidence < 0.7, returns `needs_clarification=True` + Question.
   - **Intent Classification**: `search` vs `chat` vs `analyze` vs `export`.
   - **Keyword Extraction**: Atomic split ("发票", "yesterday").
3. **Dispatch**: Returns JSON control block to `chat.py`.

### C. Export Loop (Knowledge Fusion)
1. **Trigger**: Router detects `intent=export`.
2. **Safety**: System finds files -> Asks for User Confirmation.
3. **Fusion**: `ExportService` pulls full_text from `archives`, cleans metadata, merges to `.md`.
4. **Delivery**: Returns static download link.

### D. Retrieval & Context Loop
1. **Search**:
   - If `intent=search`: Hybrid Search (Vector + Keyword) on `archives` (and future `vector_nodes`).
   - If `intent=analyze`: Direct ID fetch (bypass search).
2. **Memory (`ContextMemoryService`)**:
   - **Sliding Window**: Raw injection of last 10 messages.
   - **Rolling Summary**: Recursive distillation of older messages.
3. **Generation**:
   - System Prompt + Context (Search + Memory) + User Query -> LLM.

## 4) Key Concepts & Terms for Documentation
- **Parent-Child Indexing**: The architecture of having a coarse parent document (`archives`) linked to fine-grained child chunks (`vector_nodes`) for precise retrieval without losing context.
- **Intent Routing**: The decision layer (`RouterAgent`) that determines *how* to answer (search DB? read file? just chat?) before doing it.
- **Self-Reflection**: The router's ability to pause (`needs_clarification`) and ask the user for help instead of guessing (Anti-Hallucination).
- **Chain of Thought (CoT)**: The explicit reasoning step the Router takes before outputting a JSON decision.
- **Context Enrichment**: The process where "Child" chunks inherit metadata from "Parent" archives so they stand alone semantically (e.g., "It costs $5" -> "The [Invoice 2023-11] costs $5").