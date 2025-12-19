
import logging
from src.core.plugins import BasePlugin
from src.core.events import EventBus, Event
from src.core.event_types import FILE_UPLOADED

logger = logging.getLogger(__name__)

class ExamplePlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "ExamplePlugin"

    def register(self, bus: EventBus):
        bus.subscribe(FILE_UPLOADED, self.handle_file_uploaded)
        logger.info("ExamplePlugin subscribed to FILE_UPLOADED event.")

    async def handle_file_uploaded(self, event: Event):
        """测试处理文件上传事件"""
        file_path = event.payload.get("file_path")
        logger.info(f"⚡ [ExamplePlugin] 收到文件上传事件: {file_path}")
        logger.info(f"   Payload: {event.payload}")
