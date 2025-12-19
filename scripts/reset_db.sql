-- ⚠️ 警告：这将清空所有数据！
-- ⚠️ WARNING: This will DELETE ALL DATA!

-- 1. 清空业务数据 (Business Data)
TRUNCATE TABLE chat_messages CASCADE;
TRUNCATE TABLE chat_sessions CASCADE;
TRUNCATE TABLE archives CASCADE;
-- 如果有 vector_nodes 表
-- TRUNCATE TABLE vector_nodes CASCADE; 

-- 2. 清空配置数据 (可选 - 重启后会自动重新生成默认值)
--    If you keep these, your API Keys and custom prompts remain.
--    If you delete these, they revert to code defaults.
TRUNCATE TABLE ai_models CASCADE;
TRUNCATE TABLE prompt_configs CASCADE;
TRUNCATE TABLE system_config CASCADE;
TRUNCATE TABLE users CASCADE;
TRUNCATE TABLE storage_roots CASCADE;

-- 3. 重置序列 (可选 - 让 ID 从 1 开始)
ALTER SEQUENCE chat_messages_id_seq RESTART WITH 1;
ALTER SEQUENCE chat_sessions_id_seq RESTART WITH 1;
ALTER SEQUENCE archives_id_seq RESTART WITH 1;
ALTER SEQUENCE users_id_seq RESTART WITH 1;
