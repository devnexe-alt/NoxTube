import sys
import subprocess
import json
import time
import threading
import queue
import traceback

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QScrollArea, QSizePolicy, QSlider, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QEvent, QRectF, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PyQt5.QtGui import QFont, QPixmap, QImage, QPainterPath, QRegion
from PyQt5.QtWidgets import QGraphicsOpacityEffect

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

AUDIO_RATE       = 44100
AUDIO_CHANNELS   = 2
AUDIO_CHUNK      = 4096
BYTES_PER_SAMPLE = 2
BYTES_PER_FRAME  = BYTES_PER_SAMPLE * AUDIO_CHANNELS


def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def _fmt(s: float) -> str:
    s = int(s)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

class AVWorker(QThread):
    frame_ready    = pyqtSignal(QImage)
    duration_found = pyqtSignal(float)
    time_update    = pyqtSignal(float)
    error_signal   = pyqtSignal(str)

    def __init__(self, url, start_time=0):
        super().__init__()
        self.url        = url
        self.start_time = float(start_time)
        self.width      = 0
        self.height     = 0
        self.running    = True
        self.fps        = 30.0
        self.video_proc = None
        self.audio_proc = None
        self._video_queue        = queue.Queue(maxsize=30)
        self._audio_bytes_played = 0
        self._audio_lock         = threading.Lock()
        self._stop_event         = threading.Event()
        
        # Громкость: 0.0-1.0, поток читает это значение при микшировании
        self._volume      = 1.0
        self._volume_lock = threading.Lock()

    @staticmethod
    def _si():
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return si
        return None

    def _audio_clock(self):
        with self._audio_lock:
            b = self._audio_bytes_played
        return self.start_time + b / (AUDIO_RATE * BYTES_PER_FRAME)

    def run(self):
        try:
            self._run_inner()
        except Exception:
            _log("worker.run", traceback.format_exc())

    def _run_inner(self):
        direct_url, duration, fps, width, height = self._resolve_url()
        if direct_url is None:
            return
        self.fps, self.width, self.height = fps, width, height
        self.duration_found.emit(duration)

        si = self._si()
        video_cmd = [
            'ffmpeg', '-ss', str(self.start_time),
            '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
            '-i', direct_url, '-an',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'
        ]
        audio_cmd = [
            'ffmpeg', '-ss', str(self.start_time),
            '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
            '-i', direct_url, '-vn',
            '-f', 's16le', '-ar', str(AUDIO_RATE), '-ac', str(AUDIO_CHANNELS), '-'
        ]

        try:
            self.video_proc = subprocess.Popen(
                video_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=self.width * self.height * 3 * 4, startupinfo=si)
        except Exception:
            _log("worker", "video ffmpeg failed\n" + traceback.format_exc())
            return

        try:
            self.audio_proc = subprocess.Popen(
                audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=AUDIO_CHUNK * 8, startupinfo=si)
        except Exception:
            _log("worker", "audio ffmpeg failed\n" + traceback.format_exc())
            self.video_proc.terminate()
            return

        vt = threading.Thread(target=self._read_video, daemon=True)
        at = threading.Thread(target=self._play_audio, daemon=True)
        vt.start(); at.start()
        self._render_loop()
        at.join(timeout=3); vt.join(timeout=2)

    @staticmethod
    def _is_direct_url(url: str) -> bool:
        """Прямой поток — не нужно прогонять через yt-dlp."""
        direct_hosts = (
            "googlevideo.com",
            "videoplayback",
            "r1---sn-", "r2---sn-", "r3---sn-", "r4---sn-",
            "r5---sn-", "r6---sn-", "r7---sn-", "r8---sn-",
            "r9---sn-", "r10---sn-", "r11---sn-",
        )
        return any(h in url for h in direct_hosts)

    def _resolve_url(self):
        # Если URL уже прямой — берём размер из ffprobe, yt-dlp не нужен
        if self._is_direct_url(self.url):
            _log("resolve", "direct URL detected, skipping yt-dlp")
            w, h, fps, dur = self._probe_stream(self.url)
            return self.url, dur, fps, w, h

        # Иначе — резолвим через yt-dlp
        cmd = ["yt-dlp", "--no-warnings", "--print-json", "-f", "best[ext=mp4]/best", self.url]
        try:
            res  = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, startupinfo=self._si())
            data = json.loads(res.decode())
            return (data['url'],
                    float(data.get('duration', 0)),
                    float(data.get('fps', 30) or 30),
                    int(data.get('width',  1280) or 1280),
                    int(data.get('height',  720) or  720))
        except Exception:
            _log("resolve", traceback.format_exc())
            self.error_signal.emit("yt-dlp failed")
            return None, 0, 30, 1280, 720

    def _probe_stream(self, url: str):
        """Получаем width/height/fps/duration через ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            url
        ]
        try:
            res  = subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                           startupinfo=self._si(), timeout=15)
            data = json.loads(res.decode())
            w = h = fps = dur = 0
            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    w   = int(s.get("width",  1280) or 1280)
                    h   = int(s.get("height",  720) or  720)
                    # fps может быть "30/1" или "30000/1001"
                    fps_raw = s.get("r_frame_rate", "30/1")
                    try:
                        num, den = fps_raw.split("/")
                        fps = float(num) / float(den)
                    except Exception:
                        fps = 30.0
            dur_raw = data.get("format", {}).get("duration", "0")
            try:
                dur = float(dur_raw)
            except Exception:
                dur = 0.0
            _log("probe", f"size={w}x{h} fps={fps:.2f} dur={dur:.1f}s")
            return w or 1280, h or 720, fps or 30.0, dur
        except Exception:
            _log("probe", "ffprobe failed, using defaults\n" + traceback.format_exc())
            return 1280, 720, 30.0, 0.0


    def _read_video(self):
        frame_size  = self.width * self.height * 3
        frame_index = 0
        try:
            while self.running:
                raw = self.video_proc.stdout.read(frame_size)
                if len(raw) < frame_size:
                    break
                pts = self.start_time + frame_index / self.fps
                img = QImage(raw, self.width, self.height, QImage.Format_RGB888).copy()
                while self.running:
                    try:
                        self._video_queue.put((pts, img), timeout=0.05); break
                    except queue.Full:
                        continue
                frame_index += 1
        except Exception:
            _log("video_reader", traceback.format_exc())

    def set_volume(self, vol: float):
        """Установить громкость 0.0-1.0"""
        with self._volume_lock:
            self._volume = max(0.0, min(1.0, vol))

    def _play_audio(self):
        if not PYAUDIO_AVAILABLE:
            self._drain_no_pyaudio(); return
        pa = stream = None
        try:
            import numpy as np
        except ImportError:
            _log("audio", "numpy not found, volume control disabled")
            np = None
        
        try:
            pa     = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=AUDIO_CHANNELS,
                             rate=AUDIO_RATE, output=True,
                             frames_per_buffer=AUDIO_CHUNK // BYTES_PER_FRAME)
            while self.running and not self._stop_event.is_set():
                data = self.audio_proc.stdout.read(AUDIO_CHUNK)
                if not data: break
                if not self.running or self._stop_event.is_set(): break
                
                # Применяем громкость через numpy
                if np is not None:
                    with self._volume_lock:
                        vol = self._volume
                    if vol < 0.99:  # оптимизация — не микшируем если vol=1.0
                        samples = np.frombuffer(data, dtype=np.int16)
                        samples = (samples * vol).astype(np.int16)
                        data = samples.tobytes()
                
                stream.write(data)
                with self._audio_lock:
                    self._audio_bytes_played += len(data)
        except Exception:
            _log("audio", traceback.format_exc())
        finally:
            if stream:
                try: stream.stop_stream(); stream.close()
                except Exception: pass
            if pa:
                try: pa.terminate()
                except Exception: pass

    def _drain_no_pyaudio(self):
        t0 = time.monotonic()
        while self.running and not self._stop_event.is_set():
            data = self.audio_proc.stdout.read(AUDIO_CHUNK)
            if not data: break
            with self._audio_lock:
                self._audio_bytes_played = int(
                    (time.monotonic() - t0) * AUDIO_RATE * BYTES_PER_FRAME)

    def _render_loop(self):
        frame_dur = 1.0 / self.fps
        last_ts   = -1.0
        try:
            while self.running:
                audio_pos = self._audio_clock()
                try:
                    pts, img = self._video_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if pts < audio_pos - frame_dur * 2:
                    continue
                wait = pts - audio_pos
                if wait > 0:
                    deadline = time.monotonic() + wait
                    while self.running and time.monotonic() < deadline:
                        time.sleep(min(0.005, deadline - time.monotonic()))
                if not self.running:
                    break
                self.frame_ready.emit(img)
                if pts - last_ts >= 1.0:
                    self.time_update.emit(pts)
                    last_ts = pts
        except Exception:
            _log("render", traceback.format_exc())

    def stop(self):
        self.running = False
        self._stop_event.set()
        try:
            while True: self._video_queue.get_nowait()
        except queue.Empty:
            pass
        for proc in (self.video_proc, self.audio_proc):
            if proc:
                try: proc.terminate()
                except Exception: pass

class EmbeddedVideoWidget(QWidget):
    ar_changed = pyqtSignal(float)   # испускается когда получен реальный AR видео

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)  # принимаем фокус клавиатуры
        # Expanding по обеим осям — занимаем всё свободное место
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(1, 1)

        self._last_image: QImage = None
        self._duration    = 0.0
        self._current_sec = 0.0
        self._is_playing  = False
        self._url         = ""
        self._video_ar    = 16 / 9   # aspect ratio, обновится из первого кадра
        self._ar_set      = False
        self._volume      = 1.0      # громкость 0.0-1.0
        self._muted       = False
        self._volume_before_mute = 1.0
        self._playback_speed = 1.0   # скорость воспроизведения (пока не реализовано в ffmpeg)
        self._volume_hover = False   # флаг наведения на область громкости
        self._volume_hide_timer = QTimer()
        self._volume_hide_timer.setSingleShot(True)
        self._volume_hide_timer.timeout.connect(self._hide_volume_slider)
        self.worker: AVWorker = None

        # Панель управления — градиент поверх видео как на YouTube
        self.controls = QFrame(self)
        self.controls.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                            stop:0 rgba(0,0,0,200), stop:0.5 rgba(0,0,0,100), stop:1 rgba(0,0,0,0));
                border: none;
                border-bottom-right-radius: 15px;
                border-bottom-left-radius: 15px;
            }
        """)

        # Layout: progress bar вверху, кнопки внизу
        ctrl_layout = QVBoxLayout(self.controls)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(0)

        # Spacer — отодвигает контролы вниз
        ctrl_layout.addStretch()

        # Progress bar
        progress_container = QWidget()
        progress_container.setStyleSheet("background: transparent;")
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(12, 0, 12, 4)
        progress_layout.setSpacing(0)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: rgba(255,255,255,0.3);
                border-radius: 1.5px;
            }
            QSlider::sub-page:horizontal {
                background: #FF0000;
                border-radius: 1.5px;
            }
            QSlider::handle:horizontal {
                background: #FF0000;
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                width: 14px;
                height: 14px;
                margin: -6px 0;
                border-radius: 7px;
            }
        """)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_seek)
        progress_layout.addWidget(self.slider)
        ctrl_layout.addWidget(progress_container)

        # Нижний ряд: play, time, spacer, volume, settings, fullscreen
        bottom_row = QWidget()
        bottom_row.setStyleSheet("background: transparent;")
        bottom_layout = QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(8, 0, 8, 8)
        bottom_layout.setSpacing(8)

        self.left_row = QWidget() 
        self.left_row.setStyleSheet("background: transparent;")
        left_layout = QHBoxLayout(self.left_row)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Play/Pause
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: white;
                font-size: 20px;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
        """)
        self.play_btn.clicked.connect(self._toggle_play)

        # Time label
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("""
            color: white;
            font-family: 'Segoe UI', 'YouTube Sans', 'Roboto';
            font-size: 13px;
            background: transparent;
            padding: 0 4px;
        """)

        left_layout.addWidget(self.play_btn)

        self.volume_container = QWidget()
        self.volume_container.setObjectName("volume_container")
        self.volume_container.installEventFilter(self)
        # Изначально контейнер равен ширине кнопки
        self.volume_container.setFixedWidth(32) 
        self.volume_container.setFixedHeight(36)
        
        vol_layout = QHBoxLayout(self.volume_container)
        vol_layout.setContentsMargins(0, 0, 0, 0)
        vol_layout.setSpacing(0)

        self.volume_btn = QPushButton("🔊")
        self.volume_btn.setFixedSize(32, 32)
        self.volume_btn.setCursor(Qt.PointingHandCursor)
        self.volume_btn.setStyleSheet("background: transparent; color: white; border: none; font-size: 16px;")
        self.volume_btn.clicked.connect(self._toggle_mute)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimumWidth(0)
        self.volume_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.vol_opacity = QGraphicsOpacityEffect(self.volume_slider)
        self.volume_slider.setGraphicsEffect(self.vol_opacity)
        self.vol_opacity.setOpacity(0) # Изначально прозрачен
        self.volume_slider.hide()
        
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 3px; background: rgba(255,255,255,0.3); border-radius: 1.5px; }
            QSlider::sub-page:horizontal { background: white; border-radius: 1.5px; }
            QSlider::handle:horizontal { background: white; width: 10px; height: 10px; margin: -4px 0; border-radius: 5px; }
        """)
        self.volume_slider.valueChanged.connect(self._on_volume_change)

        vol_layout.addWidget(self.volume_btn)
        vol_layout.addWidget(self.volume_slider)
        
        left_layout.addWidget(self.volume_container)

        # Time label
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("""
            color: white;
            font-family: 'Segoe UI', 'YouTube Sans', 'Roboto';
            font-size: 13px;
            background: transparent;
            padding: 0 4px;
        """)

        left_layout.addWidget(self.time_label)
        bottom_layout.addWidget(self.left_row)
        bottom_layout.addStretch()

        # Settings (качество, субтитры)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: white;
                font-size: 18px;
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
        """)
        self.settings_btn.clicked.connect(self._show_settings_menu)
        bottom_layout.addWidget(self.settings_btn)

        # Fullscreen
        self.fs_btn = QPushButton("⛶")
        self.fs_btn.setFixedSize(32, 32)
        self.fs_btn.setCursor(Qt.PointingHandCursor)
        self.fs_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: white;
                font-size: 20px;
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
        """)
        self.fs_btn.clicked.connect(self._toggle_fullscreen)
        bottom_layout.addWidget(self.fs_btn)

        ctrl_layout.addWidget(bottom_row)

        self.controls.hide()

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_controls)

    def eventFilter(self, obj, event):
        # Показываем/скрываем volume_slider при наведении на кнопку или сам слайдер
        if hasattr(self, 'volume_btn') and obj in (self.volume_btn, self.volume_slider, self.volume_container):
            if event.type() == QEvent.Enter:
                self._volume_hover = True
                self._volume_hide_timer.stop()
                # Показываем с задержкой 200ms как на YouTube
                QTimer.singleShot(200, self._show_volume_slider)
            elif event.type() == QEvent.Leave:
                self._volume_hover = False
                # Проверяем через 100ms что курсор действительно ушёл
                QTimer.singleShot(100, self._check_volume_hover)
        return super().eventFilter(obj, event)

    def _show_volume_slider(self):
        if not self._volume_hover: return
        
        self.volume_slider.show()
        self.volume_slider.setVisible(True)

        # Групповая анимация для синхронности
        from PyQt5.QtCore import QParallelAnimationGroup
        self.vol_group = QParallelAnimationGroup()

        # Анимация ширины
        anim_w = QPropertyAnimation(self.volume_container, b"maximumWidth")
        anim_w.setDuration(200)
        anim_w.setEndValue(112)
        anim_w.setEasingCurve(QEasingCurve.OutCubic)

        # Анимация прозрачности
        anim_o = QPropertyAnimation(self.vol_opacity, b"opacity")
        anim_o.setDuration(200)
        anim_o.setEndValue(1.0)

        self.vol_group.addAnimation(anim_w)
        self.vol_group.addAnimation(anim_o)
        self.vol_group.start()

    def _hide_volume_slider(self):
        if hasattr(self, 'vol_group'): self.vol_group.stop()
        
        self.vol_group = QParallelAnimationGroup()

        anim_w = QPropertyAnimation(self.volume_container, b"maximumWidth")
        anim_w.setDuration(200)
        anim_w.setEndValue(32)
        anim_w.setEasingCurve(QEasingCurve.InCubic)

        anim_o = QPropertyAnimation(self.vol_opacity, b"opacity")
        anim_o.setDuration(150) # Прозрачность исчезает чуть быстрее
        anim_o.setEndValue(0.0)

        self.vol_group.addAnimation(anim_w)
        self.vol_group.addAnimation(anim_o)
        
        # Когда всё закончится — ВЫРУБАЕМ видимость совсем
        self.vol_group.finished.connect(self._on_vol_hidden)
        self.vol_group.start()

    def _on_vol_hidden(self):
        if self.volume_container.width() <= 35:
            self.volume_slider.hide()
            self.volume_slider.setVisible(False)

    def _check_volume_hover(self):
        """Проверяем что курсор ушёл и запускаем таймер скрытия."""
        if hasattr(self, 'volume_btn') and not (self.volume_btn.underMouse() or self.volume_slider.underMouse()):
            self._volume_hide_timer.start(500)  # скрываем через 500ms

    def mouseMoveEvent(self, event):
        self._show_controls()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()  # забираем фокус при клике
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        """Клавиатурные шорткаты."""
        key = event.key()
        
        if key == Qt.Key_Space or key == Qt.Key_K:
            # Пробел или K — play/pause
            self._toggle_play()
        elif key == Qt.Key_Left or key == Qt.Key_J:
            # Стрелка влево или J — -5 секунд
            self._skip(-5)
        elif key == Qt.Key_Right or key == Qt.Key_L:
            # Стрелка вправо или L — +5 секунд
            self._skip(5)
        elif key == Qt.Key_Up:
            # Стрелка вверх — +5% громкость
            new_vol = min(100, self.volume_slider.value() + 5)
            self.volume_slider.setValue(new_vol)
        elif key == Qt.Key_Down:
            # Стрелка вниз — -5% громкость
            new_vol = max(0, self.volume_slider.value() - 5)
            self.volume_slider.setValue(new_vol)
        elif key == Qt.Key_M:
            # M — mute/unmute
            self._toggle_mute()
        elif key == Qt.Key_F:
            # F — fullscreen
            self._toggle_fullscreen()
        elif key == Qt.Key_0:
            # 0-9 — перемотка на N*10% длины
            if self._duration > 0:
                self._start_worker(self._url, 0)
        elif Qt.Key_1 <= key <= Qt.Key_9:
            # 1-9 → перемотка на процент
            if self._duration > 0:
                percent = (key - Qt.Key_0) / 10.0
                self._start_worker(self._url, self._duration * percent)
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        self.controls.setGeometry(0, 0, self.width(), self.height())
        self._redraw()
        super().resizeEvent(event)

    def _apply_video_rounding(self, radius):
        """Создает маску, которая обрезает углы самого виджета и всего, что на нем рисуется."""
        path = QPainterPath()
        # Используем self.rect(), так как маска ложится на весь EmbeddedVideoWidget
        rect = QRectF(self.rect())
        path.addRoundedRect(rect, radius, radius)
        
        # Превращаем путь в регион (маску)
        region = QRegion(path.toFillPolygon().toPolygon())
        
        # Устанавливаем маску на текущий виджет
        self.setMask(region)

    def mouseDoubleClickEvent(self, event):
        self._toggle_fullscreen()

    def _show_settings_menu(self):
        """Показать меню настроек."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(28, 28, 28, 240);
                color: white;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px;
                padding: 8px 0;
            }
            QMenu::item {
                padding: 8px 24px 8px 16px;
                background: transparent;
            }
            QMenu::item:selected {
                background-color: rgba(255,255,255,0.1);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255,255,255,0.1);
                margin: 4px 0;
            }
        """)

        # Скорость воспроизведения
        speed_menu = QMenu("Скорость", self)
        speed_menu.setStyleSheet(menu.styleSheet())
        
        speeds = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        for speed in speeds:
            action = QAction(f"{speed}x" + (" (нормальная)" if speed == 1.0 else ""), self)
            action.setCheckable(True)
            if abs(self._playback_speed - speed) < 0.01:
                action.setChecked(True)
            action.triggered.connect(lambda checked, s=speed: self._set_speed(s))
            speed_menu.addAction(action)
        
        menu.addMenu(speed_menu)
        
        # Качество (заглушка — yt-dlp уже выбрал best)
        quality_menu = QMenu("Качество", self)
        quality_menu.setStyleSheet(menu.styleSheet())
        auto_action = QAction("Авто (выбрано)", self)
        auto_action.setCheckable(True)
        auto_action.setChecked(True)
        quality_menu.addAction(auto_action)
        menu.addMenu(quality_menu)

        # Показываем меню над кнопкой
        pos = self.settings_btn.mapToGlobal(self.settings_btn.rect().topLeft())
        menu.exec_(pos)

    def _set_speed(self, speed: float):
        """Установить скорость воспроизведения (требует перезапуск ffmpeg с -filter:a atempo)."""
        self._playback_speed = speed
        # TODO: перезапустить worker с фильтром atempo в audio_cmd
        # Пока просто сохраняем значение
        _log("speed", f"Speed set to {speed}x (not implemented yet)")

    def _show_controls(self):
        self.controls.show()
        self.controls.raise_()
        self.setCursor(Qt.ArrowCursor)
        self._hide_timer.start(3000)

    def _fade_controls(self):
        if self._is_playing:
            self.controls.hide()
            self.setCursor(Qt.BlankCursor)

    # ── Плеер ──────────────────────────────────────────────────────

    def play(self, url: str):
        self._url = url
        self._start_worker(url, 0)

    def stop(self):
        self._stop_worker()
        self._is_playing = False
        self.play_btn.setText("▶")
        self._last_image = None
        self.update()

    def _stop_worker(self):
        if self.worker:
            try:
                self.worker.frame_ready.disconnect()
                self.worker.duration_found.disconnect()
                self.worker.time_update.disconnect()
                self.worker.error_signal.disconnect()
            except Exception:
                pass
            self.worker.stop()
            if not self.worker.wait(5000):
                self.worker.terminate()
                self.worker.wait(1000)
            self.worker = None

    def _start_worker(self, url: str, start_time: float):
        self._current_sec = start_time
        self._ar_set      = False   # сбрасываем AR — будет получен из нового потока
        self._stop_worker()

        self.worker = AVWorker(url, start_time)
        self.worker.set_volume(self._volume)  # применяем текущую громкость
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.duration_found.connect(self._on_duration)
        self.worker.time_update.connect(self._on_time)
        self.worker.error_signal.connect(lambda m: _log("ERROR", m))
        self.worker.start()

        self._is_playing = True
        self.play_btn.setText("⏸")

    def _on_frame(self, img: QImage):
        self._last_image = img
        # Обновляем aspect ratio из реального размера первого кадра
        if not self._ar_set and img.width() > 0 and img.height() > 0:
            self._video_ar = img.width() / img.height()
            self._ar_set   = True
            self.updateGeometry()
            self.ar_changed.emit(self._video_ar)
        self._redraw()

    def _redraw(self):
        if self._last_image:
            self.update()   # вызывает paintEvent

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._last_image:
            return
            
        from PyQt5.QtGui import QPainter, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        iw, ih = self._last_image.width(), self._last_image.height()
        if iw <= 0 or ih <= 0: return

        # Рассчитываем геометрию видео (центрирование и scale)
        ww, wh = self.width(), self.height()
        scale = min(ww / iw, wh / ih)
        dw, dh = iw * scale, ih * scale
        dx, dy = (ww - dw) / 2, (wh - dh) / 2
        video_rect = QRectF(dx, dy, dw, dh)

        # --- КЛЮЧЕВАЯ ЧАСТЬ: Скругление ---
        path = QPainterPath()
        # Создаем скругленный прямоугольник точно по размеру видео кадра
        path.addRoundedRect(video_rect, 15, 15) 
        
        # Устанавливаем область обрезки
        painter.setClipPath(path)
        
        # Рисуем изображение — оно автоматически обрежется по углам path
        painter.drawImage(video_rect, self._last_image)
        painter.end()

    def _on_duration(self, d: float):
        self._duration = d
        self.slider.setRange(0, int(d))
        self._update_time_label()

    def _on_time(self, t: float):
        if not self.slider.isSliderDown():
            self._current_sec = t
            self.slider.setValue(int(t))
            self._update_time_label()

    def _update_time_label(self):
        self.time_label.setText(f"{_fmt(self._current_sec)} / {_fmt(self._duration)}")

    def _on_slider_pressed(self):
        self._hide_timer.stop()

    def _on_seek(self):
        if self._url:
            self._start_worker(self._url, self.slider.value())
        self._show_controls()

    def _on_volume_change(self, value: int):
        """Обработка изменения громкости."""
        self._volume = value / 100.0
        if self.worker:
            self.worker.set_volume(self._volume)
        # Обновляем иконку
        if value == 0:
            self.volume_btn.setText("🔇")
            self._muted = True
        else:
            self.volume_btn.setText("🔊")
            self._muted = False

    def _toggle_mute(self):
        """Mute/unmute."""
        if self._muted:
            # Восстанавливаем громкость
            self.volume_slider.setValue(int(self._volume_before_mute * 100))
        else:
            # Сохраняем текущую громкость и ставим 0
            self._volume_before_mute = self._volume
            self.volume_slider.setValue(0)

    def _skip(self, seconds: int):
        """Перемотка вперёд на N секунд."""
        if self._url:
            new_pos = min(self._current_sec + seconds, self._duration)
            self._start_worker(self._url, new_pos)

    def _toggle_play(self):
        if self._is_playing:
            self._stop_worker()
            self.play_btn.setText("▶")
            self._is_playing = False
        else:
            if self._url:
                self._start_worker(self._url, self.slider.value())

    def _toggle_fullscreen(self):
        top = self
        while top.parent():
            top = top.parent()
        if top.isFullScreen():
            top.showNormal()
        else:
            top.showFullScreen()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)


# ════════════════════════════════════════════════════════════════════
#  RelatedVideoItem
# ════════════════════════════════════════════════════════════════════

class RelatedVideoItem(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.setFixedHeight(94)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("background: transparent; border-radius: 8px;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(168, 94)
        self.thumb_label.setStyleSheet("background-color: #272727; border-radius: 6px;")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumb_label)

        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 4, 0, 4)
        text_layout.setSpacing(2)

        self.title_label = QLabel(data.get('title', 'No Title'))
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(44)
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_label.setStyleSheet("color: #f1f1f1; background: transparent;")

        self.channel_label = QLabel(data.get('channel', 'Unknown'))
        self.channel_label.setFont(QFont("Segoe UI", 9))
        self.channel_label.setStyleSheet("color: #aaaaaa; background: transparent;")

        self.duration_label = QLabel(data.get('duration', ''))
        self.duration_label.setFont(QFont("Segoe UI", 9))
        self.duration_label.setStyleSheet("color: #aaaaaa; background: transparent;")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.channel_label)
        text_layout.addWidget(self.duration_label)
        text_layout.addStretch()
        layout.addWidget(text_widget, stretch=1)

    def set_thumbnail(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(168, 94, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)

    def enterEvent(self, e):
        self.setStyleSheet("background: #1f1f1f; border-radius: 8px;")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet("background: transparent; border-radius: 8px;")
        super().leaveEvent(e)


# ════════════════════════════════════════════════════════════════════
#  NativePlayer — главный виджет страницы плеера
# ════════════════════════════════════════════════════════════════════

class NativePlayer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0f0f0f;")

        self._current_data: dict = {}
        self._related_items: list = []

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 16, 0, 0)
        root.setSpacing(24)

        # ── Левая колонка ──────────────────────────────────────────
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        back_row = QHBoxLayout()
        self.back_btn = QPushButton("← Назад")
        self.back_btn.setFixedSize(90, 32)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet('''
            QPushButton {
                background-color: #272727; color: #f1f1f1;
                border: none; border-radius: 6px;
                font-size: 13px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background-color: #3f3f3f; }
        ''')
        back_row.addWidget(self.back_btn)
        back_row.addStretch()
        left_layout.addLayout(back_row)
        left_layout.addSpacing(8)

        # Видеоплеер — высота вычисляется динамически по AR и ширине левой колонки
        self.video_widget = EmbeddedVideoWidget()
        self.video_widget.ar_changed.connect(self._update_video_height)
        left_layout.addWidget(self.video_widget)  # без stretch

        # Инфо под видео
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        info_scroll.setFixedHeight(130)

        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent;")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 12, 0, 0)
        info_layout.setSpacing(6)

        self.title_label = QLabel("Загрузка...")
        self.title_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.title_label.setStyleSheet("color: #f1f1f1;")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(12)

        self.avatar_label = QLabel("?")
        self.avatar_label.setFixedSize(36, 36)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.avatar_label.setStyleSheet(
            "background-color: #3f3f3f; color: #aaa; border-radius: 18px;")

        channel_col = QVBoxLayout()
        channel_col.setSpacing(0)
        self.channel_label = QLabel("Канал")
        self.channel_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.channel_label.setStyleSheet("color: #f1f1f1;")
        self.subs_label = QLabel("")
        self.subs_label.setFont(QFont("Segoe UI", 9))
        self.subs_label.setStyleSheet("color: #aaaaaa;")
        channel_col.addWidget(self.channel_label)
        channel_col.addWidget(self.subs_label)

        self.like_btn  = self._action_btn("👍  Нравится")
        self.share_btn = self._action_btn("↗  Поделиться")
        self.dl_btn    = self._action_btn("⬇  Скачать")

        channel_row.addWidget(self.avatar_label)
        channel_row.addLayout(channel_col)
        channel_row.addStretch()
        channel_row.addWidget(self.like_btn)
        channel_row.addWidget(self.share_btn)
        channel_row.addWidget(self.dl_btn)
        info_layout.addLayout(channel_row)

        self.meta_label = QLabel("")
        self.meta_label.setFont(QFont("Segoe UI", 10))
        self.meta_label.setStyleSheet("color: #aaaaaa;")
        info_layout.addWidget(self.meta_label)

        info_scroll.setWidget(info_widget)
        left_layout.addWidget(info_scroll)

        root.addWidget(left, stretch=1)

        # ── Правая колонка: похожие видео ──────────────────────────
        right = QWidget()
        right.setFixedWidth(402)
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 16, 0)
        right_layout.setSpacing(8)

        related_title = QLabel("Похожие видео")
        related_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        related_title.setStyleSheet("color: #f1f1f1;")
        right_layout.addWidget(related_title)

        self.related_scroll = QScrollArea()
        self.related_scroll.setWidgetResizable(True)
        self.related_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.related_scroll.setStyleSheet('''
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 6px; }
            QScrollBar::handle:vertical { background: #3f3f3f; border-radius: 3px; }
        ''')

        self.related_container = QWidget()
        self.related_container.setStyleSheet("background: transparent;")
        self.related_list_layout = QVBoxLayout(self.related_container)
        self.related_list_layout.setContentsMargins(0, 0, 0, 0)
        self.related_list_layout.setSpacing(4)
        self.related_list_layout.addStretch()

        self.related_scroll.setWidget(self.related_container)
        right_layout.addWidget(self.related_scroll, stretch=1)

        root.addWidget(right)

        # Совместимость с main.py
        self.status_label = QLabel()

    def _action_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet('''
            QPushButton {
                background-color: #272727; color: #f1f1f1;
                border: none; border-radius: 17px;
                font-size: 12px; font-family: 'Segoe UI'; padding: 0 14px;
            }
            QPushButton:hover { background-color: #3f3f3f; }
        ''')
        return btn

    # ── Публичный API ───────────────────────────────────────────────

    def set_video_info(self, data: dict):
        self._current_data = data
        title   = data.get('title', '')
        channel = data.get('channel', '')
        self.title_label.setText(title)
        self.channel_label.setText(channel)
        self.avatar_label.setText(channel[0].upper() if channel else '?')
        views = data.get('view_count', '')
        if views:
            try:
                v = int(views)
                views_str = (f"{v/1_000_000:.1f} млн просмотров" if v >= 1_000_000
                             else f"{v/1_000:.0f} тыс. просмотров" if v >= 1_000
                             else f"{v} просмотров")
            except (ValueError, TypeError):
                views_str = str(views)
            self.meta_label.setText(views_str)

    def set_related(self, items: list):
        while self.related_list_layout.count() > 1:
            item = self.related_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._related_items = items
        for data in items[:20]:
            card = RelatedVideoItem(data)
            self.related_list_layout.insertWidget(
                self.related_list_layout.count() - 1, card)

    def play_raw_url(self, url: str):
        """Запустить воспроизведение по прямой ссылке на поток."""
        self.video_widget.play(url)

    def stop(self):
        """Остановить воспроизведение."""
        self.video_widget.stop()

    def _update_video_height(self, ar: float = None):
        """Пересчитывает высоту video_widget по текущей ширине и AR."""
        if ar is not None:
            self.video_widget._video_ar = ar
        ar = self.video_widget._video_ar
        if ar <= 0:
            return
        w = self.video_widget.width()
        if w <= 0:
            return
        h = int(w / ar)
        self.video_widget.setFixedHeight(h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_video_height()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)