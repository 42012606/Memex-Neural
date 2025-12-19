
# 标准事件类型定义

# 当 API 收到文件上传并保存到临时区/原始区后触发
# Payload: { "file_path": Path, "user_id": int, "original_filename": str, "temp_id": str }
FILE_UPLOADED = "FILE_UPLOADED"

# 当 AI 分析完成，提取了元数据后触发
# Payload: { "file_path": Path, "summary": str, "suggested_filename": str, "meta_data": dict }
METADATA_EXTRACTED = "METADATA_EXTRACTED"

# 当文件归档完成（移动并入库）后触发
# Payload: { "archive_id": int, "final_path": Path, "file_type": str }
ARCHIVE_COMPLETED = "ARCHIVE_COMPLETED"

# 当向量化完成后触发
# Payload: { "archive_id": int, "vector_id": str }
VECTORIZATION_COMPLETED = "VECTORIZATION_COMPLETED"

# 当任何步骤处理失败时触发
# Payload: { "file_path": Path, "error": str, "stage": str }
PROCESSING_FAILED = "PROCESSING_FAILED"
