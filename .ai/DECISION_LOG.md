# Memex 决策记录 (增量记录)

## 2025

### 十二月 (December)

#### [2025-12-08]
- **Router 2.0 完成**：小模型 JSON 路由，analyze 场景自动取最新档案并注入全文；AIService 在 analyze 时强制拼接 `full_text`。
- **夜间双任务完成**：Daily Summary 写入 `data/users/{uid}/Memex_Logs/`; Memory Distillation 追加到 `data/user_profile.md`，加入防幻觉/防拼音规则。
- **RAG 语义时间过滤**：RetrievalAgent 支持 `time_range`，优先用 `meta_data.semantic_date`。
- **标签清洗**：Prompt 与后处理去除典型拼音标签；仍需进一步硬化（P1.5 Critical 待办）。

#### [2025-12-11] [特性] 阶段 5.1 原子化精炼器 (Gardener)
- **决策**: 采用 Proposal (提案) 机制实现非侵入式数据清洗。
- **原因**: 原始归档 (Archive) 需保持法律效力不可变；AI 理解需更细粒度切片 (VectorNode)。
- **影响**: 引入 `vector_nodes` 和 `proposals` 表；`RefinerAgent` 夜间生成提案，等待人工/规则审批 (Human-in-the-Loop 基础)。

#### [2025-12-11] [稳定性] AI 服务故障转移 (Failover) 实现
- **决策**: 为 STT, TTS, Vision, Embedding 实现基于优先级的轮询 Failover。
- **原因**: 解决单点模型故障导致服务不可用的问题；适配 Qwen TTS 的 URL 响应格式。
- **影响**: `ai_service.py` 和 `audio_io_plugin.py` 逻辑更健壮；需确保 DB 中配置至少 2 个模型以发挥效果。

#### [2025-12-08] [聊天/RAG] 恢复 Router+Retrieval 链路
- **决策**: `/api/chat` 先路由判 intent/keywords，命中则向量检索并拼 context，再送推理模型；附加当前时间减小“未来日期”误判。
- **原因**: 解决上传文件/消费记录未被检索的问题。
- **影响**: 路由模型仍自动切换，推理模型不自动切换，失败直返错误。

#### [2025-12-08] [故障转移范围] 推理模型关闭自动切换
- **决策**: `ai_service` 仅路由池支持 failover，推理模型失败直接报错，供前端手动切换。
- **原因**: 遵循业务预期，避免网络抖动时静默换模型。
- **影响**: 单模型故障会立即返回错误，需用户选择其它模型。

#### [2025-12-06] [架构] V3.0 前后端分离
- **决策**: 废弃 Streamlit，采用 FastAPI + Vue3。
- **原因**: 提升移动端体验与布局自由度；端口迁移 5000，挂载 static。

#### [2025-12-06] [UI] V3.4 仪表盘布局
- **决策**: Admin Dashboard 风格替代 Chat-First 胶囊样式。
- **原因**: 侧边栏功能增多，需层级与空间；Tailwind CDN 使用类名替代 @apply。

#### [2025-12-06] [特性] 置信度与透明化
- **决策**: AI 输出 `confidence` (置信度)、`reasoning` (推理过程) 字段。
- **原因**: 提升可解释性与信任感。

#### [2025-12-12] [架构] Schema 驱动配置
- **背景**: 硬编码的设置界面每次新增字段都需要修改 3+ 个文件 (后端, HTML, JS)。
- **决策**: 采用“后端优先”的 Schema。`src/core/config_definitions.py` (Pydantic) 作为唯一真理源。前端通过 `/config/schema` 动态渲染界面。
- **影响**: 新增设置只需修改 Python 代码。前端通用且免维护。支持动态提示、验证和分组。

#### [2025-12-12] [架构] PromptOps (第一阶段)
- **背景**: 硬编码的系统提示词需要重启应用才能更新；缺乏版本控制和透明度。
- **决策**: 将提示词解耦到 SQLite `prompt_configs` 表；实现带内存缓存的 `PromptManager`。
- **影响**: 可通过“提示词实验室” UI 热更新提示词。`Gardener`、`Router` 和 `AIService` 现在动态获取提示词。

#### [2025-12-12] [设计] 神经风格 UI 演进 (第二阶段)
- **背景**: UI 感觉静态且功能化，但缺乏“生命力”。
- **决策**: 采用“玻璃拟态 (Glassmorphism)”设计系统 (背景模糊、半透明背景) 和微交互 (流式打字效果、触觉反馈)。
- **影响**: 显著的用户体验升级。为知识库引入“侧边抽屉”模式以优化信息密度。

---

## [已归档] 架构演进日志 (v2.2)
> *注：以下内容合并自原 `log.md` (2025-12-17)*

