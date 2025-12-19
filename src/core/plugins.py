
import importlib
import pkgutil
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, Type
from pathlib import Path
from src.core.events import EventBus, event_bus

logger = logging.getLogger(__name__)

class BasePlugin(ABC):
    """
    插件基类。所有插件必须继承此类并实现 register 方法。
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        pass

    @abstractmethod
    def register(self, bus: EventBus):
        """在此方法中订阅事件"""
        pass

class PluginManager:
    """
    插件管理器，负责加载和初始化插件
    """
    def __init__(self, bus: EventBus, plugin_dir: str = "src/plugins"):
        self.bus = bus
        self.plugin_dir = plugin_dir
        self.plugins: Dict[str, BasePlugin] = {}

    def load_plugins(self):
        """扫描并加载所有插件"""
        logger.info(f"Scanning plugins in {self.plugin_dir}...")
        
        # 确保目录存在
        if not os.path.exists(self.plugin_dir):
            os.makedirs(self.plugin_dir, exist_ok=True)
            # 创建 __init__.py 使其成为包
            init_file = os.path.join(self.plugin_dir, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    f.write("")
            return

        # 动态导入
        # 假设 plugin_dir 是 relative path like 'src/plugins'
        # 转换为 module path 'src.plugins'
        package_name = self.plugin_dir.replace("/", ".").replace("\\", ".")
        
        try:
            package = importlib.import_module(package_name)
        except ImportError as e:
            logger.error(f"Failed to import plugin package {package_name}: {e}")
            return

        # 遍历包下的模块
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            full_module_name = f"{package_name}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                self._register_plugin_from_module(module)
            except Exception as e:
                logger.error(f"Error loading plugin module {full_module_name}: {e}", exc_info=True)

    def _register_plugin_from_module(self, module):
        """从模块中查找并实例化 BasePlugin 子类"""
        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)
            
            if (isinstance(attribute, type) and 
                issubclass(attribute, BasePlugin) and 
                attribute is not BasePlugin):
                
                # [Fix] 防止导入的插件被重复注册
                # Only register plugins defined in this module
                if attribute.__module__ != module.__name__:
                    continue

                try:
                    plugin_instance = attribute()
                    plugin_name = plugin_instance.name
                    
                    if plugin_name in self.plugins:
                        logger.warning(f"Plugin {plugin_name} already registered. Skipping.")
                        continue
                        
                    logger.info(f"Registering plugin: {plugin_name}")
                    plugin_instance.register(self.bus)
                    self.plugins[plugin_name] = plugin_instance
                    
                except Exception as e:
                    logger.error(f"Failed to instantiate plugin {attribute.__name__}: {e}", exc_info=True)

# 全局实例
plugin_manager = PluginManager(event_bus)
