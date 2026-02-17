# ui/components/titlebar.py
"""
Кастомный заголовок окна
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from core.constants import MaterialIcon
from utils.resources import resource_path

class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setFixedHeight(33)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(0)
        
        # Левая часть (иконка + меню)
        self.left_widget = QWidget()
        left_layout = QHBoxLayout(self.left_widget)
        left_layout.setContentsMargins(8, 3, 0, 0)
        left_layout.setSpacing(8)
        
        # Иконка приложения
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(18, 18)
        pixmap = QPixmap(resource_path("icon.ico")).scaled(
            18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.icon_label.setPixmap(pixmap)
        self.icon_label.setScaledContents(True)
        
        # Центральная часть (для перетаскивания)
        self.center_widget = QWidget()
        self.center_widget.setObjectName("centerWidget")
        
        # Правая часть (кнопки управления)
        self.right_widget = QWidget()
        right_layout = QHBoxLayout(self.right_widget)
        right_layout.setContentsMargins(0, 2, 2, 0)
        right_layout.setSpacing(0)
        
        self.minimize_btn = self.create_button(MaterialIcon.MINIMIZE, "minimize")
        self.maximize_btn = self.create_button(MaterialIcon.MAXIMIZE, "maximize")
        self.close_btn = self.create_button(MaterialIcon.CLOSE, "close")

        right_layout.addSpacing(10) # Небольшой отступ между терминалом и кнопками окна
        right_layout.addWidget(self.minimize_btn)
        right_layout.addWidget(self.maximize_btn)
        right_layout.addWidget(self.close_btn)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.left_widget)
        layout.addWidget(self.center_widget, 1)
        layout.addWidget(self.right_widget)
        
        # Подключаем события
        self.minimize_btn.clicked.connect(self.parent.showMinimized)
        self.maximize_btn.clicked.connect(self.toggle_maximize)
        self.close_btn.clicked.connect(self.parent.close)
        
        self.setStyleSheet("""
            CustomTitleBar {
                background-color: #1f1f1f;
                border-bottom: 3px solid qlineargradient(
                    horizontal, 
                    rgba(0, 122, 204, 0.3), 
                    rgba(0, 122, 204, 0.0)
                );
            }
            #centerWidget {
                background-color: transparent;
            }
        """)
    
    def create_button(self, icon, btn_type):
        """Создание кнопки управления окном"""
        btn = QPushButton(icon)
        btn.setFixedSize(30, 30)
        
        style = f"""
            QPushButton {{
                background: transparent;
                border: 2px solid #1f1f1f;
                border-radius: 6px;
                color: #cccccc;
                font-family: 'Material Symbols Rounded';
                font-size: {14 if btn_type == 'maximize' else 18}px;
                font-weight: normal;
            }} 
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.15);
            }}
        """
        
        if btn_type == 'close':
            style = """
                QPushButton {
                    background: transparent;
                    border-radius: 6px;
                    border: 2px solid #1f1f1f;
                    color: #cccccc;
                    font-family: 'Material Symbols Rounded';
                    font-size: 18px;
                    font-weight: normal;
                }
                QPushButton:hover {
                    background-color: #e81123;
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background-color: #f1707a;
                }
            """
        
        btn.setStyleSheet(style)
        return btn
    
    def toggle_maximize(self):
        if self.parent.isMaximized():
            self.parent.showNormal()
        else:
            self.parent.showMaximized()
    
    def update_maximize_button(self):
        if self.parent.isMaximized():
            self.maximize_btn.setText(MaterialIcon.RESTORE)
        else:
            self.maximize_btn.setText(MaterialIcon.MAXIMIZE)
    
    def mouseDoubleClickEvent(self, event):
        self.toggle_maximize()
        event.accept()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent.windowHandle().startSystemMove()
        super().mousePressEvent(event)