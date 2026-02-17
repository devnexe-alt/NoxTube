import subprocess
import win32gui
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider
from PyQt5.QtGui import QWindow
from PyQt5.QtCore import Qt, QTimer, QProcess

class NativePlayer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000000;")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # --- Кнопка "Назад" ---
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(8, 8, 8, 4)
        self.back_btn = QPushButton("← Back")
        self.back_btn.setFixedSize(80, 30)
        self.back_btn.setStyleSheet("background-color: #333; color: white; border-radius: 4px;")
        top_bar.addWidget(self.back_btn)
        top_bar.addStretch()
        self.layout.addLayout(top_bar)

        # --- Контейнер для видео ---
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: #000;")
        self.layout.addWidget(self.video_container, stretch=1)

        # --- Панель управления (упрощенная для FFplay) ---
        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 8)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        
        # FFplay управляется клавишами, поэтому кнопки будут слать команды окну
        self.info_label = QLabel("Space: Pause | M: Mute | ←→: Seek")
        self.info_label.setStyleSheet("color: #555; font-size: 10px;")

        controls.addWidget(self.status_label)
        controls.addStretch()
        controls.addWidget(self.info_label)
        self.layout.addLayout(controls)

        # --- Логика процесса ---
        self.process = QProcess(self)
        self.embed_timer = QTimer()
        self.embed_timer.setInterval(200)
        self.embed_timer.timeout.connect(self.try_embed)
        
        self.current_hwnd = None

    def play_raw_url(self, url: str):
        if not url: return
        self.stop() # Убиваем старый процесс если есть

        print(f"[FFplay] Запуск: {url[:60]}...")
        
        # -noborder убирает рамки
        # -window_title нужен чтобы найти окно через win32gui
        args = [
            "-loglevel", "quiet",
            "-noborder",
            "-window_title", "NoxInternalPlayer",
            url
        ]
        
        self.process.start("ffplay", args)
        self.status_label.setText("Loading...")
        self.embed_timer.start()

    def try_embed(self):
        hwnd = win32gui.FindWindow(None, "NoxInternalPlayer")
        if hwnd and hwnd != self.current_hwnd:
            self.current_hwnd = hwnd
            self.embed_timer.stop()
            
            # Встраиваем окно в PyQt
            window = QWindow.fromWinId(hwnd)
            self.video_widget = QWidget.createWindowContainer(window, self.video_container)
            
            # Очищаем старые виджеты из контейнера видео если были
            if self.video_container.layout():
                # Удаляем старый лейаут
                import sip
                sip.delete(self.video_container.layout())
            
            v_layout = QVBoxLayout(self.video_container)
            v_layout.setContentsMargins(0,0,0,0)
            v_layout.addWidget(self.video_widget)
            
            self.status_label.setText("Playing")

    def stop(self):
        self.embed_timer.stop()
        if self.process.state() == QProcess.Running:
            self.process.terminate()
            self.process.waitForFinished(1000)
        self.current_hwnd = None
        self.status_label.setText("Stopped")

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)