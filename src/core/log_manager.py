import logging
from collections import deque
from typing import List

class MemoryLogHandler(logging.Handler):
    """
    In-memory log handler that stores logs in a ring buffer (deque).
    Used to serve real-time logs to the frontend without disk IO blocking.
    """
    def __init__(self, maxlen=200):
        super().__init__()
        self.log_buffer = deque(maxlen=maxlen)
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_logs(self) -> List[str]:
        """Return all logs currently in the buffer."""
        return list(self.log_buffer)

# Global singleton instance
log_manager = MemoryLogHandler()
