"""
Context Memory Service - 滚动摘要与滑动窗口
负责实时蒸馏历史对话，压缩 Token，注入给大模型
"""
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.models.chat import ChatMessage
from src.services.ai_service import AIService

logger = logging.getLogger(__name__)


class ContextMemoryService:
    """
    上下文记忆服务
    - 实现滚动摘要（Rolling Summary）：小模型实时蒸馏历史对话
    - 实现滑动窗口（Sliding Window）：限制直接注入的消息数量
    """
    
    # 配置参数
    SLIDING_WINDOW_SIZE = 10  # 滑动窗口：直接注入最近 N 条消息
    SUMMARY_TRIGGER_THRESHOLD = 15  # 当历史消息超过此数量时，触发摘要生成
    MAX_SUMMARY_LENGTH = 500  # 摘要最大长度（字符数）
    
    def __init__(self, db: Session):
        self.db = db
        self.router_service = AIService(service_type="router")  # 使用小模型生成摘要
    
    def get_recent_messages(
        self, 
        session_id: str, 
        limit: int = 50,
        exclude_last: int = 0
    ) -> List[ChatMessage]:
        """
        获取会话的最近消息（按时间正序）
        :param session_id: 会话ID
        :param limit: 最大返回数量
        :param exclude_last: 排除最后 N 条（用于排除当前正在处理的消息）
        """
        query = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        
        if exclude_last > 0:
            # 获取总数
            total = query.count()
            if total > exclude_last:
                # 只取前面的消息
                query = query.limit(total - exclude_last)
        
        messages = query.limit(limit).all()
        return messages
    
    async def generate_rolling_summary(
        self, 
        messages: List[ChatMessage],
        current_time: str
    ) -> str:
        """
        使用小模型（Router）生成滚动摘要
        :param messages: 历史消息列表
        :param current_time: 当前系统时间
        :return: 压缩后的摘要文本
        """
        if not messages:
            return ""
        
        # 构建对话历史文本
        conversation_text = "\n".join([
            f"{msg.role.upper()}: {msg.content}"
            for msg in messages
        ])

        # 安全截断，避免长上下文导致小模型调用失败
        MAX_CONTEXT_CHARS = 3000
        if len(conversation_text) > MAX_CONTEXT_CHARS:
            logger.warning(
                f"⚠️ ContextMemory: 历史对话过长，截断用于摘要的文本 "
                f"(len={len(conversation_text)} -> {MAX_CONTEXT_CHARS})"
            )
            conversation_text = "...(truncated)..." + conversation_text[-MAX_CONTEXT_CHARS:]
        
        # 构建摘要生成 Prompt
        from src.core.prompt_manager import prompt_manager
        
        # 使用配置化提示词
        base_prompt = prompt_manager.get("tasks.summarization")
        if not base_prompt:
             # Fallback
             base_prompt = "请简要总结以下内容，提取关键信息点，并保持客观。"
             
        summary_prompt = f"""
System Context: Current Server Time is {current_time}.

{base_prompt}

【历史对话】
{conversation_text}
"""
        
        try:
            # 使用 Router 小模型生成摘要（支持 Failover）
            result = await self.router_service.chat(
                query="请生成上述对话的摘要。",
                context=summary_prompt
            )
            summary = result.get("reply", "") if isinstance(result, dict) else str(result)
            
            # 清理摘要（移除可能的代码块标记）
            summary = summary.strip()
            if summary.startswith("```"):
                lines = summary.split("\n")
                if len(lines) > 1:
                    summary = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            
            # 限制长度
            if len(summary) > self.MAX_SUMMARY_LENGTH:
                summary = summary[:self.MAX_SUMMARY_LENGTH] + "..."
            
            logger.info(f"✅ 生成滚动摘要成功，长度: {len(summary)} 字符")
            return summary
            
        except Exception as e:
            logger.error(f"❌ 生成滚动摘要失败: {e}", exc_info=True)
            # 降级：返回简单的消息计数
            return f"[历史对话摘要生成失败，共 {len(messages)} 条历史消息]"
    
    async def build_context_with_memory(
        self,
        session_id: str,
        current_query: str,
        base_context: str = "",
        exclude_last_n: int = 1  # 排除最后 N 条（当前正在处理的消息）
    ) -> Tuple[List[Dict[str, str]], str, str]:
        """
        构建带记忆的上下文（遵循单一系统消息原则）
        - 如果历史消息少，直接注入所有消息
        - 如果历史消息多，使用滑动窗口 + 滚动摘要
        
        :param session_id: 会话ID
        :param current_query: 当前查询（用于上下文）
        :param base_context: 基础上下文（检索结果等）
        :param exclude_last_n: 排除最后 N 条消息
        :return: (messages_list, summary_text, conversation_context)
            - messages_list: 历史对话消息列表（user/assistant 对）
            - summary_text: 滚动摘要文本（如果有）
            - conversation_context: 对话上下文文本（包含时间、窗口消息、检索结果）
        """
        # 获取历史消息
        all_messages = self.get_recent_messages(
            session_id=session_id,
            limit=100,  # 获取足够多的历史消息
            exclude_last=exclude_last_n
        )
        
        total_messages = len(all_messages)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 如果消息数量少，直接注入所有消息
        if total_messages <= self.SLIDING_WINDOW_SIZE:
            # 构建消息列表（user/assistant 对）
            messages_list = []
            for msg in all_messages:
                messages_list.append({
                    'role': msg.role,
                    'content': msg.content
                })
            
            # 构建对话上下文文本
            context_parts = []
            if total_messages > 0:
                recent_text = "\n".join([
                    f"{msg.role.upper()}: {msg.content}"
                    for msg in all_messages
                ])
                context_parts.append(f"[对话历史]\n{recent_text}")
            
            # 添加基础上下文（检索结果等）
            if base_context:
                context_parts.append(base_context)
            
            conversation_context = "\n\n".join(context_parts) if context_parts else ""
            summary_text = ""  # 短对话不需要摘要
            
            logger.info(f"📝 直接注入 {total_messages} 条历史消息")
            return messages_list, summary_text, conversation_context
        
        # 消息数量多，使用滑动窗口 + 滚动摘要
        # 1. 获取窗口内的最近消息（直接注入）
        window_messages = all_messages[-self.SLIDING_WINDOW_SIZE:]
        
        # 构建消息列表（只包含窗口内的消息）
        messages_list = []
        for msg in window_messages:
            messages_list.append({
                'role': msg.role,
                'content': msg.content
            })
        
        # 2. 获取窗口外的历史消息（用于生成摘要）
        older_messages = all_messages[:-self.SLIDING_WINDOW_SIZE]
        
        # 3. 生成滚动摘要
        summary_text = ""
        if older_messages and total_messages >= self.SUMMARY_TRIGGER_THRESHOLD:
            logger.info(f"🔄 触发滚动摘要生成，历史消息: {len(older_messages)} 条，窗口消息: {len(window_messages)} 条")
            summary_text = await self.generate_rolling_summary(older_messages, current_time)
        
        # 4. 构建对话上下文文本（不包含时间上下文，时间上下文将在 chat.py 中合并到系统提示）
        context_parts = []
        
        # 最近对话（滑动窗口）
        window_text = "\n".join([
            f"{msg.role.upper()}: {msg.content}"
            for msg in window_messages
        ])
        context_parts.append(f"[最近对话（最近 {len(window_messages)} 条）]\n{window_text}")
        
        # 基础上下文（检索结果等）
        if base_context:
            context_parts.append(base_context)
        
        conversation_context = "\n\n".join(context_parts)
        
        logger.info(f"📚 上下文记忆构建完成：摘要({len(summary_text)} 字符) + 窗口({len(window_messages)} 条) + 基础上下文")
        return messages_list, summary_text, conversation_context

