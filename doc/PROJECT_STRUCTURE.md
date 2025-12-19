# Memex 项目文件树结构

```
Memex/
├── .ai/                           # AI Agent 协作目录
│   └── AI_MAP.md                  # 📍 架构真相源 (Source of Truth)
│
├── src/                           # 🔥 核心源代码
│   ├── main.py                    # FastAPI 应用入口 + Lifespan管理
│   │
│   ├── api/                       # API 端点层 (15 个模块)
│   │   ├── chat.py               # 💬 对话核心接口
│   │   ├── endpoints.py          # Archive CRUD 接口
│   │   ├── storage_endpoints.py  # 📁 文件浏览器 & 物理删除
│   │   ├── prompts.py            # Prompt Laboratory 接口
│   │   ├── auth_endpoints.py     # 用户认证
│   │   ├── config_endpoints.py   # 系统配置管理
│   │   ├── cron_endpoints.py     # 定时任务管理
│   │   ├── dashboard_endpoints.py # 仪表盘数据
│   │   └── ...
│   │
│   ├── core/                      # 核心基础设施 (15 个模块)
│   │   ├── database.py           # 数据库连接池 (PostgreSQL)
│   │   ├── auth.py               # JWT 认证逻辑
│   │   ├── events.py             # 🔔 事件总线 (解耦通信)
│   │   ├── plugins.py            # 🧩 插件系统管理器
│   │   ├── prompt_manager.py     # PromptOps 动态管理
│   │   ├── config_manager.py     # 系统配置管理
│   │   ├── migration_manager.py  # 数据库迁移管理
│   │   └── ...
│   │
│   ├── models/                    # 数据模型层 (9 个模型)
│   │   ├── archive.py            # 📦 Archive (Parent Document)
│   │   ├── vector_node.py        # 🔍 VectorNode (Child Chunks)
│   │   ├── user.py               # 用户模型
│   │   ├── chat.py               # 对话历史模型
│   │   ├── prompt_config.py      # Prompt 配置模型
│   │   ├── ai_config.py          # AI 模型配置
│   │   └── ...
│   │
│   ├── services/                  # 业务逻辑层 (24 个服务)
│   │   ├── ai/                   # AI 服务提供者
│   │   │   ├── openai_provider.py       # OpenAI 兼容协议 (含 o1 Thinking)
│   │   │   ├── dashscope_provider.py    # 阿里通义千问 (多模态)
│   │   │   ├── rerank_provider.py       # BGE-M3 重排序 (ONNX/PyTorch)
│   │   │   └── base_provider.py         # AI Provider 抽象基类
│   │   │
│   │   ├── agents/               # Agent 智能体
│   │   │   ├── router_agent.py          # 🧠 Neural Router (意图识别)
│   │   │   └── retrieval_agent.py       # 🔎 混合检索 + Parent-Child聚合
│   │   │
│   │   ├── ai_service.py         # 🎯 AI 模型池 (Failover)
│   │   ├── chat_distiller.py     # 📊 Chat Distiller (Nightly Reports)
│   │   ├── distillation.py       # Nightly 蒸馏任务
│   │   ├── context_memory.py     # 🧠 Memory Service (Rolling Summary)
│   │   ├── export_service.py     # 📤 批量导出融合服务
│   │   ├── nightly_jobs.py       # ⏰ 定时任务调度器
│   │   └── ...
│   │
│   ├── plugins/                   # 插件系统 (5 个插件)
│   │   ├── gardener_plugin.py    # 🌱 Gardener Agent (语义切分 + 精炼)
│   │   ├── core_archiver.py      # 📂 文件归档 + 语义重命名
│   │   ├── core_vectorizer.py    # 🔢 向量化服务 (Metadata注入)
│   │   └── audio_io_plugin.py    # 🎙️ 音频处理插件
│   │
│   └── utils/                     # 工具库
│       └── text_tools.py         # RecursiveCharacterTextSplitter
│
├── web/                           # 前端资源
│   ├── index.html                # 主应用界面 (Vue3)
│   ├── dashboard.html            # 管理仪表盘
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── app.js                # Vue3 主应用 (双视图模式)
│   │   ├── audio_manager.js      # 录音 & 播放管理
│   │   └── dashboard.js          # 仪表盘逻辑
│   ├── logo.svg
│   ├── manifest.json             # PWA 配置
│   └── sw_v2.js                  # Service Worker (离线支持)
│
├── scripts/                       # 运维脚本 (30 个脚本)
│   ├── init_database.py          # ✅ 数据库初始化 (必需)
│   ├── create_default_user.py    # ✅ 创建默认管理员
│   ├── export_onnx.py            # ✅ 导出 ONNX 模型
│   ├── batch_reprocess_images.py # ✅ 批量重新处理图片
│   ├── migrate_*.sql/py          # ⚠️ 历史迁移脚本 (可选清理)
│   ├── fix_*.py                  # ⚠️ 一次性修复脚本 (可选清理)
│   ├── recover_database.*        # 🛟 灾备恢复脚本
│   └── router_cases.json         # 路由测试用例
│
├── migrations/                    # Alembic 迁移 (如需要)
│   └── 001_initial.sql
│
├── doc/                           # 📚 文档目录
│   ├── PROMPT_CATALOG_CN.md      # Prompt 目录
│   └── PROJECT_STRUCTURE.md      # ✅ 项目文件树结构
│
├── debug/                         # 🔧 调试工具 (已 gitignore)
│   ├── debug_db.py               # 数据库调试
│   ├── fetch_prompts.py          # Prompt 提取
│   └── tmp_update_prompts.py     # 🗑️ 临时脚本 (可删除)
│
├── data/                          # 数据存储目录 (已 gitignore)
│   ├── admin/                    # 用户文件存储
│   ├── logs/                     # 日志文件
│   └── memex.db                  # SQLite (开发用)
│
├── docker-compose.yml            # 🐳 Docker 编排配置
├── docker-compose.nas.yml        # 🏠 NAS 部署配置 (gitignore)
├── Dockerfile                    # Docker 镜像构建
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 排除规则
├── manage_release.py             # 发布管理脚本
└── README.md                     # 项目说明文档
```

## 关键目录说明

### 🔥 核心业务逻辑
- **`src/services/`**: 承载所有业务逻辑，包括 AI 服务、Agent、检索、蒸馏等
- **`src/plugins/`**: 插件化设计，Gardener、Archiver、Vectorizer 均为插件
- **`src/api/`**: RESTful API 端点，FastAPI 路由层

### 🧠 AI 核心
- **`src/services/ai/`**: 多 Provider 架构 (OpenAI, DashScope, Rerank)
- **`src/services/agents/`**: Router Agent (意图识别) + Retrieval Agent (混合检索)

### 📊 数据层
- **`src/models/`**: SQLAlchemy ORM 模型，核心是 `archive.py` (Parent) + `vector_node.py` (Child)

### 🛠️ 运维工具
- **`scripts/`**: 数据库初始化、迁移、维护脚本
- **`debug/`**: 开发调试工具 (不会进入生产)

## 统计数据
- **Python 模块总数**: ~60+
- **API 端点模块**: 15
- **核心服务**: 24
- **数据模型**: 9
- **运维脚本**: 30
