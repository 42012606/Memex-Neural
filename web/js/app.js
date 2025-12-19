const { createApp, ref, reactive, nextTick, computed, onMounted, watch } = Vue;

createApp({
    setup() {
        // --- 认证状态 ---
        const token = ref(localStorage.getItem('memex_token') || '');
        const isAuthenticated = computed(() => !!token.value);
        const showLogin = ref(!isAuthenticated.value);
        const loginError = ref('');
        const loginForm = ref({
            username: '',
            password: ''
        });
        const isLoggingIn = ref(false);

        // --- 用户管理状态 ---
        const currentUser = ref(null); // 当前登录用户信息
        const isAdmin = computed(() => currentUser.value?.id === 1); // 管理员判断（ID为1）
        const users = ref([]); // 用户列表（管理员可见）
        const userPanel = ref('profile'); // 用户管理面板：'profile' 个人资料, 'users' 用户管理（管理员）
        const newUserForm = ref({ username: '', password: '', email: '' });
        const editingUser = ref(null);
        const passwordForm = ref({ old_password: '', new_password: '', confirm_password: '' });
        const isChangingPassword = ref(false);

        // --- State ---
        const messages = ref([]);
        const inputVal = ref("");
        const currentModel = ref(null); // Default to null (System Config)
        const systemLogs = ref([]);
        const currentView = ref('chat');
        const isThinking = ref(false);
        const chatBox = ref(null);
        const logBox = ref(null); // [新增] 日志容器引用

        // [新增] 会话管理状态
        const sessions = ref([]);
        const sessionMenu = ref({ visible: false, x: 0, y: 0, sessionId: null, sessionTitle: null });
        const toggleSessionMenu = (session, event) => {
            if (event) event.stopPropagation();
            if (sessionMenu.value.visible && sessionMenu.value.sessionId === session.id) {
                closeSessionMenu();
                return;
            }
            const rect = event.currentTarget.getBoundingClientRect();
            // User requested "Put on right". Align left edge of menu to slightly left of button right edge?
            // Or align left edge of menu to left edge of button (expanding right).
            // "Why back to left" -> They want body on right.
            sessionMenu.value = {
                visible: true,
                x: rect.right - 10, // Align closer to the right, possibly popping out
                y: rect.bottom + 5,
                sessionId: session.id,
                sessionTitle: session.title
            };
        };
        const closeSessionMenu = () => {
            sessionMenu.value.visible = false;
            sessionMenu.value.sessionId = null;
        };
        // [修复] 从 localStorage 恢复 session_id，或生成新的 UUID
        const initializeSessionId = () => {
            const stored = localStorage.getItem('memex_session_id');
            if (stored) {
                console.log("📦 从 localStorage 恢复 Session ID:", stored);
                return stored;
            }
            // 生成新的 UUID v4
            const newId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            console.log("🆕 生成新 Session ID:", newId);
            localStorage.setItem('memex_session_id', newId);
            return newId;
        };
        const currentSessionId = ref(initializeSessionId());

        // UI Control
        const isSidebarCollapsed = ref(false);
        const isMobileMenuOpen = ref(false);
        const isConfigSidebarOpen = ref(false); // [新增]
        // [修复] 初始加载状态：如果有 Session ID，默认为 Loading，避免闪烁 Jarvis 界面
        const isChatLoading = ref(!!localStorage.getItem('memex_session_id'));
        const showModelSelector = ref(false); // [新增] 模型选择器显示状态

        // [新增] Voice Recording UI State (WeChat-style) 
        // Note: isRecording is declared below at line ~1966 with the recording logic
        const isVoiceMode = ref(false);           // 是否处于语音输入模式（按住说话）
        const recordingDuration = ref(0);         // 录音时长（秒）
        const voiceSendCancelled = ref(false);    // 是否取消发送（上滑取消）
        const isProcessingVoice = ref(false);     // 是否正在处理语音（发送到后端）



        // [新增] Feedback State
        const showFeedbackModal = ref(false);
        const feedbackType = ref('intent_wrong_search');
        const feedbackComment = ref('');
        const currentFeedbackMsg = ref(null);

        // [新增] Toast State
        const toast = ref({ show: false, message: '', type: 'info' });
        const showToast = (message, type = 'info') => {
            toast.value = { show: true, message, type };
            setTimeout(() => {
                toast.value.show = false;
            }, 3000);
        };

        // [新增] Long Text Modal State
        const longTextModal = ref({ show: false, content: '' });
        const showLongTextModal = (text) => {
            longTextModal.value.content = text;
            longTextModal.value.show = true;
        };

        // [新增] 配置页面面板状态 (侧边栏导航)
        const configPanel = ref('dashboard'); // 默认显示 Dashboard

        // [新增] 可折叠分组状态 (Gemini-style)
        const expandedGroups = ref({
            data: true,      // 📊 数据管理 - 默认展开
            models: false,   // 🤖 模型池
            system: false    // ⚙️ 系统
        });
        const toggleGroup = (group) => {
            expandedGroups.value[group] = !expandedGroups.value[group];
        };

        // [新增] Dashboard 统计数据
        const dashboardStats = ref({
            summary: { total_archives: 0, vector_coverage: 0, pending_proposals: 0 }
        });
        const dashboardProposals = ref([]);
        const isDashboardLoading = ref(false);

        // [新增] Audio Config State (TTS)

        const audioConfig = ref({
            tts_provider: 'dashscope',
            tts_model: 'sambert-zhichu-v1',
            tts_api_key: ''
        });

        // [动态获取] 可用模型列表
        const availableModels = ref([]);

        // [新增] 获取模型列表
        const fetchModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/models');
                if (res.data.status === 'ok') {
                    availableModels.value = res.data.models;
                    // 如果当前没选模型，且列表不为空，默认选第一个
                    if (!currentModel.value && availableModels.value.length > 0) {
                        currentModel.value = availableModels.value[0].value;
                    }
                }
            } catch (e) {
                console.error("获取模型列表失败:", e);
                // Fallback (保留一个默认选项以防万一)
                availableModels.value = [{
                    value: null, name: "Default", description: "Backend Default", icon: "settings", iconColor: "text-gray-400"
                }];
            }
        };


        // --- Configuration State (Schema-Driven) ---
        const dynamicConfigGroups = ref([]); // Stores the schema definitions

        // [New] System Control Group IDs to separate them from main sidebar
        const systemControlGroupIds = ['system', 'nightly', 'router_tuning', 'batch_ops', 'notifications'];

        const systemControlGroups = computed(() => {
            return dynamicConfigGroups.value.filter(g => systemControlGroupIds.includes(g.id));
        });

        const sidebarConfigGroups = computed(() => {
            return dynamicConfigGroups.value.filter(g => !systemControlGroupIds.includes(g.id));
        });
        const configValues = ref({}); // Stores the actual values (nested objects)
        const showPasswords = ref({}); // Toggles for password visibility
        const routerModels = ref([]);
        const reasoningModels = ref([]);
        const visionModels = ref([]); // [新增] 视觉模型列表
        const voiceModels = ref([]); // [新增] 语音模型列表 (TTS)
        const hearingModels = ref([]); // [新增] 听觉模型列表 (STT)
        const memoryConfig = ref({ provider: "dashscope", model_id: "", api_key: "" }); // [修改] 记忆配置改为API配置
        const newRouterModel = ref({ // [新增] Router 模型表单
            name: "",
            provider: "gemini",
            model_id: "",
            api_key: "",
            base_url: "",
        });
        const newReasoningModel = ref({
            name: "",
            provider: "gemini",
            model_id: "",
            api_key: "",
            base_url: "",
        });
        const newVisionModel = ref({ // [新增] 视觉模型表单
            name: "",
            provider: "dashscope",
            model_id: "",
            api_key: "",
        });
        const newVoiceModel = ref({ // [新增] 语音模型表单
            name: "",
            provider: "dashscope",
            model_id: "",
            api_key: "",
            config: { voice_id: "longxiaochun" }
        });
        const newHearingModel = ref({ // [新增] 听觉模型表单
            name: "",
            provider: "dashscope",
            model_id: "",
            api_key: "",
        });
        const memoryModels = ref([]); // [新增] 记忆模型列表（改为模型池）
        const isConfigLoading = ref(false);
        const configSaveStatus = ref("");

        // [新增] 卡片编辑状态
        const editingRouterModel = ref(null);
        const editingReasoningModel = ref(null);
        const editingVisionModel = ref(null);
        const editingVoiceModel = ref(null);
        const editingHearingModel = ref(null);
        const editingMemoryModel = ref(null);

        // [新增] 拖拽状态
        const draggedIndex = ref(null);

        // [新增] 清空数据相关状态
        const clearDataConfirm = ref(false);
        const isClearingData = ref(false);

        // [新增] 批量导入相关状态
        const batchSelectedFiles = ref([]);
        const batchRateLimit = ref(0.5);
        const isBatchImporting = ref(false);
        const batchTaskId = ref(null);
        const batchProgress = ref({
            total: 0,
            processed: 0,
            succeeded: 0,
            failed: 0,
            current_file: null
        });
        let batchStatusInterval = null;

        // [新增] 批量向量化相关状态
        const isVectorizing = ref(false);
        const vectorizeTaskId = ref(null);
        const vectorizeProgress = ref({
            total: 0,
            progress: 0,
            success_count: 0,
            failed_count: 0,
            status: 'pending'
        });
        let vectorizeStatusInterval = null;

        // [新增] 向量服务测试相关状态
        const isTestingVector = ref(false);



        const vectorTestResult = ref(null);

        // [新增] 模型连接测试状态
        // 存储每个模型的测试状态: { [modelId]: 'loading' | 'success' | 'error' }
        const testingModels = reactive({});

        const batchOpsTab = ref('archive'); // 'archive', 'vector', 'combined'
        const autoVectorizeAfterImport = ref(false);
        // [新增] 数据库管理状态
        // [新增] 数据库管理状态
        const dbTables = ref([]);
        const sqlQuery = ref("");
        const queryResult = ref(null);
        const queryError = ref("");
        const isExecutingQuery = ref(false);

        // [New] Database Table Scroll Sync
        const topScroll = ref(null);
        const tableContainer = ref(null);
        const dataTable = ref(null);
        const tableWidth = ref(0);

        const syncScroll = (source) => {
            if (!topScroll.value || !tableContainer.value) return;
            if (source === 'top') {
                tableContainer.value.scrollLeft = topScroll.value.scrollLeft;
            } else {
                topScroll.value.scrollLeft = tableContainer.value.scrollLeft;
            }
        };

        const updateTableDimensions = () => {
            if (dataTable.value) {
                tableWidth.value = dataTable.value.scrollWidth;
            }
        };

        watch(queryResult, () => {
            nextTick(updateTableDimensions);
        });

        // [新增] PromptOps State
        const prompts = ref([]);
        const editingPrompt = ref(null); // { key, content, group, description }
        const isPromptLoading = ref(false);

        // [New] Knowledge Base (Archives) State - Physical File Browser
        const archives = ref([]);
        const isArchiveLoading = ref(false);
        const selectedArchive = ref(null);
        const isDrawerOpen = ref(false); // Side Drawer toggle

        // [New] Physical File Browser State
        const userStorageLocations = ref([]); // User's folders across all storage roots
        const currentBrowseRoot = ref(null); // Current storage root being browsed
        const currentBrowsePath = ref(''); // Current path (relative to root)
        const fileListItems = ref([]); // Current directory contents
        const isFileListLoading = ref(false);
        const selectedFiles = ref(new Set()); // Multi-select file set
        const fileSortBy = ref('name'); // Sort column: name, modified, size
        const fileSortAsc = ref(true); // Sort direction

        // [新增] Storage Management State
        const storageRoots = ref([]);
        const showStorageModal = ref(false);
        const isSubmittingStorage = ref(false);
        const storageForm = ref({ name: "", mount_path: "", is_default: false });

        // [新增] Folder Browser State (for storage root selection modal)
        const showFolderBrowser = ref(false);
        const currentBrowsePath_old = ref('/'); // Rename to avoid conflict
        const browserItems = ref([]);
        const isBrowsingLoading = ref(false);



        const viewTitle = computed(() => {
            const titles = {
                'chat': 'Memex Pro',
                'config': '高级设置',
                'user': '用户管理'
            };
            return titles[currentView.value] || 'Memex Pro';
        });

        // [新增] 获取模型显示名称
        const getModelDisplayName = (modelId) => {
            if (!modelId) {
                // 如果是 null，显示第一个可用模型的名字，或者 "System Default"
                if (availableModels.value.length > 0) {
                    return availableModels.value[0].name;
                }
                return "System Default";
            }
            const model = availableModels.value.find(m => m.value === modelId);
            return model ? model.name : modelId;
        };

        // [新增] 获取当前会话标题
        const getCurrentSessionTitle = () => {
            if (!currentSessionId.value) return '对话模式';
            const session = sessions.value.find(s => s.id === currentSessionId.value);
            return session ? session.title : '对话模式';
        };

        // [新增] 切换会话
        const switchSession = async (sessionId) => {
            console.log("🔄 切换会话，Session ID:", sessionId);
            // close menu
            closeSessionMenu();

            // 如果当前在高级设置页面，切换回聊天视图
            if (currentView.value !== 'chat') {
                currentView.value = 'chat';
            }
            // 即使 sessionId 相同，也重新加载历史记录（解决刷新后无响应问题）
            currentSessionId.value = sessionId;
            localStorage.setItem('memex_session_id', sessionId); // [修复] 持久化切换的会话 ID

            // 确保侧边栏状态正确 (Desktop: 保持当前状态, Mobile: 关闭)
            if (window.innerWidth < 768) {
                isMobileMenuOpen.value = false;
            }

            await fetchChatHistory(sessionId);
        };

        // [NEW] Haptic Feedback Helper
        const vibrate = (pattern = 10) => {
            if (navigator.vibrate) navigator.vibrate(pattern);
        };

        // [新增] 切换配置面板并自动关闭移动端侧边栏
        const switchConfigPanel = (panel) => {
            configPanel.value = panel;
            isConfigSidebarOpen.value = false; // Auto close on mobile
        };

        // [新增] 点击隐藏键盘 (模拟原生体验)
        const hideKeyboard = () => {
            // 只有当当前焦点在 input 或 textarea 时才执行 blur
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
                document.activeElement.blur();
            }
        };

        // --- Core Methods ---
        const toggleSidebar = () => {
            isSidebarCollapsed.value = !isSidebarCollapsed.value;
        };

        const toggleConfigSidebar = () => {
            isConfigSidebarOpen.value = !isConfigSidebarOpen.value;
        };

        const switchView = (view) => {
            vibrate(5); // Light tap
            currentView.value = view;
            isMobileMenuOpen.value = false;
            if (view === 'config') {
                fetchConfig();
                configPanel.value = 'dashboard';
                // 如果切换到日志面板，自动滚动到底部
                if (configPanel.value === 'logs') {
                    nextTick(() => {
                        if (logBox.value) {
                            logBox.value.scrollTop = logBox.value.scrollHeight;
                        }
                    });
                    fetchLogs();
                }
            } else if (view === 'user') {
                fetchCurrentUser();
                if (isAdmin.value) {
                    fetchUsers();
                }
                userPanel.value = 'profile'; // 默认显示个人资料
                editingUser.value = null; // 重置编辑状态
                isChangingPassword.value = false; // 重置密码修改状态
            }
        };

        // 获取配置
        const fetchConfig = async () => {
            isConfigLoading.value = true;
            try {
                // 1. Fetch Dynamic Schema & Values (New System)
                await fetchConfigSchema();
                await fetchConfigValues();

                // 2. Fetch Legacy Model Pools
                await fetchRouterModels();
                await fetchReasoningModels();
                await fetchVisionModels();
                await fetchVoiceModels();
                await fetchHearingModels();
                await fetchMemoryModels();
            } catch (e) {
                console.error("获取配置失败:", e);
            } finally {
                isConfigLoading.value = false;
            }
        };

        // --- Schema-Driven Config Methods ---
        const fetchConfigSchema = async () => {
            try {
                const res = await axios.get('/api/v1/config/schema');
                if (res.data.status === 'ok') {
                    dynamicConfigGroups.value = res.data.schema;
                }
            } catch (e) {
                console.error("Failed to fetch config schema:", e);
            }
        };

        const fetchConfigValues = async () => {
            try {
                const res = await axios.get('/api/v1/config/values');
                if (res.data.status === 'ok') {
                    configValues.value = res.data.values;
                }
            } catch (e) {
                console.error("Failed to fetch config values:", e);
            }
        };

        // Helper: Access value by dot-notation key (e.g. "system.debug_mode")
        const getConfigValue = (dotKey) => {
            if (!dotKey) return undefined;
            const parts = dotKey.split('.');
            let current = configValues.value;
            for (const part of parts) {
                if (current === undefined || current === null) return undefined;
                current = current[part];
            }
            return current;
        };

        // Helper: Update local state (Optimistic UI)
        // Also saves to backend if needed (Debouncing recommended for text inputs, strictly calling save API for toggles)
        const updateConfigValue = (dotKey, newValue) => {
            if (!dotKey) return;
            const parts = dotKey.split('.');

            // 1. Update Local State Deeply
            let current = configValues.value;
            for (let i = 0; i < parts.length - 1; i++) {
                const part = parts[i];
                if (!current[part]) current[part] = {};
                current = current[part];
            }
            const lastPart = parts[parts.length - 1];

            // Handle type conversion if necessary
            // For boolean toggles, it's already boolean. For inputs, it might be string.
            // We rely on the schema to know what it should be, but here we just store what we get.
            // For 'number' inputs, HTML input returns string, so simple conversion:
            // (We could check schema but let's do a simple check)

            // Check schema for type
            let fieldType = 'string';
            for (const group of dynamicConfigGroups.value) {
                const field = group.fields.find(f => f.key === dotKey);
                if (field) {
                    fieldType = field.type;
                    break;
                }
            }

            if (fieldType === 'number') {
                newValue = Number(newValue);
            } else if (fieldType === 'boolean') {
                newValue = Boolean(newValue);
            }

            current[lastPart] = newValue;

            // 2. Auto-save for Toggles Immediately
            if (fieldType === 'boolean' || fieldType === 'select') {
                saveConfigValueDebounced(dotKey, newValue);
            } else {
                // For text inputs using v-model / @input, we might wait for explicit "Save All" or debounce
                // But let's create a debounced saver
                saveConfigValueDebounced(dotKey, newValue);
            }
        };

        // Debounce storage
        let saveTimers = {};
        const saveConfigValueDebounced = (key, value) => {
            if (saveTimers[key]) clearTimeout(saveTimers[key]);
            saveTimers[key] = setTimeout(() => {
                saveSingleConfig(key, value);
                delete saveTimers[key];
            }, 500); // 500ms delay
        };

        const saveSingleConfig = async (key, value) => {
            try {
                // Construct the partial update object
                // The API accepts {"system": {"debug": true}} OR {"system.debug": true}
                // To support dot notation, we can just send { [key]: value } if the backend supports it.
                // Our backend implementation supports flattened keys.

                configSaveStatus.value = "saving";
                const payload = { values: { [key]: value } };

                const res = await axios.post('/api/v1/config/values', payload);
                if (res.data.status === 'ok') {
                    configSaveStatus.value = "success";
                    setTimeout(() => configSaveStatus.value = "", 2000);
                }
            } catch (e) {
                console.error("Save failed:", e);
                configSaveStatus.value = "error";
            }
        };

        const togglePasswordVisibility = (key) => {
            showPasswords.value[key] = !showPasswords.value[key];
        };

        const testWebhook = async (url) => {
            if (!url) {
                alert("请先填写 Webhook URL");
                return;
            }
            try {
                const res = await axios.post('/api/v1/config/test-webhook', { webhook_url: url });
                if (res.data.status === 'ok') {
                    alert(`测试成功!\nHTTP Status: ${res.data.webhook_status}\nResponse: ${res.data.response_text}`);
                } else {
                    alert(`测试失败:\n${res.data.message}`);
                }
            } catch (e) {
                alert("测试请求失败: " + e.message);
            }
        };

        // [新增] 获取面板标题
        const getPanelTitle = (panel) => {
            // Check dynamic groups first
            const dynamicGroup = dynamicConfigGroups.value.find(g => g.id === panel);
            if (dynamicGroup) return dynamicGroup.title;

            const titles = {
                'dashboard': '看板统计',
                'router': '路由模型池',
                'reasoning': '推理模型池',
                'vision': '视觉模型池',
                'voice': '语音模型池',
                'hearing': '听觉模型池',
                'memory': '记忆模型池',
                'storage': '存储管理',
                'batch-ops': '批量作业',
                'batch-archive': '批量归档',
                'batch-vector': '批量向量',
                'logs': '系统日志',
                'database': '数据库',
                'prompts': '提示词实验室',
                'archives': '知识库 (Archives)'
            };
            return titles[panel] || '高级设置';
        };

        // [新增] Dashboard Methods
        const fetchDashboardStats = async () => {
            isDashboardLoading.value = true;
            try {
                const res = await axios.get('/api/v1/dashboard/stats');
                dashboardStats.value = res.data;
            } catch (e) {
                console.error("Fetch Dashboard Stats Failed:", e);
            } finally {
                isDashboardLoading.value = false;
            }
        };

        const fetchDashboardProposals = async () => {
            try {
                const res = await axios.get('/api/v1/dashboard/proposals');
                dashboardProposals.value = res.data || [];
            } catch (e) {
                console.error("Fetch Proposals Failed:", e);
            }
        };

        const approveProposal = async (id) => {
            if (!confirm("确定要批准此提案吗？")) return;
            try {
                await axios.post(`/api/v1/proposals/${id}/approve`);
                dashboardProposals.value = dashboardProposals.value.filter(p => p.id !== id);
                await fetchDashboardStats();
                showToast("提案已批准", "success");
            } catch (e) {
                console.error("Approve failed:", e);
                showToast("批准失败: " + (e.response?.data?.detail || e.message), "error");
            }
        };

        const rejectProposal = async (id) => {
            if (!confirm("确定要拒绝此提案吗？")) return;
            try {
                await axios.post(`/api/v1/proposals/${id}/reject`);
                dashboardProposals.value = dashboardProposals.value.filter(p => p.id !== id);
                await fetchDashboardStats();
                showToast("提案已拒绝", "success");
            } catch (e) {
                console.error("Reject failed:", e);
                showToast("拒绝失败: " + (e.response?.data?.detail || e.message), "error");
            }
        };

        // [New] Knowledge Base Methods
        const fetchArchives = async () => {

            isArchiveLoading.value = true;
            try {
                // Using the new endpoints
                const res = await axios.get('/api/v1/archives?limit=100');
                archives.value = res.data || [];
            } catch (e) {
                console.error("Fetch Archives Failed:", e);
                showToast("获取归档列表失败", "error");
            } finally {
                isArchiveLoading.value = false;
            }
        };

        const openArchiveDrawer = async (archive) => {
            // 1. Initial render with available data (optimistic UI)
            let initialData = {};
            let archiveId = null;

            if (archive.archive_info) {
                // Handle FileBrowserItem with nested archive_info
                archiveId = archive.archive_info.id;
                initialData = {
                    id: archiveId,
                    filename: archive.name,
                    status: archive.archive_info.processing_status,
                    summary: archive.archive_info.summary,
                    file_type: archive.archive_info.file_type,
                    category: archive.archive_info.category,
                    full_text: archive.archive_info.full_text, // might be partial
                    created_at: new Date(archive.modified * 1000).toISOString()
                };
            } else if (archive.id || archive.filename) {
                // Standard ArchiveRecord
                archiveId = archive.id;
                initialData = archive;
            } else {
                // Unarchived file
                selectedArchive.value = {
                    filename: archive.name,
                    status: 'Not Archived',
                    summary: 'This file has not been archived/vectorized yet.',
                    file_type: 'Unknown',
                    created_at: new Date(archive.modified * 1000).toISOString()
                };
                isDrawerOpen.value = true;
                return;
            }

            selectedArchive.value = initialData;
            isDrawerOpen.value = true;

            // 2. Fetch complete details from DB to get full_text
            if (archiveId) {
                try {
                    const res = await axios.get(`/api/v1/archives/${archiveId}`);
                    // Merge/Update with fresh data
                    selectedArchive.value = {
                        ...selectedArchive.value,
                        ...res.data,
                        full_text: res.data.full_text || res.data.meta_data?.ocr_text || ''
                    };
                } catch (e) {
                    console.error("Failed to fetch archive details:", e);
                    // Don't show toast to avoid spamming if just looking
                }
            }
        };

        const closeArchiveDrawer = () => {
            isDrawerOpen.value = false;
            setTimeout(() => {
                selectedArchive.value = null;
            }, 300); // clear after animation
        };

        const deleteArchive = async (id) => {
            if (!confirm("确定要删除此归档记录吗？文件和向量数据也将被删除。")) return;
            try {
                await axios.delete(`/api/v1/archives/${id}`);
                showToast("归档记录已删除", "success");
                if (selectedArchive.value && selectedArchive.value.id === id) {
                    closeArchiveDrawer();
                }
                await fetchArchives();
                // Refresh current directory if browsing
                if (currentBrowseRoot.value && currentBrowsePath.value) {
                    await browseDirectory(currentBrowseRoot.value, currentBrowsePath.value);
                }
            } catch (e) {
                console.error("Delete Archive Failed:", e);
                showToast(e.response?.data?.detail || "删除失败", "error");
            }
        };

        // [New] Physical File Browser Methods
        const fetchUserStorageLocations = async () => {
            try {
                const roots = storageRoots.value;
                if (!roots || roots.length === 0) {
                    await fetchStorageRoots();
                }

                const username = currentUser.value?.username || '';
                if (!username) {
                    console.error('No current user');
                    return [];
                }

                const locations = [];
                for (const root of storageRoots.value) {
                    // Build user path: {mount_path}/{username}
                    let userPath = root.mount_path;
                    if (!userPath.endsWith('/')) userPath += '/';
                    userPath += username;

                    locations.push({
                        rootId: root.id,
                        rootName: root.name,
                        path: userPath,
                        mountPath: root.mount_path,
                        isDefault: root.is_default
                    });
                }

                userStorageLocations.value = locations;
                return locations;
            } catch (e) {
                console.error('Failed to fetch user storage locations:', e);
                return [];
            }
        };

        const browseDirectory = async (rootName, path) => {
            isFileListLoading.value = true;
            try {
                const res = await axios.get(`/api/v1/storage/browse?path=${encodeURIComponent(path)}`);
                fileListItems.value = res.data || [];
                currentBrowseRoot.value = rootName;
                currentBrowsePath.value = path;
                selectedFiles.value.clear(); // Clear selection when changing directory
            } catch (e) {
                console.error('Browse Directory Failed:', e);
                showToast(e.response?.data?.detail || '无法浏览此目录', 'error');
            } finally {
                isFileListLoading.value = false;
            }
        };

        const browseIntoFolder = (item) => {
            if (!item.is_dir) return;
            let newPath = currentBrowsePath.value;
            if (!newPath.endsWith('/')) newPath += '/';
            newPath += item.name;
            browseDirectory(currentBrowseRoot.value, newPath);
        };

        const navigateToStorageRoot = (location) => {
            browseDirectory(location.rootName, location.path);
        };

        const navigateUp = () => {
            if (!currentBrowsePath.value) return;
            const parts = currentBrowsePath.value.split('/').filter(p => p);
            if (parts.length > 0) {
                parts.pop();
                const parentPath = '/' + parts.join('/');
                browseDirectory(currentBrowseRoot.value, parentPath || '/');
            }
        };

        const navigateToBreadcrumb = (index) => {
            if (!currentBrowsePath.value) return;
            const parts = currentBrowsePath.value.split('/').filter(p => p);
            if (index === -1) {
                // Navigate to root
                const location = userStorageLocations.value.find(l => l.rootName === currentBrowseRoot.value);
                if (location) {
                    navigateToStorageRoot(location);
                }
            } else {
                const newParts = parts.slice(0, index + 1);
                const newPath = '/' + newParts.join('/');
                browseDirectory(currentBrowseRoot.value, newPath);
            }
        };

        // Multi-select operations
        const toggleFileSelection = (item) => {
            if (item.is_dir) return; // Don't select folders
            const key = item.name;
            if (selectedFiles.value.has(key)) {
                selectedFiles.value.delete(key);
            } else {
                selectedFiles.value.add(key);
            }
        };

        const toggleSelectAll = (checked) => {
            if (checked) {
                fileListItems.value.forEach(item => {
                    if (!item.is_dir) {
                        selectedFiles.value.add(item.name);
                    }
                });
            } else {
                selectedFiles.value.clear();
            }
        };

        // Batch delete
        const batchDeleteFiles = async () => {
            const toDeleteNames = Array.from(selectedFiles.value);
            if (toDeleteNames.length === 0) return;
            if (!confirm(`确定删除 ${toDeleteNames.length} 个文件吗？`)) return;

            let success = 0;
            let fail = 0;

            for (const name of toDeleteNames) {
                // Find item in fileListItems
                const item = fileListItems.value.find(i => i.name === name);
                if (!item) continue;

                try {
                    if (item.archive_info && item.archive_info.id) {
                        await axios.delete(`/api/v1/archives/${item.archive_info.id}`);
                    } else {
                        // Use path from item
                        await axios.delete(`/api/v1/storage/files?path=${encodeURIComponent(item.path)}`);
                    }
                    success++;
                } catch (e) {
                    console.error(`Failed to delete ${name}:`, e);
                    fail++;
                }
            }
            selectedFiles.value.clear();
            showToast(`删除完成: ${success} 成功, ${fail} 失败`, fail > 0 ? "warning" : "success");
            await browseDirectory(currentBrowseRoot.value, currentBrowsePath.value);
        };



        const handleFileDelete = async (item) => {
            if (!confirm(`确定要删除 ${item.name} 吗？`)) return;

            try {
                if (item.archive_info && item.archive_info.id) {
                    // Delete via Archive API
                    await axios.delete(`/api/v1/archives/${item.archive_info.id}`);
                } else {
                    // Delete physical file only
                    await axios.delete(`/api/v1/storage/files?path=${encodeURIComponent(item.path)}`);
                }
                showToast("文件已删除", "success");
                // Refresh
                await browseDirectory(currentBrowseRoot.value, currentBrowsePath.value);
            } catch (e) {
                console.error("Delete failed:", e);
                showToast("删除失败: " + (e.response?.data?.detail || e.message), "error");
            }
        };

        const handleFolderDelete = async (item) => {
            if (!confirm(`确定要删除文件夹 "${item.name}" 吗？\n\n⚠️ 注意：文件夹内所有内容将被永久删除！`)) return;

            try {
                await axios.delete(`/api/v1/storage/folders?path=${encodeURIComponent(item.path)}`);
                showToast("文件夹已删除", "success");
                await browseDirectory(currentBrowseRoot.value, currentBrowsePath.value);
            } catch (e) {
                console.error("Delete folder failed:", e);
                showToast("删除失败: " + (e.response?.data?.detail || e.message), "error");
            }
        };

        // Sorting
        const sortFileList = (column) => {
            if (fileSortBy.value === column) {
                fileSortAsc.value = !fileSortAsc.value;
            } else {
                fileSortBy.value = column;
                fileSortAsc.value = true;
            }

            fileListItems.value.sort((a, b) => {
                // Folders always first
                if (a.is_dir !== b.is_dir) {
                    return a.is_dir ? -1 : 1;
                }

                let compareValue = 0;
                switch (column) {
                    case 'name':
                        compareValue = a.name.localeCompare(b.name);
                        break;
                    case 'modified':
                        compareValue = (a.modified || 0) - (b.modified || 0);
                        break;
                    case 'size':
                        compareValue = (a.size || 0) - (b.size || 0);
                        break;
                }

                return fileSortAsc.value ? compareValue : -compareValue;
            });
        };

        // Helper computed properties
        const pathParts = computed(() => {
            if (!currentBrowsePath.value) return [];
            return currentBrowsePath.value.split('/').filter(p => p);
        });

        // [新增] Storage Management Functions
        const fetchStorageRoots = async () => {
            try {
                const res = await axios.get('/api/v1/storage/roots');
                storageRoots.value = res.data || [];
            } catch (e) {
                console.error("Fetch Storage Roots Failed:", e);
                showToast("获取存储库列表失败", "error");
            }
        };

        const openAddStorageModal = () => {
            storageForm.value = { name: "", mount_path: "", is_default: false };
            showStorageModal.value = true;
        };

        const closeStorageModal = () => {
            showStorageModal.value = false;
            showFolderBrowser.value = false;
        };

        const createStorageRoot = async () => {
            if (!storageForm.value.name || !storageForm.value.mount_path) {
                showToast("请填写名称和挂载路径", "error");
                return;
            }
            isSubmittingStorage.value = true;
            try {
                const res = await axios.post('/api/v1/storage/roots', storageForm.value);
                if (res.data.status === 'ok') {
                    showToast("存储库添加成功", "success");
                    closeStorageModal();
                    await fetchStorageRoots();
                }
            } catch (e) {
                console.error("Create Storage Root Failed:", e);
                showToast(e.response?.data?.detail || "添加存储库失败", "error");
            } finally {
                isSubmittingStorage.value = false;
            }
        };

        const deleteStorageRoot = async (rootId) => {
            if (!confirm("确定要删除此存储库吗？")) return;
            try {
                const res = await axios.delete(`/api/v1/storage/roots/${rootId}`);
                if (res.data.status === 'ok') {
                    showToast("存储库已移除", "success");
                    await fetchStorageRoots();
                }
            } catch (e) {
                console.error("Delete Storage Root Failed:", e);
                showToast(e.response?.data?.detail || "删除存储库失败", "error");
            }
        };

        const setDefaultStorageRoot = async (rootId) => {
            try {
                const res = await axios.patch(`/api/v1/storage/roots/${rootId}/default`);
                if (res.data.status === 'ok') {
                    showToast("默认存储库已更新", "success");
                    await fetchStorageRoots();
                }
            } catch (e) {
                console.error("Set Default Root Failed:", e);
                showToast(e.response?.data?.detail || "设置默认存储库失败", "error");
            }
        };

        // [新增] Folder Browser Functions
        const openFolderBrowser = () => {
            currentBrowsePath.value = '/';
            showFolderBrowser.value = true;
            fetchDirectoryListing('/');
        };

        const fetchDirectoryListing = async (path) => {
            isBrowsingLoading.value = true;
            try {
                const res = await axios.get(`/api/v1/storage/browse?path=${encodeURIComponent(path)}`);
                browserItems.value = res.data;
                currentBrowsePath.value = path;
            } catch (e) {
                console.error("Browse Directory Failed:", e);
                showToast(e.response?.data?.detail || "无法浏览此目录", "error");
            } finally {
                isBrowsingLoading.value = false;
            }
        };

        const browseTo = (path) => {
            fetchDirectoryListing(path);
        };

        const browseUp = () => {
            // Navigate to parent directory
            const parts = currentBrowsePath.value.split('/').filter(p => p);
            if (parts.length > 0) {
                parts.pop();
                const parentPath = '/' + parts.join('/');
                fetchDirectoryListing(parentPath || '/');
            }
        };

        const selectCurrentFolder = () => {
            storageForm.value.mount_path = currentBrowsePath.value;
            showFolderBrowser.value = false;
        };

        // [新增] Vision模型管理
        const fetchVisionModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/vision');
                if (res.data.status === 'ok') {
                    visionModels.value = res.data.models || [];
                }
            } catch (e) {
                console.error("获取Vision模型列表失败:", e);
            }
        };

        const addVisionModel = async () => {
            if (!newVisionModel.value.name || !newVisionModel.value.model_id || !newVisionModel.value.api_key) return;

            try {
                const payload = {
                    ...newVisionModel.value,
                    priority: visionModels.value.length
                };
                const res = await axios.post('/api/v1/config/vision', payload);
                if (res.data.status === 'ok') {
                    alert("视觉模型添加成功！");
                    newVisionModel.value = {
                        name: "",
                        provider: "dashscope",
                        model_id: "",
                        api_key: "",
                    };
                    await fetchVisionModels();
                }
            } catch (e) {
                console.error("添加Vision模型失败:", e);
                alert("添加Vision模型失败: " + (e.response?.data?.detail || e.message));
            }
        };

        // 视觉模型卡片编辑方法
        const editVisionModelCard = (model) => {
            if (editingVisionModel.value?.id === model.id) {
                cancelEditVisionModel();
            } else {
                editingVisionModel.value = { ...model };
            }
        };

        const addNewVisionModelCard = () => {
            editingVisionModel.value = {
                id: null,
                name: "",
                provider: "dashscope",
                model_id: "",
                api_key: "",
            };
        };

        const saveVisionModelCard = async () => {
            if (!editingVisionModel.value.name || !editingVisionModel.value.model_id || !editingVisionModel.value.api_key) {
                alert("请填写名称、Model ID和API Key");
                return;
            }

            try {
                const payload = { ...editingVisionModel.value };
                delete payload.id;

                if (editingVisionModel.value.id) {
                    const res = await axios.put(`/api/v1/config/vision/${editingVisionModel.value.id}`, payload);
                    if (res.data.status === 'ok') {
                        await fetchVisionModels();
                        editingVisionModel.value = null;
                    }
                } else {
                    const res = await axios.post('/api/v1/config/vision', payload);
                    if (res.data.status === 'ok') {
                        await fetchVisionModels();
                        editingVisionModel.value = null;
                    }
                }
            } catch (e) {
                console.error("保存视觉模型失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const cancelEditVisionModel = () => {
            editingVisionModel.value = null;
        };

        const onVisionDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onVisionDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;
            const item = visionModels.value.splice(draggedIndex.value, 1)[0];
            visionModels.value.splice(dropIndex, 0, item);
            draggedIndex.value = null;
            // TODO: 实现视觉模型优先级更新API
        };

        const editVisionModel = (model) => {
            editVisionModelCard(model);
        };

        const deleteVisionModel = async (modelId) => {
            if (!confirm("确定要删除此视觉模型吗？")) return;

            try {
                const res = await axios.delete(`/api/v1/config/vision/${modelId}`);
                if (res.data.status === 'ok') {
                    await fetchVisionModels();
                }
            } catch (e) {
                console.error("删除Vision模型失败:", e);
                alert("删除Vision模型失败: " + e.message);
            }
        };

        // [新增] Audio模型管理
        // [新增] Voice模型管理
        const fetchVoiceModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/voice');
                if (res.data.status === 'ok') {
                    voiceModels.value = res.data.models || [];
                }
            } catch (e) {
                console.error("获取Voice模型列表失败:", e);
            }
        };

        const addVoiceModel = async () => {
            if (!newVoiceModel.value.name || !newVoiceModel.value.model_id || !newVoiceModel.value.api_key) return;

            try {
                const payload = {
                    ...newVoiceModel.value,
                    priority: voiceModels.value.length
                };
                const res = await axios.post('/api/v1/config/voice', payload);
                if (res.data.status === 'ok') {
                    alert("语音模型添加成功！");
                    newVoiceModel.value = {
                        name: "",
                        provider: "dashscope",
                        model_id: "",
                        api_key: "",
                    };
                    await fetchVoiceModels();
                }
            } catch (e) {
                console.error("添加Voice模型失败:", e);
                alert("添加Voice模型失败: " + (e.response?.data?.detail || e.message));
            }
        };

        // 语音模型卡片编辑方法
        const editVoiceModelCard = (model) => {
            if (editingVoiceModel.value?.id === model.id) {
                cancelEditVoiceModel();
            } else {
                editingVoiceModel.value = { ...model };
            }
        };

        const addNewVoiceModelCard = () => {
            editingVoiceModel.value = {
                id: null,
                name: "",
                provider: "dashscope",
                model_id: "",
                api_key: "",
            };
        };

        const saveVoiceModelCard = async () => {
            if (!editingVoiceModel.value.name || !editingVoiceModel.value.model_id || !editingVoiceModel.value.api_key) {
                alert("请填写名称、Model ID和API Key");
                return;
            }

            try {
                const payload = { ...editingVoiceModel.value };
                delete payload.id;

                if (editingVoiceModel.value.id) {
                    const res = await axios.put(`/api/v1/config/voice/${editingVoiceModel.value.id}`, payload);
                    if (res.data.status === 'ok') {
                        await fetchVoiceModels();
                        editingVoiceModel.value = null;
                    }
                } else {
                    const res = await axios.post('/api/v1/config/voice', payload);
                    if (res.data.status === 'ok') {
                        await fetchVoiceModels();
                        editingVoiceModel.value = null;
                    }
                }
            } catch (e) {
                console.error("保存语音模型失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const cancelEditVoiceModel = () => {
            editingVoiceModel.value = null;
        };

        const onVoiceDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onVoiceDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;

            const item = voiceModels.value.splice(draggedIndex.value, 1)[0];
            voiceModels.value.splice(dropIndex, 0, item);

            const models = voiceModels.value.map((m, idx) => ({
                id: m.id,
                priority: idx
            }));

            try {
                const res = await axios.put('/api/v1/config/voice/reorder', { models });
                if (res.data.status === 'ok') {
                    await fetchVoiceModels();
                }
            } catch (e) {
                console.error("更新Voice优先级失败:", e);
                alert("更新优先级失败: " + e.message);
                await fetchVoiceModels(); // Revert on failure
            }
            draggedIndex.value = null;
        };

        const editVoiceModel = (model) => {
            editVoiceModelCard(model);
        };

        const deleteVoiceModel = async (modelId) => {
            if (!confirm("确定要删除此语音模型吗？")) return;

            try {
                const res = await axios.delete(`/api/v1/config/voice/${modelId}`);
                if (res.data.status === 'ok') {
                    await fetchVoiceModels();
                }
            } catch (e) {
                console.error("删除Voice模型失败:", e);
                alert("删除Voice模型失败: " + e.message);
            }
        };

        // [新增] Hearing (STT) 模型管理
        const fetchHearingModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/hearing');
                if (res.data.status === 'ok') {
                    hearingModels.value = res.data.models || [];
                }
            } catch (e) {
                console.error("获取Hearing模型列表失败:", e);
            }
        };

        const addHearingModel = async () => {
            if (!newHearingModel.value.name || !newHearingModel.value.model_id || !newHearingModel.value.api_key) return;

            try {
                const payload = {
                    ...newHearingModel.value,
                    priority: hearingModels.value.length
                };
                const res = await axios.post('/api/v1/config/hearing', payload);
                if (res.data.status === 'ok') {
                    alert("听觉模型添加成功！");
                    newHearingModel.value = {
                        name: "",
                        provider: "dashscope",
                        model_id: "",
                        api_key: "",
                    };
                    await fetchHearingModels();
                }
            } catch (e) {
                console.error("添加Hearing模型失败:", e);
                alert("添加Hearing模型失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const editHearingModelCard = (model) => {
            if (editingHearingModel.value?.id === model.id) {
                cancelEditHearingModel();
            } else {
                editingHearingModel.value = { ...model };
            }
        };

        const addNewHearingModelCard = () => {
            editingHearingModel.value = {
                id: null,
                name: "",
                provider: "dashscope",
                model_id: "",
                api_key: "",
            };
        };

        const saveHearingModelCard = async () => {
            if (!editingHearingModel.value.name || !editingHearingModel.value.model_id || !editingHearingModel.value.api_key) {
                alert("请填写名称、Model ID和API Key");
                return;
            }

            try {
                const payload = { ...editingHearingModel.value };
                delete payload.id;

                if (editingHearingModel.value.id) {
                    // Update
                    const res = await axios.put(`/api/v1/config/hearing/${editingHearingModel.value.id}`, payload);
                    if (res.data.status === 'ok') {
                        await fetchHearingModels();
                        editingHearingModel.value = null;
                    }
                } else {
                    // Add
                    const res = await axios.post('/api/v1/config/hearing', payload);
                    if (res.data.status === 'ok') {
                        await fetchHearingModels();
                        editingHearingModel.value = null;
                    }
                }
            } catch (e) {
                console.error("保存Hearing模型失败:", e);
                alert("保存失败: " + e.message);
            }
        };

        // --- PromptOps Methods ---
        const fetchPrompts = async () => {
            isPromptLoading.value = true;
            try {
                const res = await axios.get('/api/prompts');
                prompts.value = res.data || [];
            } catch (e) {
                console.error("Fetch Prompts Failed:", e);
                showToast("无法加载提示词列表", "error");
            } finally {
                isPromptLoading.value = false;
            }
        };

        const editPrompt = (prompt) => {
            if (!prompt) return;
            // Deep copy to avoid mutating list directly
            editingPrompt.value = JSON.parse(JSON.stringify(prompt));
        };

        const createPrompt = () => {
            editingPrompt.value = {
                key: "",
                group: "custom",
                role: "",
                content: "",
                description: ""
            };
        };

        const cancelEditPrompt = () => {
            editingPrompt.value = null;
        };

        const savePrompt = async () => {
            if (!editingPrompt.value?.key || !editingPrompt.value?.content) {
                alert("Key and Content are required!");
                return;
            }
            try {
                const res = await axios.post(`/api/prompts/${editingPrompt.value.key}`, {
                    content: editingPrompt.value.content,
                    group: editingPrompt.value.group,
                    role: editingPrompt.value.role,
                    description: editingPrompt.value.description
                });
                // Update local list
                const idx = prompts.value.findIndex(p => p.key === res.data.key);
                if (idx !== -1) {
                    prompts.value[idx] = res.data;
                } else {
                    prompts.value.push(res.data);
                }
                editingPrompt.value = null;
                showToast("提示词已保存 & 热更新生效", "success");
            } catch (e) {
                console.error("Save Prompt Failed:", e);
                alert("保存失败: " + e.message);
            }
        };

        const refreshPromptCache = async () => {
            try {
                await axios.post('/api/prompts/system/refresh');
                showToast("系统缓存已刷新", "success");
                await fetchPrompts();
            } catch (e) {
                showToast("刷新失败", "error");
            }
        };

        // Group prompts by 'group' field
        const groupedPrompts = computed(() => {
            const groups = {};
            prompts.value.forEach(p => {
                if (!p || !p.group) return;
                if (!groups[p.group]) groups[p.group] = [];
                groups[p.group].push(p);
            });
            return groups;
        });

        const cancelEditHearingModel = () => {
            editingHearingModel.value = null;
        };

        const onHearingDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onHearingDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;

            const item = hearingModels.value.splice(draggedIndex.value, 1)[0];
            hearingModels.value.splice(dropIndex, 0, item);

            const models = hearingModels.value.map((m, idx) => ({
                id: m.id,
                priority: idx
            }));

            try {
                await axios.put('/api/v1/config/hearing/reorder', { models });
                await fetchHearingModels();
            } catch (e) {
                console.error("更新Hearing优先级失败:", e);
                await fetchHearingModels(); // Revert on failure
            }
            draggedIndex.value = null;
        };

        const editHearingModel = (model) => {
            editHearingModelCard(model);
        };

        const deleteHearingModel = async (modelId) => {
            if (!confirm("确定要删除此听觉模型吗？")) return;

            try {
                const res = await axios.delete(`/api/v1/config/hearing/${modelId}`);
                if (res.data.status === 'ok') {
                    await fetchHearingModels();
                }
            } catch (e) {
                console.error("删除Hearing模型失败:", e);
                alert("删除Hearing模型失败: " + e.message);
            }
        };

        // [修改] Memory模型池管理（改为模型池）
        const fetchMemoryModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/memory');
                if (res.data.status === 'ok' && res.data.config) {
                    // 将单个配置转换为模型列表格式
                    if (res.data.config.id) {
                        memoryModels.value = [{
                            id: res.data.config.id,
                            name: "Embedding Model",
                            provider: res.data.config.provider || "dashscope",
                            model_id: res.data.config.model_id || "",
                            api_key: res.data.config.api_key || ""
                        }];
                    } else {
                        memoryModels.value = [];
                    }
                }
            } catch (e) {
                console.error("获取Memory模型列表失败:", e);
            }
        };

        // 记忆模型卡片编辑方法
        const editMemoryModelCard = (model) => {
            if (editingMemoryModel.value?.id === model.id) {
                cancelEditMemoryModel();
            } else {
                editingMemoryModel.value = { ...model };
            }
        };

        const addNewMemoryModelCard = () => {
            editingMemoryModel.value = {
                id: null,
                name: "Embedding Model",
                provider: "dashscope",
                model_id: "",
                api_key: "",
            };
        };

        const saveMemoryModelCard = async () => {
            if (!editingMemoryModel.value.model_id || !editingMemoryModel.value.api_key) {
                alert("请填写Model ID和API Key");
                return;
            }

            try {
                const payload = {
                    provider: editingMemoryModel.value.provider,
                    model_id: editingMemoryModel.value.model_id,
                    api_key: editingMemoryModel.value.api_key
                };

                const res = await axios.put('/api/v1/config/memory', payload);
                if (res.data.status === 'ok') {
                    await fetchMemoryModels();
                    editingMemoryModel.value = null;
                }
            } catch (e) {
                console.error("保存记忆模型失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const cancelEditMemoryModel = () => {
            editingMemoryModel.value = null;
        };

        const deleteMemoryModel = async (modelId) => {
            if (!confirm("确定要删除此记忆模型吗？")) return;
            // Memory模型通常只有一个，删除后清空配置
            try {
                const res = await axios.put('/api/v1/config/memory', {
                    provider: "dashscope",
                    model_id: "",
                    api_key: ""
                });
                if (res.data.status === 'ok') {
                    await fetchMemoryModels();
                }
            } catch (e) {
                console.error("删除记忆模型失败:", e);
                alert("删除失败: " + e.message);
            }
        };

        const onMemoryDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onMemoryDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;
            const item = memoryModels.value.splice(draggedIndex.value, 1)[0];
            memoryModels.value.splice(dropIndex, 0, item);
            draggedIndex.value = null;
            // TODO: 实现记忆模型优先级更新API
        };

        // [保留兼容] Memory配置管理
        const fetchMemoryConfig = async () => {
            await fetchMemoryModels();
        };

        const saveMemoryConfig = async () => {
            if (memoryModels.value.length > 0) {
                const model = memoryModels.value[0];
                editingMemoryModel.value = { ...model };
                await saveMemoryModelCard();
            }
        };

        // [修改] Router 模型列表管理（类似 Reasoning）
        const fetchRouterModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/router');
                if (res.data.status === 'ok') {
                    routerModels.value = res.data.models || [];
                }
            } catch (e) {
                console.error("获取Router模型列表失败:", e);
            }
        };

        const addRouterModel = async () => {
            if (!newRouterModel.value.name || !newRouterModel.value.model_id) return;

            try {
                const payload = {
                    ...newRouterModel.value,
                    priority: routerModels.value.length
                };
                const res = await axios.post('/api/v1/config/router', payload);
                if (res.data.status === 'ok') {
                    alert("Router模型添加成功！");
                    newRouterModel.value = {
                        name: "",
                        provider: "gemini",
                        model_id: "",
                        api_key: "",
                        base_url: "",
                    };
                    await fetchRouterModels();
                }
            } catch (e) {
                console.error("添加Router模型失败:", e);
                alert("添加Router模型失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const editRouterModel = (model) => {
            newRouterModel.value = {
                name: model.name,
                provider: model.provider,
                model_id: model.model_id,
                api_key: model.api_key || "",
                base_url: model.base_url || "",
            };
            deleteRouterModel(model.id);
        };

        const deleteRouterModel = async (modelId) => {
            if (!confirm("确定要删除此Router模型吗？")) return;

            try {
                const res = await axios.delete(`/api/v1/config/router/${modelId}`);
                if (res.data.status === 'ok') {
                    await fetchRouterModels();
                }
            } catch (e) {
                console.error("删除Router模型失败:", e);
                alert("删除Router模型失败: " + e.message);
            }
        };

        // Router 卡片编辑方法
        const editRouterModelCard = (model) => {
            if (editingRouterModel.value?.id === model.id) {
                cancelEditRouterModel();
            } else {
                // ✅ 反序列化 config JSONB 为可编辑的字符串
                editingRouterModel.value = {
                    ...model,
                    config_text: model.config ? JSON.stringify(model.config, null, 2) : '{}'
                };
            }
        };

        const addNewRouterModelCard = () => {
            editingRouterModel.value = {
                id: null,
                name: "",
                provider: "gemini",
                model_id: "",
                api_key: "",
                base_url: "",
                config_text: "{}",  // ✅ 初始化为空 JSON 对象
            };
        };

        const saveRouterModelCard = async () => {
            if (!editingRouterModel.value.name || !editingRouterModel.value.model_id) {
                alert("请填写名称和Model ID");
                return;
            }

            try {
                // ✅ 序列化 config_text 到 config 对象
                let configObject = {};
                if (editingRouterModel.value.config_text) {
                    try {
                        configObject = JSON.parse(editingRouterModel.value.config_text || '{}');
                    } catch (e) {
                        alert('Preset Config JSON 格式错误，请检查语法！');
                        return;
                    }
                }

                const payload = {
                    ...editingRouterModel.value,
                    config: configObject,  // ✅ 使用解析后的对象
                    priority: editingRouterModel.value.id ? routerModels.value.findIndex(m => m.id === editingRouterModel.value.id) : routerModels.value.length
                };
                delete payload.id; // 移除id，由后端处理
                delete payload.config_text; // ✅ 移除临时字段

                if (editingRouterModel.value.id) {
                    // 更新
                    const res = await axios.put(`/api/v1/config/router/${editingRouterModel.value.id}`, payload);
                    if (res.data.status === 'ok') {
                        await fetchRouterModels();
                        editingRouterModel.value = null;
                    }
                } else {
                    // 新增
                    const res = await axios.post('/api/v1/config/router', payload);
                    if (res.data.status === 'ok') {
                        await fetchRouterModels();
                        editingRouterModel.value = null;
                    }
                }
            } catch (e) {
                console.error("保存Router模型失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const cancelEditRouterModel = () => {
            editingRouterModel.value = null;
        };

        // Router 拖动排序
        const onRouterDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onRouterDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;

            const item = routerModels.value.splice(draggedIndex.value, 1)[0];
            routerModels.value.splice(dropIndex, 0, item);

            const models = routerModels.value.map((m, idx) => ({
                id: m.id,
                priority: idx
            }));

            try {
                const res = await axios.put('/api/v1/config/router/reorder', { models });
                if (res.data.status === 'ok') {
                    await fetchRouterModels();
                }
            } catch (e) {
                console.error("更新Router优先级失败:", e);
                alert("更新优先级失败: " + e.message);
                await fetchRouterModels();
            }
            draggedIndex.value = null;
        };

        // 获取推理模型列表
        const fetchReasoningModels = async () => {
            try {
                const res = await axios.get('/api/v1/config/reasoning');
                if (res.data.status === 'ok') {
                    reasoningModels.value = res.data.models || [];
                }
            } catch (e) {
                console.error("获取推理模型列表失败:", e);
            }
        };

        // 添加推理模型
        const addReasoningModel = async () => {
            if (!newReasoningModel.value.name || !newReasoningModel.value.model_id) return;

            try {
                const payload = {
                    ...newReasoningModel.value,
                    priority: reasoningModels.value.length // 默认追加到末尾，排序靠拖动调整
                };
                const res = await axios.post('/api/v1/config/reasoning', payload);
                if (res.data.status === 'ok') {
                    alert("模型添加成功！");
                    // 重置表单
                    newReasoningModel.value = {
                        name: "",
                        provider: "gemini",
                        model_id: "",
                        api_key: "",
                        base_url: "",
                    };
                    await fetchReasoningModels();
                    await fetchModels(); // 刷新聊天窗口的模型列表
                }
            } catch (e) {
                console.error("添加模型失败:", e);
                alert("添加模型失败: " + (e.response?.data?.detail || e.message));
            }
        };

        // 推理模型卡片编辑方法
        const editReasoningModelCard = (model) => {
            if (editingReasoningModel.value?.id === model.id) {
                cancelEditReasoningModel();
            } else {
                // ✅ 反序列化 config JSONB 为可编辑的字符串
                editingReasoningModel.value = {
                    ...model,
                    config_text: model.config ? JSON.stringify(model.config, null, 2) : '{}'
                };
            }
        };

        const addNewReasoningModelCard = () => {
            editingReasoningModel.value = {
                id: null,
                name: "",
                provider: "gemini",
                model_id: "",
                api_key: "",
                base_url: "",
                config_text: "{}",  // ✅ 初始化为空 JSON 对象
            };
        };

        const saveReasoningModelCard = async () => {
            if (!editingReasoningModel.value.name || !editingReasoningModel.value.model_id) {
                alert("请填写名称和Model ID");
                return;
            }

            try {
                // ✅ 序列化 config_text 到 config 对象
                let configObject = {};
                if (editingReasoningModel.value.config_text) {
                    try {
                        configObject = JSON.parse(editingReasoningModel.value.config_text || '{}');
                    } catch (e) {
                        alert('Preset Config JSON 格式错误，请检查语法！');
                        return;
                    }
                }

                const payload = {
                    ...editingReasoningModel.value,
                    config: configObject,  // ✅ 使用解析后的对象
                    priority: editingReasoningModel.value.id ? reasoningModels.value.findIndex(m => m.id === editingReasoningModel.value.id) : reasoningModels.value.length
                };
                delete payload.id;
                delete payload.config_text; // ✅ 移除临时字段

                if (editingReasoningModel.value.id) {
                    const res = await axios.put(`/api/v1/config/reasoning/${editingReasoningModel.value.id}`, payload);
                    if (res.data.status === 'ok') {
                        await fetchReasoningModels();
                        await fetchModels();
                        editingReasoningModel.value = null;
                    }
                } else {
                    const res = await axios.post('/api/v1/config/reasoning', payload);
                    if (res.data.status === 'ok') {
                        await fetchReasoningModels();
                        await fetchModels();
                        editingReasoningModel.value = null;
                    }
                }
            } catch (e) {
                console.error("保存推理模型失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const cancelEditReasoningModel = () => {
            editingReasoningModel.value = null;
        };

        // 编辑推理模型（保留兼容）
        const editReasoningModel = (model) => {
            editReasoningModelCard(model);
        };

        // 删除推理模型
        const deleteReasoningModel = async (modelId) => {
            if (!confirm("确定要删除此模型吗？")) return;

            try {
                const res = await axios.delete(`/api/v1/config/reasoning/${modelId}`);
                if (res.data.status === 'ok') {
                    await fetchReasoningModels();
                    await fetchModels();
                }
            } catch (e) {
                console.error("删除模型失败:", e);
                alert("删除模型失败: " + e.message);
            }
        };








        // 拖动排序（通用）
        const onDragStart = (index) => {
            draggedIndex.value = index;
        };

        const onDragOver = (index) => {
            // 允许放置
        };

        const onDrop = async (dropIndex) => {
            if (draggedIndex.value === null || draggedIndex.value === dropIndex) return;

            // 重新排序数组
            const item = reasoningModels.value.splice(draggedIndex.value, 1)[0];
            reasoningModels.value.splice(dropIndex, 0, item);

            // 更新优先级
            const models = reasoningModels.value.map((m, idx) => ({
                id: m.id,
                priority: idx
            }));

            try {
                const res = await axios.put('/api/v1/config/reasoning/reorder', { models });
                if (res.data.status === 'ok') {
                    await fetchReasoningModels();
                    await fetchModels();
                }
            } catch (e) {
                console.error("更新优先级失败:", e);
                alert("更新优先级失败: " + e.message);
                await fetchReasoningModels();
            }

            draggedIndex.value = null;
        };

        // 保存所有配置
        // 保存所有配置 (Dynamic + Legacy)
        const saveAllConfig = async () => {
            isConfigLoading.value = true;
            try {
                // 1. Save Dynamic Config
                const payload = { values: configValues.value };
                await axios.post('/api/v1/config/values', payload);

                // 2. Save Legacy Memory Config (if needed)
                if (memoryConfig.value && memoryConfig.value.model_id) {
                    await saveMemoryConfig();
                }

                configSaveStatus.value = "success";
                setTimeout(() => configSaveStatus.value = "", 2000);
                alert("所有配置保存成功！");
            } catch (e) {
                console.error("Failed to save all config:", e);
                configSaveStatus.value = "error";
                alert("保存失败: " + e.message);
            } finally {
                isConfigLoading.value = false;
            }
        };

        // [新增] 清空所有数据
        const clearAllData = async () => {
            if (!clearDataConfirm.value) {
                alert("请先确认要清空所有数据");
                return;
            }

            // 二次确认
            if (!confirm("⚠️ 警告：此操作将永久删除所有数据和文件，无法恢复！\n\n确定要继续吗？")) {
                return;
            }

            isClearingData.value = true;
            try {
                const res = await axios.delete('/api/v1/data/clear?confirm=true');
                if (res.data.status === 'ok') {
                    alert(`✅ ${res.data.message}\n\n${res.data.note || ''}`);
                    clearDataConfirm.value = false;
                    // 刷新页面或清空消息列表
                    messages.value = [];
                }
            } catch (e) {
                console.error("清空数据失败:", e);
                alert("清空数据失败: " + (e.response?.data?.detail || e.message));
            } finally {
                isClearingData.value = false;
            }
        };

        // [新增] 批量文件选择（自动识别音频或图片）
        const handleBatchFileSelect = (e) => {
            const files = Array.from(e.target.files);
            batchSelectedFiles.value = files.map(f => f.path || f.name);
        };

        // [新增] 获取文件类型图标和标签（自动识别音频或图片）
        const getFileTypeIcon = (filename) => {
            const ext = filename.split('.').pop()?.toLowerCase() || '';
            // 音频文件
            if (['mp3', 'm4a', 'wav', 'flac', 'aac', 'ogg', 'wma', 'opus'].includes(ext)) {
                return { icon: 'audiotrack', label: '音频', color: 'text-green-400' };
            }
            // 图片文件
            if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'heic', 'heif'].includes(ext)) {
                return { icon: 'image', label: '图片', color: 'text-blue-400' };
            }
            // 视频文件
            if (['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'].includes(ext)) {
                return { icon: 'videocam', label: '视频', color: 'text-purple-400' };
            }
            // 文档文件
            if (['pdf', 'txt', 'doc', 'docx', 'md', 'csv', 'xls', 'xlsx'].includes(ext)) {
                return { icon: 'description', label: '文档', color: 'text-yellow-400' };
            }
            // 默认
            return { icon: 'insert_drive_file', label: '其他', color: 'text-gray-400' };
        };

        // [新增] 开始批量导入
        const startBatchImport = async () => {
            if (batchSelectedFiles.value.length === 0) {
                alert("请先选择文件");
                return;
            }

            isBatchImporting.value = true;
            try {
                const res = await axios.post('/api/v1/batch/import', {
                    file_paths: batchSelectedFiles.value,
                    model_id: currentModel.value,
                    rate_limit: batchRateLimit.value
                });

                batchTaskId.value = res.data.task_id;
                batchProgress.value = {
                    total: res.data.total_files,
                    processed: 0,
                    succeeded: 0,
                    failed: 0,
                    current_file: null
                };

                // 开始轮询状态
                if (batchStatusInterval) clearInterval(batchStatusInterval);
                batchStatusInterval = setInterval(fetchBatchStatus, 1000);

            } catch (e) {
                console.error("批量导入失败:", e);
                alert("批量导入失败: " + (e.response?.data?.detail || e.message));
                isBatchImporting.value = false;
            }
        };

        // [新增] 停止批量导入 (Placeholder)
        const stopBatchImport = async () => {
            // TODO: Implement cancel API
            if (batchStatusInterval) {
                clearInterval(batchStatusInterval);
                batchStatusInterval = null;
            }
            isBatchImporting.value = false;
            alert("批量导入已停止");
        };

        // [新增] 获取批量导入状态
        const fetchBatchStatus = async () => {
            if (!batchTaskId.value) return;

            try {
                const res = await axios.get(`/api/v1/batch/status/${batchTaskId.value}`);
                batchProgress.value = {
                    total: res.data.total,
                    processed: res.data.processed,
                    succeeded: res.data.succeeded,
                    failed: res.data.failed,
                    current_file: res.data.current_file
                };

                if (res.data.status === 'completed') {
                    isBatchImporting.value = false;
                    if (batchStatusInterval) {
                        clearInterval(batchStatusInterval);
                        batchStatusInterval = null;
                    }
                    alert(`批量导入完成！成功: ${res.data.succeeded}, 失败: ${res.data.failed}`);

                    // [NEW] 自动触发向量化
                    if (autoVectorizeAfterImport.value) {
                        autoVectorizeAfterImport.value = false;
                        showToast("归档完成，即将开始向量化...", "info");
                        setTimeout(() => {
                            startBatchVectorize();
                        }, 1000);
                    }
                }
            } catch (e) {
                console.error("获取批量导入状态失败:", e);
            }
        };

        // [新增] 开始批量向量化
        const startBatchVectorize = async () => {
            if (isVectorizing.value) return;

            try {
                isVectorizing.value = true;
                const res = await axios.post('/api/v1/data/vectorize/batch', {
                    all_files: true
                });

                if (res.data.task_id) {
                    vectorizeTaskId.value = res.data.task_id;
                    vectorizeProgress.value = {
                        total: res.data.total,
                        progress: 0,
                        success_count: 0,
                        failed_count: 0,
                        status: 'processing'
                    };

                    // 开始轮询状态
                    vectorizeStatusInterval = setInterval(checkVectorizeStatus, 2000);
                }
            } catch (e) {
                console.error("批量向量化失败:", e);
                alert("批量向量化失败: " + (e.response?.data?.detail || e.message));
                isVectorizing.value = false;
            }
        };

        // [新增] 联合工作流：归档 + 向量化
        const startCombinedBatch = async () => {
            if (batchSelectedFiles.value.length === 0) {
                alert("请先选择文件");
                return;
            }
            autoVectorizeAfterImport.value = true;
            await startBatchImport();
        };

        // [新增] 检查向量化状态
        const checkVectorizeStatus = async () => {
            if (!vectorizeTaskId.value) return;

            try {
                const res = await axios.get(`/api/v1/data/vectorize/status/${vectorizeTaskId.value}`);
                vectorizeProgress.value = {
                    total: res.data.total || 0,
                    progress: res.data.progress || 0,
                    success_count: res.data.success_count || 0,
                    failed_count: res.data.failed_count || 0,
                    status: res.data.status || 'pending'
                };

                if (res.data.status === 'completed' || res.data.status === 'failed') {
                    isVectorizing.value = false;
                    if (vectorizeStatusInterval) {
                        clearInterval(vectorizeStatusInterval);
                        vectorizeStatusInterval = null;
                    }
                    if (res.data.status === 'completed') {
                        alert(`批量向量化完成！成功: ${res.data.success_count}, 失败: ${res.data.failed_count}`);
                    } else {
                        alert(`批量向量化失败: ${res.data.error || '未知错误'}`);
                    }
                }
            } catch (e) {
                console.error("获取向量化状态失败:", e);
            }
        };

        // [新增] 获取 Audio 配置
        const fetchAudioConfig = async () => {
            try {
                const res = await axios.get('/api/v1/config/audio');
                if (res.data.status === 'ok') {
                    audioConfig.value = { ...audioConfig.value, ...res.data.config };
                }
            } catch (e) {
                console.error("获取Audio配置失败:", e);
            }
        };

        // [新增] 保存 Audio 配置
        const saveAudioConfig = async () => {
            try {
                const res = await axios.put('/api/v1/config/audio', audioConfig.value);
                if (res.data.status === 'ok') {
                    alert("语音配置已保存");
                }
            } catch (e) {
                console.error("保存Audio配置失败:", e);
                alert("保存失败: " + (e.response?.data?.detail || e.message));
            }
        };

        // [新增] 测试向量服务
        const testVectorService = async () => {
            if (isTestingVector.value) return;

            try {
                isTestingVector.value = true;
                vectorTestResult.value = null;

                const res = await axios.post('/api/v1/config/retrieval/test');

                vectorTestResult.value = {
                    status: res.data.status,
                    message: res.data.message,
                    available: res.data.available,
                    vector_dimension: res.data.vector_dimension,
                    error: res.data.error
                };
            } catch (e) {
                console.error("测试向量服务失败:", e);
                vectorTestResult.value = {
                    status: 'error',
                    message: e.response?.data?.detail || e.message || '测试失败',
                    available: false
                };
            } finally {
                isTestingVector.value = false;
            }
        };

        // [新增] 模型连接测试方法
        const testModelConnection = async (model) => {
            if (!model || !model.id) return;

            // 设置为加载状态
            testingModels[model.id] = 'loading';

            try {
                // 构造请求体，类似 ConfigRequest
                const payload = {
                    name: model.name || "Test Model",
                    provider: model.provider,
                    model_id: model.model_id,
                    api_key: model.api_key,
                    base_url: model.base_url,
                    config: model.config
                };

                const res = await axios.post('/api/v1/config/test', payload);
                if (res.data.status === 'ok') {
                    testingModels[model.id] = 'success';
                    showToast(`Connection successful: ${model.model_id}`, 'success');
                } else {
                    testingModels[model.id] = 'error';
                    showToast(`Connection failed: ${res.data.message}`, 'error');
                }
            } catch (e) {
                console.error("Connection test failed:", e);
                testingModels[model.id] = 'error';
                showToast(`Connection test failed: ${e.response?.data?.detail || e.message}`, 'error');
            } finally {
                // 3秒后重置状态，以便下次点击
                setTimeout(() => {
                    if (testingModels[model.id]) {
                        delete testingModels[model.id];
                    }
                }, 3000);
            }
        };

        const getTestIconClass = (model) => {
            const status = testingModels[model.id];
            if (status === 'loading') return 'text-yellow-400 animate-spin';
            if (status === 'success') return 'text-green-400';
            if (status === 'error') return 'text-red-400';
            return 'text-gray-500 group-hover:text-gray-300';
        };

        // Voice Recording State
        const isRecording = ref(false);
        const mediaRecorder = ref(null);
        const audioChunks = ref([]);
        // isThinking is already declared above

        const toggleVoiceRecording = async () => {
            if (isRecording.value) {
                stopRecording();
            } else {
                startRecording();
            }
        };

        const startRecording = async () => {
            try {
                // [Mobile Compatibility] Check for secure context (HTTPS required for getUserMedia)
                if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
                    showToast("语音功能需要 HTTPS 安全连接", 'error');
                    console.error("getUserMedia requires HTTPS");
                    return;
                }

                // [Mobile Compatibility] Polyfill for older browsers (iOS Safari, old Android)
                if (!navigator.mediaDevices) {
                    navigator.mediaDevices = {};
                }

                if (!navigator.mediaDevices.getUserMedia) {
                    navigator.mediaDevices.getUserMedia = function (constraints) {
                        // Legacy getUserMedia for older browsers
                        const getUserMedia = navigator.webkitGetUserMedia ||
                            navigator.mozGetUserMedia ||
                            navigator.msGetUserMedia;

                        if (!getUserMedia) {
                            return Promise.reject(new Error('此浏览器不支持语音录制功能'));
                        }

                        return new Promise((resolve, reject) => {
                            getUserMedia.call(navigator, constraints, resolve, reject);
                        });
                    };
                }

                // Check if MediaRecorder is supported
                if (typeof MediaRecorder === 'undefined') {
                    showToast("此浏览器不支持录音功能，请使用 Chrome 或 Safari", 'error');
                    return;
                }

                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true
                    }
                });

                // Determine best MIME type for mobile compatibility
                let mimeType = 'audio/webm';
                if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                    mimeType = 'audio/webm;codecs=opus';
                } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
                    mimeType = 'audio/mp4'; // iOS Safari
                } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
                    mimeType = 'audio/ogg;codecs=opus';
                }
                console.log('🎤 Using MIME type:', mimeType);

                mediaRecorder.value = new MediaRecorder(stream, { mimeType });
                audioChunks.value = [];

                mediaRecorder.value.ondataavailable = (event) => {
                    if (event.data && event.data.size > 0) {
                        audioChunks.value.push(event.data);
                    }
                };

                mediaRecorder.value.onstop = sendVoiceMessage;

                mediaRecorder.value.start(100); // Collect chunks every 100ms
                isRecording.value = true;
                showToast("开始录音...", 'success');
            } catch (err) {
                console.error("Error accessing microphone:", err);

                // User-friendly error messages
                let errorMsg = "无法访问麦克风";
                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    errorMsg = "麦克风权限被拒绝，请在浏览器设置中允许访问";
                } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
                    errorMsg = "未检测到麦克风设备";
                } else if (err.name === 'NotSupportedError') {
                    errorMsg = "此浏览器不支持语音录制";
                } else if (err.name === 'SecurityError') {
                    errorMsg = "安全限制：请使用 HTTPS 访问";
                } else if (err.message) {
                    errorMsg = err.message;
                }

                showToast(errorMsg, 'error');
            }
        };

        const stopRecording = () => {
            if (mediaRecorder.value && mediaRecorder.value.state !== "inactive") {
                mediaRecorder.value.stop();
                isRecording.value = false;
            }
        };

        const sendVoiceMessage = async () => {
            if (!mediaRecorder.value) return;

            // Stop stream tracks
            if (mediaRecorder.value.stream) {
                mediaRecorder.value.stream.getTracks().forEach(track => track.stop());
            }

            const audioBlob = new Blob(audioChunks.value, { type: 'audio/wav' });
            if (audioBlob.size === 0) return;

            // Temp user message
            const tempUserMsg = {
                role: "user",
                content: "🎤 [语音输入处理中...]",
                type: "text",
                created_at: new Date().toISOString()
            };
            messages.value.push(tempUserMsg);
            isThinking.value = true;
            scrollToBottom();

            const formData = new FormData();
            formData.append("file", audioBlob, "recording.wav");

            try {
                // Determine Session ID
                let targetSessionId = currentSessionId.value;
                if (!targetSessionId) {
                    // Try to create new session first? Or let backend handle?
                    // Let's passed session_id if exists.
                }

                const res = await axios.post('/api/v1/chat/voice', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                    params: targetSessionId ? { session_id: targetSessionId } : {} // If backend supported param
                });

                // Remove temp message
                messages.value.pop();

                const data = res.data;

                // Update Session ID if new
                if (data.session_id && data.session_id !== currentSessionId.value) {
                    currentSessionId.value = parseInt(data.session_id);
                    localStorage.setItem('memex_session_id', currentSessionId.value);
                    await fetchSessions();
                }

                // Append User Text
                messages.value.push({
                    role: "user",
                    content: `🎤 ${data.user_text || '(无语音内容)'}`,
                    type: "text",
                    created_at: new Date().toISOString(),
                    model_id: "voice-input"
                });

                // Append AI Reply
                messages.value.push({
                    role: "assistant",
                    content: data.reply,
                    type: "text",
                    created_at: new Date().toISOString(),
                    model_id: data.model_id
                });

                // Check for follow-up
                if (data.user_text && data.user_text.toLowerCase().includes("bye")) {
                    // example logic
                }

                scrollToBottom();

                // Auto Play
                if (data.audio_data) {
                    playAudioBase64(data.audio_data);
                }

            } catch (e) {
                console.error("发送语音失败:", e);
                messages.value.pop();
                showToast("语音交互失败: " + (e.response?.data?.detail || e.message), 'error');
            } finally {
                isThinking.value = false;
                scrollToBottom();
            }
        };

        const playAudioBase64 = (base64Data) => {
            const audio = new Audio("data:audio/mp3;base64," + base64Data);
            audio.play().catch(e => console.error("Auto-play error:", e));
        };

        // [新增] 数据库工具方法
        const fetchDbTables = async () => {
            try {
                const res = await axios.get('/api/v1/system/db/tables');
                if (res.data.tables) {
                    dbTables.value = res.data.tables;
                }
            } catch (e) {
                console.error("Failed to fetch tables:", e);
                showToast("Failed to fetch tables: " + e.message, 'error');
            }
        };

        const executeSql = async () => {
            if (!sqlQuery.value.trim()) return;

            isExecutingQuery.value = true;
            queryError.value = "";
            queryResult.value = null;

            try {
                const res = await axios.post('/api/v1/system/db/query', { query: sqlQuery.value });
                if (res.data) {
                    queryResult.value = res.data;
                    if (res.data.message) {
                        showToast(res.data.message, 'success');
                    }
                }
            } catch (e) {
                console.error("SQL execution failed:", e);
                queryError.value = e.response?.data?.detail || e.message;
            } finally {
                isExecutingQuery.value = false;
            }
        };

        const selectAllFromTable = (table) => {
            sqlQuery.value = `SELECT * FROM ${table} LIMIT 100;`;
            executeSql();
        };

        // 监听面板切换，自动加载表
        watch(configPanel, (newVal) => {
            if (newVal === 'database') {
                fetchDbTables();
            }
        });


        // [新增] 获取会话列表
        // [新增] 获取会话列表
        const fetchSessions = async (silent = false) => {
            try {
                if (!silent) console.log("[DEBUG] Fetching sessions...");
                const res = await axios.get('/api/v1/sessions?limit=20');
                if (!silent) console.log("[DEBUG] Sessions received:", res.data);
                sessions.value = res.data;
            } catch (e) {
                // Prevent console spam on network errors
                const isNetworkError = e.code === "ERR_NETWORK" || e.code === "ERR_CONNECTION_RESET" || !e.response;
                if (!isNetworkError) {
                    console.error("[ERROR] 获取会话列表失败:", e);
                } else {
                    // console.warn("[Network] Connection unstable, retrying...");
                }
            }
        };

        // [新增] 创建新会话
        const createNewSession = async () => {
            try {
                const res = await axios.post('/api/v1/sessions');
                // 切换到新会话
                const newSessionId = res.data.id;
                console.log("🆕 创建新会话，Session ID:", newSessionId);
                currentSessionId.value = newSessionId;
                localStorage.setItem('memex_session_id', newSessionId); // [修复] 持久化新会话 ID
                messages.value = []; // 清空当前视图
                isMobileMenuOpen.value = false;
                await fetchSessions();
            } catch (e) {
                console.error("创建会话失败:", e);
                alert("创建新会话失败");
            }
        };



        // [新增] 删除会话
        const deleteSession = async (sessionId) => {
            if (!confirm("确定要删除此对话吗？")) return;
            try {
                await axios.delete(`/api/v1/sessions/${sessionId}`);
                await fetchSessions();
                // 如果删除的是当前会话，重置
                if (currentSessionId.value === sessionId) {
                    currentSessionId.value = null;
                    messages.value = [];
                }
            } catch (e) {
                console.error("删除会话失败:", e);
                alert("删除失败");
            }
        };

        // 返回首页空状态（Memex JARVIS）
        const goHome = () => {
            currentView.value = 'chat';
            currentSessionId.value = null;
            messages.value = [];
            localStorage.removeItem('memex_session_id');
            isMobileMenuOpen.value = false;
        };

        // [修改] 获取聊天记录 (支持 session_id)
        const fetchChatHistory = async (sessionId = null) => {
            isChatLoading.value = true;
            try {
                let url = '/api/v1/chat/history?limit=50';
                if (sessionId) url += `&session_id=${sessionId}`;

                const res = await axios.get(url);
                // 转换格式适配前端
                const history = res.data.map(msg => ({
                    role: msg.role,
                    type: 'text', // 目前数据库只存了文本
                    content: msg.content
                }));
                // [修复] 先清空消息列表，避免看到旧消息
                messages.value = [];
                // 等待 DOM 更新后再设置新消息，并直接滚动到底部（不使用平滑滚动）
                await nextTick();
                messages.value = history;

                // [修复] 强制滚动到底部 - 使用 double RAF 或 setTimeout 确保渲染完成
                const forceScroll = () => {
                    if (chatBox.value) {
                        // 临时禁用平滑滚动
                        chatBox.value.style.scrollBehavior = 'auto';
                        chatBox.value.scrollTop = chatBox.value.scrollHeight;
                        // 恢复平滑滚动
                        setTimeout(() => {
                            if (chatBox.value) {
                                chatBox.value.style.scrollBehavior = '';
                            }
                        }, 50);
                    }
                };

                await nextTick();
                forceScroll();
                // 再次尝试，确保图片等资源加载导致的高度变化被捕获
                setTimeout(forceScroll, 100);
                setTimeout(forceScroll, 300);

                // [NEW] 恢复未完成的上传任务
                loadPendingUploads();

            } catch (e) {
                console.error("获取聊天记录失败:", e);
                // showToast("获取聊天记录失败", "error"); // Optional: suppress if common
            } finally {
                isChatLoading.value = false;
            }
        };

        // [NEW] 保存未完成的上传任务到 localStorage
        const savePendingUploads = () => {
            const pending = messages.value.filter(m => m.type === 'file' && m.status !== 'Completed' && m.status !== 'Failed' && m.status !== 'Archived');
            // 只保存必要字段
            const toSave = pending.map(m => ({
                id: m.id, // Archive ID if available
                filename: m.filename,
                status: m.status,
                statusClass: m.statusClass,
                type: 'file',
                role: 'user',
                timestamp: Date.now()
            }));
            localStorage.setItem('memex_pending_uploads', JSON.stringify(toSave));
        };

        // [NEW] 从 localStorage 加载未完成的上传任务
        const loadPendingUploads = () => {
            try {
                const saved = localStorage.getItem('memex_pending_uploads');
                if (!saved) return;

                const pending = JSON.parse(saved);
                const now = Date.now();

                // 过滤掉超过 24 小时的旧任务
                const validPending = pending.filter(p => (now - p.timestamp) < 24 * 60 * 60 * 1000);

                if (validPending.length > 0) {
                    console.log("📥 恢复 pending uploads:", validPending.length);
                    // 避免重复添加 (通过 filename + status 简单去重，或者 ID)
                    validPending.forEach(p => {
                        const exists = messages.value.some(m => m.type === 'file' && m.filename === p.filename && m.status === p.status);
                        if (!exists) {
                            // 恢复消息对象
                            const msgObj = {
                                role: p.role,
                                type: p.type,
                                filename: p.filename,
                                status: p.status,
                                statusClass: p.statusClass,
                                id: p.id // 恢复 ID
                            };
                            messages.value.push(msgObj);

                            // 如果有 ID，重启轮询
                            if (p.id) {
                                // 找到新 push 进去的 index
                                const idx = messages.value.indexOf(msgObj);
                                startPollingArchive(p.id, idx);
                            }
                        }
                    });
                    scrollToBottom();
                }
            } catch (e) {
                console.error("加载 pending uploads 失败:", e);
                localStorage.removeItem('memex_pending_uploads');
            }
        };

        const sendText = async () => {
            vibrate(10); // Medium tap on send
            const text = inputVal.value.trim();
            if (!text) return;

            // [修复] 确保 session_id 存在，如果不存在则使用当前值（会在后端创建）
            console.log("💬 发送消息，当前 Session ID:", currentSessionId.value);

            messages.value.push({ role: 'user', type: 'text', content: text });
            inputVal.value = "";
            scrollToBottom();
            isThinking.value = true;
            try {
                const res = await axios.post('/api/v1/chat', {
                    query: text,
                    model_id: currentModel.value,
                    session_id: currentSessionId.value // [修复] 使用持久化的 session_id
                });

                // [修复] 如果后端返回了新的 session_id（首次创建时），更新并持久化
                if (res.data.session_id && res.data.session_id !== currentSessionId.value) {
                    console.log("🔄 后端返回新 Session ID，更新:", res.data.session_id);
                    currentSessionId.value = res.data.session_id;
                    localStorage.setItem('memex_session_id', res.data.session_id);
                }

                // [NEW] Simulated Streaming (Typewriter Effect)
                isThinking.value = false; // Stop thinking animation before typing

                // 1. Create a placeholder message
                messages.value.push({ role: 'assistant', type: 'text', content: '' });
                const msgIndex = messages.value.length - 1;

                // 2. Start typewriter effect
                await typeWriterEffect(msgIndex, res.data.reply);

                // 发送完消息后刷新会话列表 (更新时间)
                fetchSessions();
            } catch (e) {
                const detail = e?.response?.data?.detail || e?.message || "未知错误";
                messages.value.push({ role: 'assistant', type: 'text', content: `❌ 系统错误：无法获取回复\n\n${detail}` });
            } finally {
                isThinking.value = false;
                scrollToBottom();
            }
        };

        // [NEW] Typewriter Effect Helper
        const typeWriterEffect = async (index, fullText) => {
            if (!messages.value[index] || !fullText) return;

            const speed = 10; // ms per char
            let currentText = "";

            // Allow larger chunks for long text to keep it brisk
            const chunkSize = fullText.length > 500 ? 5 : 2;

            for (let i = 0; i < fullText.length; i += chunkSize) {
                // Check if user switched session or cleared messages
                if (!messages.value[index]) break;

                const chunk = fullText.slice(i, i + chunkSize);
                currentText += chunk;
                messages.value[index].content = currentText;

                await new Promise(r => setTimeout(r, speed));

                // Auto-scroll periodically
                if (i % 50 === 0) scrollToBottom();
            }

            // Ensure full text is set
            if (messages.value[index]) {
                messages.value[index].content = fullText;
                scrollToBottom();
            }
        };

        const handleEnter = (e) => {
            if (!e.shiftKey) sendText();
        };

        // 上传后简单轮询后台处理状态（兼容 202 Accepted）
        const archivePollers = {};

        const stopPolling = (id) => {
            if (archivePollers[id]) {
                clearInterval(archivePollers[id]);
                delete archivePollers[id];
            }
        };

        const startPollingArchive = (id, msgIdx) => {
            if (!id) return;
            let attempts = 0;
            const poll = async () => {
                attempts += 1;

                // [NEW] 重新定位 msgIdx (因为 messages 数组可能变动)
                // 通过 id 查找
                let currentMsgIdx = -1;
                const currentMsg = messages.value.find((m, index) => {
                    if (m.type === 'file' && m.id === id) {
                        currentMsgIdx = index;
                        return true;
                    }
                    return false;
                });

                if (!currentMsg) {
                    // 消息找不到了，停止轮询
                    stopPolling(id);
                    return;
                }

                try {
                    const res = await axios.get(`/api/v1/archives/${id}`, {
                        validateStatus: (s) => s < 500, // 容忍 404/202
                    });
                    const data = (res.data && typeof res.data === 'object') ? res.data : {};
                    const statusText = (data.processing_status || data.status || '').toLowerCase();
                    const errText = data.processing_error || data.error;

                    if (res.status === 200 && data && (statusText === 'completed' || !statusText)) {
                        currentMsg.status = 'Completed';
                        currentMsg.statusClass = 'text-green-400';

                        const summary = data.summary || '';
                        const cat = data.category || '';
                        const tags = data.meta_data?.semantic?.tags || data.tags || [];
                        if (summary || cat || tags.length) {
                            let reply = `${cat ? `**${cat}**` : '已归档'}`;
                            if (summary) reply += `\n\n${summary}`;
                            if (tags.length) reply += `\n\nTags: ${tags.join(', ')}`;
                            messages.value.push({ role: 'assistant', type: 'text', content: reply });
                        }
                        stopPolling(id);
                        savePendingUploads(); // [NEW] 更新状态 (会移除 completed)
                        scrollToBottom();
                        return;
                    }
                    if (res.status === 200 && statusText === 'failed') {
                        currentMsg.status = 'Failed';
                        currentMsg.statusClass = 'text-red-500';
                        if (errText) {
                            messages.value.push({ role: 'assistant', type: 'text', content: `⚠️ 归档失败：${errText}` });
                        }
                        stopPolling(id);
                        savePendingUploads(); // [NEW] 更新状态
                        scrollToBottom();
                        return;
                    }
                    if (res.status === 202) {
                        currentMsg.status = 'Processing...';
                        currentMsg.statusClass = 'text-yellow-400';
                        savePendingUploads(); // [NEW] 更新状态
                    }
                } catch (err) { }

                if (attempts >= 60) { // ~120s 后停止
                    currentMsg.status = 'Processing (background)';
                    currentMsg.statusClass = 'text-yellow-500';
                    stopPolling(id);
                    savePendingUploads();
                }
            };
            poll();
            archivePollers[id] = setInterval(poll, 2000);
        };

        const handleFileUpload = async (e) => {
            const files = e.target.files;
            if (!files.length) return;
            for (let file of files) {
                const msgIdx = messages.value.push({
                    role: 'user', type: 'file', filename: file.name,
                    status: 'Analyzing...', statusClass: 'text-yellow-500', confidence: null
                }) - 1;
                scrollToBottom();

                const formData = new FormData();
                formData.append('file', file);
                if (currentModel.value) {
                    formData.append('model_id', currentModel.value);
                }
                // [Persistence] Pass session_id to backend
                if (currentSessionId.value) {
                    formData.append('session_id', currentSessionId.value);
                }

                try {
                    const res = await axios.post('/api/v1/upload', formData, {
                        validateStatus: (s) => s < 500 // 接受 202/4xx 以便自定义处理
                    });
                    const data = (res.data && typeof res.data === 'object') ? res.data : {};

                    // 异步处理路径：202 Accepted 或 status/pending
                    if (res.status === 202 || data.status === 'pending' || data.status === 'processing') {
                        messages.value[msgIdx].status = 'Processing...';
                        messages.value[msgIdx].statusClass = 'text-yellow-400';
                        messages.value[msgIdx].id = data.id; // [NEW] 绑定 Archive ID

                        // [REMOVED] 不再添加临时消息，后端会在处理完成后保存真正的完成消息
                        if (data.id) startPollingArchive(data.id, msgIdx);

                        savePendingUploads(); // [NEW] 保存到 localStorage
                        scrollToBottom();
                    } else {
                        // 兼容旧同步返回
                        messages.value[msgIdx].status = 'Archived';
                        messages.value[msgIdx].statusClass = 'text-green-400';
                        messages.value[msgIdx].confidence = data.confidence;
                        const summary = data.summary;
                        const category = data.category;
                        const reasoning = data.reasoning;
                        if (summary || category || reasoning) {
                            let replyText = `${category ? `**${category}**` : '已归档'}`;
                            if (summary) replyText += `\n\n${summary}`;
                            if (reasoning) replyText += `\n\n> 💡 ${reasoning}`;
                            messages.value.push({ role: 'assistant', type: 'text', content: replyText });
                        }
                    }
                } catch (err) {
                    console.error("上传失败", err);
                    messages.value[msgIdx].status = 'Failed';
                    messages.value[msgIdx].statusClass = 'text-red-500';
                }
                scrollToBottom();
            }
            e.target.value = '';
        };

        // [新增] 处理重命名会话（包装 prompt 调用）
        const handleRenameSession = async (sessionId, currentTitle) => {
            const newTitle = prompt('请输入新标题:', currentTitle);
            if (newTitle && newTitle.trim() && newTitle.trim() !== currentTitle) {
                await renameSession(sessionId, newTitle.trim());
            }
        };

        // [新增] 重命名会话
        const renameSession = async (sessionId, newTitle) => {
            // 处理 prompt 返回 null 或空字符串的情况
            if (!newTitle || newTitle.trim() === '') return;
            try {
                const res = await axios.put(`/api/v1/sessions/${sessionId}`, { title: newTitle.trim() });
                // API 返回 ChatSessionResponse，直接检查响应
                if (res.data && res.data.id) {
                    await fetchSessions();
                    console.log("✅ 会话重命名成功:", newTitle);
                } else {
                    throw new Error(res.data?.detail || '重命名失败');
                }
            } catch (e) {
                console.error("重命名会话失败:", e);
                alert("重命名失败: " + (e.response?.data?.detail || e.message || '未知错误'));
            }
        };

        const fetchLogs = async () => {
            try {
                const res = await axios.get('/api/v1/logs?lines=50');
                systemLogs.value = res.data.logs;
                // [修复] 获取日志后自动滚动到底部
                nextTick(() => {
                    if (logBox.value) {
                        logBox.value.scrollTop = logBox.value.scrollHeight;
                    }
                });
            } catch (e) {
                systemLogs.value = ["无法连接到日志服务..."];
            }
        };

        const resetChat = () => {
            messages.value = [];
            isMobileMenuOpen.value = false;
        };

        const scrollToBottom = () => nextTick(() => {
            if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight;
        });

        const renderMarkdown = (text) => marked.parse(text);

        // [新增] 监听配置面板切换
        watch(configPanel, () => {
            if (configPanel.value === 'logs') {
                nextTick(() => {
                    fetchLogs();
                    if (logBox.value) {
                        logBox.value.scrollTop = logBox.value.scrollHeight;
                    }
                });
            }
        });

        // 定期刷新日志（仅在日志面板激活时）
        setInterval(() => {
            if (currentView.value === 'config' && configPanel.value === 'logs') {
                fetchLogs();
            }
        }, 5000);

        // --- 认证功能 ---
        const login = async () => {
            if (!loginForm.value.username || !loginForm.value.password) {
                loginError.value = '请输入用户名和密码';
                return;
            }
            isLoggingIn.value = true;
            loginError.value = '';
            try {
                const res = await axios.post('/api/v1/auth/login', {
                    username: loginForm.value.username,
                    password: loginForm.value.password
                });
                token.value = res.data.access_token;
                localStorage.setItem('memex_token', token.value);
                showLogin.value = false;
                // 登录成功后初始化应用
                await fetchCurrentUser(); // 获取当前用户信息
                await fetchModels();
                await fetchSessions();
            } catch (e) {
                loginError.value = e.response?.data?.detail || '登录失败，请检查用户名和密码';
            } finally {
                isLoggingIn.value = false;
            }
        };

        const logout = () => {
            token.value = '';
            localStorage.removeItem('memex_token');
            localStorage.removeItem('memex_session_id');
            showLogin.value = true;
            messages.value = [];
            sessions.value = [];
            currentSessionId.value = '';
            currentUser.value = null;
            users.value = [];
        };

        // --- 用户管理功能 ---
        const fetchCurrentUser = async () => {
            try {
                const res = await axios.get('/api/v1/auth/me');
                currentUser.value = res.data;
            } catch (e) {
                console.error("获取当前用户信息失败:", e);
                currentUser.value = null;
            }
        };

        const fetchUsers = async () => {
            if (!isAdmin.value) return;
            try {
                const res = await axios.get('/api/v1/users');
                users.value = res.data;
            } catch (e) {
                console.error("获取用户列表失败:", e);
                alert("获取用户列表失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const createUser = async () => {
            if (!newUserForm.value.username || !newUserForm.value.password) {
                alert("请输入用户名和密码");
                return;
            }
            try {
                const res = await axios.post('/api/v1/users', newUserForm.value);
                alert("用户创建成功！");
                newUserForm.value = { username: '', password: '', email: '' };
                await fetchUsers();
            } catch (e) {
                console.error("创建用户失败:", e);
                alert("创建用户失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const updateUser = async (user) => {
            try {
                const updateData = {
                    username: user.username,
                    email: user.email || null,
                    is_active: user.is_active
                };
                await axios.put(`/api/v1/users/${user.id}`, updateData);
                alert("用户信息更新成功！");
                editingUser.value = null;
                await fetchUsers();
                if (user.id === currentUser.value?.id) {
                    await fetchCurrentUser();
                }
            } catch (e) {
                console.error("更新用户失败:", e);
                alert("更新用户失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const deleteUser = async (userId) => {
            if (!confirm("确定要删除该用户吗？此操作不可恢复。")) {
                return;
            }
            try {
                await axios.delete(`/api/v1/users/${userId}`);
                alert("用户删除成功！");
                await fetchUsers();
            } catch (e) {
                console.error("删除用户失败:", e);
                alert("删除用户失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const changePassword = async (userId, isAdminChange = false) => {
            if (!isAdminChange && !passwordForm.value.old_password) {
                alert("请输入旧密码");
                return;
            }
            if (!passwordForm.value.new_password) {
                alert("请输入新密码");
                return;
            }
            if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
                alert("新密码和确认密码不一致");
                return;
            }
            try {
                const payload = isAdminChange
                    ? { old_password: '', new_password: passwordForm.value.new_password }
                    : passwordForm.value;
                await axios.put(`/api/v1/users/${userId}/password`, payload);
                alert("密码修改成功！");
                passwordForm.value = { old_password: '', new_password: '', confirm_password: '' };
                isChangingPassword.value = false;
                editingUser.value = null; // 重置编辑状态
            } catch (e) {
                console.error("修改密码失败:", e);
                alert("修改密码失败: " + (e.response?.data?.detail || e.message));
            }
        };

        const updateProfile = async () => {
            if (!currentUser.value) return;
            try {
                const updateData = {
                    username: currentUser.value.username,
                    email: currentUser.value.email || null
                };
                await axios.put(`/api/v1/users/${currentUser.value.id}`, updateData);
                alert("个人信息更新成功！");
                await fetchCurrentUser();
            } catch (e) {
                console.error("更新个人信息失败:", e);
                alert("更新个人信息失败: " + (e.response?.data?.detail || e.message));
            }
        };

        // --- Axios 拦截器 ---
        // 请求拦截器：添加 Authorization header
        axios.interceptors.request.use(
            (config) => {
                if (token.value) {
                    config.headers.Authorization = `Bearer ${token.value}`;
                }
                return config;
            },
            (error) => {
                return Promise.reject(error);
            }
        );

        // 响应拦截器：处理 401 错误
        axios.interceptors.response.use(
            (response) => response,
            (error) => {
                if (error.response?.status === 401) {
                    // Token 无效或过期，清除 token 并显示登录界面
                    token.value = '';
                    localStorage.removeItem('memex_token');
                    showLogin.value = true;
                }
                return Promise.reject(error);
            }
        );

        // [新增] Audio Methods
        const playMessageAudio = (text) => {
            if (window.AudioManager) {
                window.AudioManager.playText(text);
            }
        };

        // [新增] Feedback Methods
        const openFeedbackModal = (msg) => {
            currentFeedbackMsg.value = msg;
            feedbackType.value = 'intent_wrong_search';
            feedbackComment.value = '';
            showFeedbackModal.value = true;
        };

        const closeFeedbackModal = () => {
            showFeedbackModal.value = false;
            currentFeedbackMsg.value = null;
        };

        const submitFeedback = async () => {
            if (!currentFeedbackMsg.value) return;

            // Try to find the user message before this AI message
            let inputContent = "";
            try {
                const idx = messages.value.indexOf(currentFeedbackMsg.value);
                if (idx > 0) {
                    inputContent = messages.value[idx - 1].content;
                }
            } catch (e) { }

            const payload = {
                input: inputContent || "Unknown Context",
                actual_intent: "unknown",
                expected_intent: feedbackType.value,
                comment: feedbackComment.value
            };

            try {
                await axios.post('/api/v1/system/feedback', payload);
                showToast("Feedback submitted. Thank you!", "success");
                closeFeedbackModal();
            } catch (e) {
                console.error("Feedback failed:", e);
                showToast("Failed to submit feedback.", "error");
            }
        };

        // [新增] 移动端视口高度动态调整 (解决键盘遮挡问题)
        const setupMobileViewport = () => {
            const updateHeight = () => {
                // visualViewport.height handles the soft keyboard on Android and iOS
                if (window.visualViewport) {
                    const vh = window.visualViewport.height;
                    const offsetTop = window.visualViewport.offsetTop;
                    // 使用 document.body 或 #app 设置高度
                    const appEl = document.getElementById('app');
                    if (appEl) {
                        // 确保 app 高度等于可视区域高度
                        // 注意: 在 iOS 上 visualViewport.offsetTop 通常为 0，除非发生了奇怪的滚动
                        document.documentElement.style.setProperty('--app-height', `${vh}px`);
                    }

                    // 如果键盘弹出 (高度显著变小)，强制滚动到底部
                    if (window.innerHeight - vh > 150) {
                        setTimeout(() => scrollToBottom(), 50);
                    }
                } else {
                    // Fallback
                    document.documentElement.style.setProperty('--app-height', `${window.innerHeight}px`);
                }
            };

            if (window.visualViewport) {
                window.visualViewport.addEventListener('resize', updateHeight);
                window.visualViewport.addEventListener('scroll', updateHeight); // iOS sometimes fires scroll instead of resize
            }
            window.addEventListener('resize', updateHeight);
            updateHeight(); // Initial set
        };

        // 初始化
        onMounted(async () => {
            setupMobileViewport(); // [New] Init viewport handler

            // 如果未登录，不执行初始化
            if (!isAuthenticated.value) {
                return;
            }
            await fetchCurrentUser(); // [新增] 获取当前用户信息
            await fetchModels(); // [新增] 获取模型列表
            await fetchAudioConfig(); // [新增] 获取语音配置
            await fetchSessions();
            await fetchArchives(); // [Auto-load] Knowledge Base
            await fetchPrompts(); // [Auto-load] Prompt Lab

            // [修复] 优先使用 localStorage 中的 session_id（如果存在且有效）
            const storedSessionId = localStorage.getItem('memex_session_id');
            if (storedSessionId) {
                // 检查该 session_id 是否在会话列表中
                const sessionExists = sessions.value.some(s => s.id === storedSessionId);
                if (sessionExists) {
                    console.log("✅ 恢复之前的会话，Session ID:", storedSessionId);
                    await switchSession(storedSessionId);
                } else {
                    // session_id 不在列表中，可能是新会话，保持使用它
                    console.log("ℹ️ 使用 localStorage 中的 Session ID（可能为新会话）:", storedSessionId);
                    currentSessionId.value = storedSessionId;
                    await fetchChatHistory(storedSessionId);
                }
            } else {
                // 如果没有 session，取消 loading 状态，显示 Jarvis
                isChatLoading.value = false;

                if (sessions.value.length > 0) {
                    // 没有 localStorage，但有会话列表，加载第一个
                    console.log("📋 加载第一个会话，Session ID:", sessions.value[0].id);
                    await switchSession(sessions.value[0].id);
                }
            }

            // [新增] 定期同步会话列表 (解决多端同步问题)
            // [Modified] Robust Polling (15s interval, silent)
            const startSessionPolling = async () => {
                await fetchSessions(true);
                setTimeout(startSessionPolling, 15000);
            };
            startSessionPolling();
        });

        // Dashboard Charts
        let activityChart = null;
        let typeChart = null;

        const initDashboardCharts = () => {
            // Ensure DOM is updated
            nextTick(() => {
                const activityCtx = document.getElementById('dashboardActivityChart');
                const typeCtx = document.getElementById('dashboardTypeChart');

                if (activityCtx && dashboardStats.value.charts?.activity_30d) {
                    if (activityChart) activityChart.destroy();
                    activityChart = new Chart(activityCtx, {
                        type: 'line',
                        data: {
                            labels: dashboardStats.value.charts.activity_30d.labels,
                            datasets: [{
                                label: '活跃度',
                                data: dashboardStats.value.charts.activity_30d.data,
                                borderColor: '#60A5FA',
                                backgroundColor: 'rgba(96, 165, 250, 0.1)',
                                fill: true,
                                tension: 0.4
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: { legend: { display: false } },
                            scales: {
                                y: { grid: { color: '#333' }, ticks: { color: '#9CA3AF' } },
                                x: { grid: { display: false }, ticks: { color: '#9CA3AF' } }
                            }
                        }
                    });
                }

                if (typeCtx && dashboardStats.value.charts?.type_distribution) {
                    if (typeChart) typeChart.destroy();
                    typeChart = new Chart(typeCtx, {
                        type: 'doughnut',
                        data: {
                            labels: dashboardStats.value.charts.type_distribution.labels,
                            datasets: [{
                                data: dashboardStats.value.charts.type_distribution.data,
                                backgroundColor: ['#60A5FA', '#A78BFA', '#34D399', '#FBBF24', '#F87171'],
                                borderWidth: 0
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: { legend: { position: 'right', labels: { color: '#e5e7eb' } } }
                        }
                    });
                }
            });
        };




        // Watch for panel switch to init charts
        watch(configPanel, (newPanel) => {
            if (newPanel === 'dashboard') {
                fetchDashboardStats().then(() => {
                    initDashboardCharts();
                });
                fetchDashboardProposals();
            }
        });

        // Initial load if dashboard is default
        onMounted(() => {
            // [修复] 桌面端强制显示侧边栏
            if (window.innerWidth >= 768) {
                isSidebarCollapsed.value = false;
                isMobileMenuOpen.value = false;
            }

            if (configPanel.value === 'dashboard') {
                fetchDashboardStats().then(() => {
                    initDashboardCharts();
                });
                fetchDashboardProposals();
            }
            // [Fix] Auto-load Archives and Prompts on mount
            fetchArchives();
            fetchPrompts();
            fetchStorageRoots(); // [New] Load Storage Roots
            fetchUserStorageLocations(); // [New] Load User Storage Locations
        });

        return {
            // 认证相关
            token, isAuthenticated, showLogin, loginError, loginForm, isLoggingIn, login, logout,
            // 用户管理相关
            currentUser, isAdmin, users, userPanel, newUserForm, editingUser, passwordForm, isChangingPassword,
            fetchCurrentUser, fetchUsers, createUser, updateUser, deleteUser, changePassword, updateProfile,
            messages, inputVal, currentModel, systemLogs, isSidebarCollapsed, isMobileMenuOpen, isConfigSidebarOpen, currentView, viewTitle,
            isThinking, isChatLoading, chatBox, logBox, showModelSelector, configPanel, switchConfigPanel, availableModels,
            hideKeyboard, // [新增]
            // [NEW] Collapsible Groups
            expandedGroups, toggleGroup,
            // [NEW] Dashboard
            dashboardStats, dashboardProposals, isDashboardLoading,
            fetchDashboardStats, fetchDashboardProposals, approveProposal, rejectProposal,
            dynamicConfigGroups, configValues, showPasswords, // [Fix] Expose config state
            systemControlGroups, sidebarConfigGroups, // [New] Expose split groups
            archives, isArchiveLoading, selectedArchive, isDrawerOpen, // [New] Archive State
            fetchArchives, openArchiveDrawer, closeArchiveDrawer, deleteArchive, // [New] Archive Methods
            // [New] Physical File Browser
            userStorageLocations, currentBrowseRoot, currentBrowsePath, fileListItems, isFileListLoading,
            selectedFiles, fileSortBy, fileSortAsc, pathParts,
            fetchUserStorageLocations, browseDirectory, browseIntoFolder, navigateToStorageRoot,
            navigateUp, navigateToBreadcrumb, toggleFileSelection, toggleSelectAll,
            batchDeleteFiles, sortFileList,

            // [NEW] Storage Management - ALL must be exported to avoid Vue crash!
            storageRoots, showStorageModal, isSubmittingStorage, storageForm,
            showFolderBrowser, currentBrowsePath_old, browserItems, isBrowsingLoading,
            fetchStorageRoots, openAddStorageModal, closeStorageModal, createStorageRoot,
            deleteStorageRoot, setDefaultStorageRoot,
            openFolderBrowser, fetchDirectoryListing, browseTo, browseUp, selectCurrentFolder,
            vibrate, // [NEW] Export vibrate helper
            getConfigValue, updateConfigValue, fetchConfigValues, testWebhook, saveAllConfig, // [Fix] Expose saveAllConfig
            routerModels, reasoningModels, visionModels, voiceModels, audioConfig, memoryConfig, memoryModels,
            newRouterModel, newReasoningModel, newVisionModel, newVoiceModel,
            editingRouterModel, editingReasoningModel, editingVisionModel, editingVoiceModel, editingMemoryModel,
            draggedIndex,
            isConfigLoading, configSaveStatus, clearDataConfirm, isClearingData,
            batchOpsTab, autoVectorizeAfterImport, // [NEW] Batch Ops State
            batchSelectedFiles, batchRateLimit, isBatchImporting, batchTaskId, batchProgress,
            isVectorizing, vectorizeTaskId, vectorizeProgress, isTestingVector, vectorTestResult,
            // Database
            dbTables, sqlQuery, queryResult, queryError, isExecutingQuery, fetchDbTables, executeSql, selectAllFromTable,
            topScroll, tableContainer, dataTable, tableWidth, syncScroll, // [New] Scroll Sync
            longTextModal, showLongTextModal, // [Fix] Export Long Text Modal
            // Model Testing
            testingModels, testModelConnection, getTestIconClass,
            toggleSidebar, toggleConfigSidebar, switchView, sendText, handleEnter, handleFileUpload, fetchLogs, resetChat, renderMarkdown,
            fetchConfig, saveMemoryConfig, saveAllConfig, getModelDisplayName, getPanelTitle, clearAllData,
            fetchRouterModels, addRouterModel, editRouterModel, deleteRouterModel, onRouterDragStart, onRouterDrop,
            editRouterModelCard, addNewRouterModelCard, saveRouterModelCard, cancelEditRouterModel,
            fetchReasoningModels, addReasoningModel, editReasoningModel, deleteReasoningModel,
            editReasoningModelCard, addNewReasoningModelCard, saveReasoningModelCard, cancelEditReasoningModel,
            fetchVisionModels, addVisionModel, editVisionModel, deleteVisionModel,
            editVisionModelCard, addNewVisionModelCard, saveVisionModelCard, cancelEditVisionModel, onVisionDragStart, onVisionDrop,
            fetchVoiceModels, addVoiceModel, editVoiceModel, deleteVoiceModel,
            editVoiceModelCard, addNewVoiceModelCard, saveVoiceModelCard, cancelEditVoiceModel, onVoiceDragStart, onVoiceDrop,
            hearingModels, newHearingModel, editingHearingModel,
            fetchHearingModels, addHearingModel, editHearingModel, deleteHearingModel,
            editHearingModelCard, addNewHearingModelCard, saveHearingModelCard, cancelEditHearingModel, onHearingDragStart, onHearingDrop,
            fetchMemoryModels, fetchMemoryConfig,
            editMemoryModelCard, addNewMemoryModelCard, saveMemoryModelCard, cancelEditMemoryModel, deleteMemoryModel, onMemoryDragStart, onMemoryDrop,
            onDragStart, onDragOver, onDrop,
            // Long Text Modal
            longTextModal, showLongTextModal,
            onDragStart, onDragOver, onDrop,
            handleBatchFileSelect, startBatchImport, fetchBatchStatus, getFileTypeIcon,
            startBatchVectorize, checkVectorizeStatus, startCombinedBatch, // [NEW] Batch Ops Functions
            stopBatchImport, // [placeholder]
            fetchAudioConfig, saveAudioConfig,
            // Session exports
            sessions, currentSessionId, fetchSessions, createNewSession, switchSession, deleteSession, renameSession, handleRenameSession, getCurrentSessionTitle, getCurrentSessionTitle, goHome,
            // Audio
            playMessageAudio,
            // Voice Recording (WeChat-style)
            isRecording, toggleVoiceRecording, isVoiceMode, recordingDuration, voiceSendCancelled, isProcessingVoice,
            // Feedback
            showFeedbackModal, feedbackType, feedbackComment, openFeedbackModal, closeFeedbackModal, submitFeedback,
            // Toast
            toast, showToast,
            // PromptOps
            prompts, editingPrompt, isPromptLoading, fetchPrompts, editPrompt, createPrompt, cancelEditPrompt, savePrompt, refreshPromptCache, groupedPrompts,
            handleFileDelete, handleFolderDelete,

            // [Fix] Authenticated File Download
            downloadSourceFile: async (archive) => {
                if (!archive.relative_path) return;
                try {
                    const res = await axios.get(`/api/v1/files/${archive.relative_path}`, {
                        responseType: 'blob'
                    });

                    // Create blob link to download
                    const url = window.URL.createObjectURL(new Blob([res.data]));
                    const link = document.createElement('a');
                    link.href = url;
                    // Try to use original filename if possible, else derive from path
                    const filename = archive.filename || archive.relative_path.split('/').pop() || 'download';
                    link.setAttribute('download', filename);
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    window.URL.revokeObjectURL(url);
                } catch (e) {
                    console.error("Download failed:", e);
                    showToast("下载失败: " + (e.response?.status === 404 ? "文件不存在" : "权限不足或系统错误"), "error");
                }
            },
            // DEBUG
            _debugCheck: () => { console.log('toggleSessionMenu type:', typeof toggleSessionMenu); },
            toggleSessionMenu,
            closeSessionMenu,
            sessionMenu
        };
    }
}).mount('#app');