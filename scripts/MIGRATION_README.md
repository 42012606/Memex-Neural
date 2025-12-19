# 数据库迁移说明

## 问题描述

1. **system_config 表缺少 user_id 字段**
   - 错误：`psycopg2.errors.UndefinedColumn: column system_config.user_id does not exist`
   - 原因：数据库表结构与模型定义不一致

2. **is_vectorized 字段类型不匹配**
   - 错误：`psycopg2.errors.DatatypeMismatch: column "is_vectorized" is of type integer but expression is of type boolean`
   - 原因：代码中使用了 `True`（Boolean），但数据库字段是 `Integer` 类型

## 修复内容

### 1. 数据库结构修复

**方式一：使用 SQL 脚本（推荐）**

```bash
# 在 PostgreSQL 容器中执行
docker exec -it memex-postgres psql -U memex -d memex -f /path/to/migrate_system_config.sql
```

或者直接在容器中执行 SQL：

```bash
docker exec -it memex-postgres psql -U memex -d memex
```

然后执行：

```sql
ALTER TABLE system_config 
ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_system_config_user_id ON system_config(user_id);
```

**方式二：使用 Python 脚本**

```bash
# 在 Docker 容器中执行
docker exec -it memex-backend python /app/scripts/migrate_system_config.py
```

### 2. 代码修复

已修复以下文件中的类型不匹配问题：

- ✅ `src/services/processor.py`：`is_vectorized = True` → `is_vectorized = 1`
- ✅ `src/api/data_endpoints.py`：`is_vectorized = True` → `is_vectorized = 1`
- ✅ `src/api/data_endpoints.py`：`is_vectorized == False` → `is_vectorized == 0`
- ✅ `src/api/data_endpoints.py`：优化判断逻辑 `if record.is_vectorized == 1:`

### 3. 模型定义验证

✅ `src/models/archive.py` 中的 `is_vectorized` 字段定义正确：
```python
is_vectorized = Column(Integer, default=0, index=True, comment="是否已向量化 0=否 1=是")
```

## 执行步骤

1. **执行数据库迁移**
   ```bash
   # 方式一：SQL 脚本
   docker exec -it memex-postgres psql -U memex -d memex < scripts/migrate_system_config.sql
   
   # 方式二：Python 脚本
   docker exec -it memex-backend python scripts/migrate_system_config.py
   ```

2. **重启服务**
   ```bash
   docker-compose restart
   ```

3. **验证修复**
   - 上传一个文件，检查是否成功向量化
   - 查看日志，确认没有数据库错误

## 验证查询

执行以下 SQL 验证迁移是否成功：

```sql
-- 检查 system_config 表结构
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'system_config'
ORDER BY ordinal_position;

-- 检查 archives 表的 is_vectorized 字段
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'archives' AND column_name = 'is_vectorized';
```

## 注意事项

- `is_vectorized` 字段使用 Integer 类型：`0` = 未向量化，`1` = 已向量化
- 所有代码中的 Boolean 值已改为 Integer 值
- `user_id` 字段默认值为 `1`（单用户模式）