### 1. 核心更新摘要 (2025-12-11)
1.  **感知层进化**：语音流式输出 (TTS) + PWA 离线缓存 + 负反馈闭环。
2.  **数据层哲学**：确立了“非破坏性原子化”原则——原文只读，通过影子向量节点进行清洗、拆分与语境补全；支持按需重组。
3.  **管理层升级**：确立了“独立 Dashboard”与“提案/批准 (Proposal/Approval)”机制，实现 Human-in-the-Loop。

### 2. 代码库文件所引 (关键组件)

| 文件路径 | 职责 | 关键类/函数 |
| :--- | :--- | :--- |
| `src/plugins/audio_io_plugin.py` | **感知插件**: 负责 TTS 流式合成 | `AudioIOPlugin`, `synthesize(stream=True)` |
| `src/plugins/gardener_plugin.py` | **数据园丁 (已实现)**: 负责原子化拆分与提案 | `GardenerPlugin`, `scan_and_propose()` |
| `src/models/vector_node.py` | **新模型 (已实现)**: 存储切片/影子向量 | `VectorNode` (parent_id, content, embedding, meta) |
| `src/models/proposal.py` | **新模型 (已实现)**: 存储待批准的操作 | `Proposal` (type, payload, status) |
| `web/sw.js` | **PWA**: Service Worker 缓存控制 | `install`, `fetch` (Stale-while-revalidate) |
| `web/dashboard.html` | **独立视图**: BI 仪表盘与审批台 | 用户隔离的指标 & 提案操作 |

### 3. 数据策略: "原子影子" 架构

**核心原则：原文不可变 (Immutable Source) + 影子切片 (Shadow Chunks)**

* **L1: 物理归档 (The Source)**
    * 表：`archives`
    * 职责：法律意义上的原始文件。**只读，永不被 AI 修改**。
    * 存储：原始文件路径 + 原始全文。
* **L2: 向量节点 (The Atoms)**
    * 表：`vector_nodes` (替代原先直接在 archives 存向量的做法)
    * 职责：这是 AI 理解的世界。内容经过清洗、拆分和语境补全。
    * 结构：
        * `parent_id`: 关联 L1 Archive。
        * `chunk_content`: 实际被向量化的文本（可能经过 AI 改写/补全）。
        * `chunk_index`: 排序索引，支持合并还原。
        * `embedding`: 768维向量。
        * `meta`: 包含来源标签 (`category`, `tags`)。

### 4. "夜间法庭" 工作流 (人机回环)

**不再自动修改数据，而是生成“提案”**

1.  **Gardener Agent (夜间运行)**:
    * 扫描 `archives`。
    * 发现重复 -> 生成 `Proposal(type='dedup')`。
    * 发现长文 -> 模拟拆分 -> 生成 `Proposal(type='split')`。
    * 发现上下文缺失 -> 生成 `Proposal(type='enrich')`。
2.  **Dashboard (日间审批)**:
    * 用户登录 `/dashboard`。
    * 查看提案列表。
    * 点击 [批准] -> 系统执行拆分/清洗逻辑（写入 `vector_nodes`）。
    * 点击 [拒绝] -> 忽略。

### 5. 感知与体验升级

* **语音 (TTS)**:
    * 架构：后端生成器 -> 流式响应 -> 前端 `AudioContext`。
    * 体验：**Wake Lock API** 保证播放时不息屏。
* **PWA**:
    * **Service Worker**: 缓存 App Shell (UI)，实现断网可打开。
    * 策略：API 优先网络，UI 资源优先缓存。
* **反馈闭环**:
    * UI: 消息气泡旁 [👎] 按钮。
    * Data: 写入 `bad_cases.json` -> 触发 Router 回归测试。

### 6. 路由逻辑 (Router 3.0)

* **思维链 (CoT)**: 强制 AI 输出 `thought_process` (<50 字) 再给结论。
* **犹豫机制**:
    * 置信度 0.4~0.7 -> 返回 `intent: ambiguous` (模糊)。
    * 动作 -> 前端显示反问句，不强行检索。

### 7. UI 结构计划

* `/` (聊天): 极简聊天流，侧边栏抽屉预览文件（分屏视图），流式语音。
* `/dashboard` (管理):
    * **KPI**: 知识总量、向量库健康度。
    * **表格**: 提案审批 (Proposals)。
    * **用户隔离**: 普通用户只能看自己的数据/提案。

### 8. 2025-12-13 RAG 升级纪元 (v0.7.0)
*   **父子索引**: 实现 `300-500` token 切片。子节点实现精确召回，聚合回父档案以提供上下文。
*   **本地重排序**: 集成 `BGE-M3` (CrossEncoder) 优化 Top-K 结果。
*   **重置**: 系统于 2025-12-13 进行了硬重置（截断数据库）以清除旧向量。
