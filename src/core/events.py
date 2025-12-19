
import asyncio
import logging
import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Callable, Union, Awaitable

logger = logging.getLogger(__name__)

@dataclass
class Event:
    """标准事件对象"""
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

class EventBus:
    """
    异步事件总线 (Singleton)
    - 支持 sync 和 async handler
    - 错误隔离: handler 失败不会导致总线崩溃
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
            cls._instance._subscribers: Dict[str, List[Callable]] = {}
        return cls._instance

    def subscribe(self, event_name: str, handler: Callable[[Event], Union[None, Awaitable[None]]]):
        """订阅事件"""
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        
        # [FIX] 防止重复订阅同一个 handler（热重载时会发生）
        existing_handlers = [h.__name__ for h in self._subscribers[event_name]]
        if handler.__name__ in existing_handlers:
            logger.debug(f"Handler {handler.__name__} already subscribed to {event_name}, skipping.")
            return
            
        self._subscribers[event_name].append(handler)
        logger.debug(f"Handler {handler.__name__} subscribed to {event_name}")
    
    def clear_subscribers(self):
        """清空所有订阅者（用于热重载时重置状态）"""
        count = sum(len(handlers) for handlers in self._subscribers.values())
        self._subscribers.clear()
        logger.info(f"🔄 EventBus: Cleared {count} subscribers (reset for reload)")

    async def publish(self, event: Event):
        """发布事件 (异步执行所有 handlers)"""
        if event.name not in self._subscribers:
            logger.debug(f"Event {event.name} published but no subscribers.")
            return

        handlers = self._subscribers[event.name]
        logger.info(f"Adding task to process event: {event.name} (Payload keys: {list(event.payload.keys())})")
        
        # 并行执行所有 handler
        tasks = []
        for handler in handlers:
            tasks.append(self._execute_handler(handler, event))
        
        # 等待所有 handler 完成（或报错）
        # return_exceptions=True 确保一个失败不影响其他
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_handler(self, handler, event: Event):
        """执行单个 Handler 并捕获异常"""
        try:
            if inspect.iscoroutinefunction(handler):
                await handler(event)
            else:
                # 在线程池中运行同步函数，防止阻塞 Event Loop
                await asyncio.to_thread(handler, event)
        except Exception as e:
            logger.error(f"Error handling event {event.name} in {handler.__name__}: {str(e)}", exc_info=True)
            # TODO: 可以在这里发布一个 SYSTEM_ERROR 事件，或者写入错误表

# 全局实例
event_bus = EventBus()
