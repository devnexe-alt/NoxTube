# utils/resources.py
"""
Утилиты для работы с ресурсами
"""
import sys
import os

def resource_path(relative_path):
    """Получить абсолютный путь к ресурсу"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    full_path = os.path.join(base_path, relative_path)
    if not os.path.exists(full_path) and not relative_path.startswith("fonts/"):
        alt_path = os.path.join(base_path, "fonts", os.path.basename(relative_path))
        if os.path.exists(alt_path):
            return alt_path
    
    return full_path