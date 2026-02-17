import os
import importlib.util
import inspect
from typing import Dict
from core.interfaces import BasePlugin

class PluginManager:
    def __init__(self, plugin_folder: str = "plugins"):
        self.plugin_folder = plugin_folder
        self.plugins: Dict[str, BasePlugin] = {}
        self.active_plugin: BasePlugin = None

    def load_plugins(self):
        if not os.path.exists(self.plugin_folder):
            os.makedirs(self.plugin_folder)

        for filename in os.listdir(self.plugin_folder):
            if filename.endswith(".py") and not filename.startswith("__"):
                self._load_file(filename)

    def _load_file(self, filename: str):
        path = os.path.join(self.plugin_folder, filename)
        module_name = filename[:-3]
        
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                instance = obj()
                self.plugins[instance.name] = instance
                print(f"[PluginManager] Loaded: {instance.name}")

    async def set_active_plugin(self, name: str):
        if name in self.plugins:
            self.active_plugin = self.plugins[name]
            await self.active_plugin.initialize()
        else:
            raise ValueError(f"Plugin {name} not found")