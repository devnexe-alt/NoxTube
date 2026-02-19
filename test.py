import sys
import subprocess
import json
import time
import threading
import queue
import traceback

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QSlider, QLabel, QFrame, QSizePolicy)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QEvent

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("WARNING: pyaudio not found. Install: pip install pyaudio")

AUDIO_RATE       = 44100
AUDIO_CHANNELS   = 2
AUDIO_CHUNK      = 4096
BYTES_PER_SAMPLE = 2
BYTES_PER_FRAME  = BYTES_PER_SAMPLE * AUDIO_CHANNELS


def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


class AVWorker(QThread):
    frame_ready    = pyqtSignal(QImage)
    duration_found = pyqtSignal(float)
    time_update    = pyqtSignal(float)
    error_signal   = pyqtSignal(str)

    def __init__(self, url, start_time=0):
        super().__init__()
        self.url        = url
        self.start_time = float(start_time)
        self.width      = 0    # будет получен из yt-dlp
        self.height     = 0
        self.running    = True
        self.fps        = 30.0

        self.video_proc = None
        self.audio_proc = None

        self._video_queue        = queue.Queue(maxsize=30)
        self._audio_bytes_played = 0
        self._audio_lock         = threading.Lock()

        # Событие для сигнала аудио-потоку что надо завершиться
        # (не трогаем PyAudio снаружи — только через это событие)
        self._stop_event = threading.Event()

    # ── helpers ────────────────────────────────────────────────────

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

    # ── main thread ────────────────────────────────────────────────

    def run(self):
        try:
            self._run_inner()
        except Exception:
            log("worker.run", traceback.format_exc())

    def _run_inner(self):
        log("worker", f"starting from {self.start_time:.1f}s")

        direct_url, duration, fps, width, height = self._resolve_url()
        if direct_url is None:
            return
        self.fps    = fps
        self.width  = width
        self.height = height
        self.duration_found.emit(duration)
        log("worker", f"url resolved, duration={duration:.1f}s fps={fps} size={width}x{height}")

        si = self._si()

        video_cmd = [
            'ffmpeg', '-ss', str(self.start_time),
            '-reconnect', '1', '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-i', direct_url,
            '-an',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            # без -s — декодируем в нативном разрешении, Qt сам масштабирует
            '-'
        ]
        audio_cmd = [
            'ffmpeg', '-ss', str(self.start_time),
            '-reconnect', '1', '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-i', direct_url,
            '-vn',
            '-f', 's16le', '-ar', str(AUDIO_RATE), '-ac', str(AUDIO_CHANNELS),
            '-'
        ]

        try:
            self.video_proc = subprocess.Popen(
                video_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=self.width * self.height * 3 * 4, startupinfo=si
            )
            log("worker", "video ffmpeg started")
        except Exception:
            log("worker", "failed to start video ffmpeg\n" + traceback.format_exc())
            return

        try:
            self.audio_proc = subprocess.Popen(
                audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=AUDIO_CHUNK * 8, startupinfo=si
            )
            log("worker", "audio ffmpeg started")
        except Exception:
            log("worker", "failed to start audio ffmpeg\n" + traceback.format_exc())
            self.video_proc.terminate()
            return

        vt = threading.Thread(target=self._read_video, daemon=True, name="VideoReader")
        at = threading.Thread(target=self._play_audio, daemon=True, name="AudioPlayer")
        vt.start()
        at.start()

        self._render_loop()

        log("worker", "render loop ended, joining threads")
        # Ждём аудио-поток — он сам закроет PyAudio
        at.join(timeout=3)
        vt.join(timeout=2)
        log("worker", "done")

    # ── url resolve ────────────────────────────────────────────────

    def _resolve_url(self):
        cmd = [
            "yt-dlp", "--no-warnings", "--print-json",
            "-f", "best[ext=mp4]/best", self.url
        ]
        try:
            res = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, startupinfo=self._si()
            )
            data = json.loads(res.decode())
            return data['url'], float(data.get('duration', 0)), float(data.get('fps', 30) or 30), int(data.get('width', 1280) or 1280), int(data.get('height', 720) or 720)
        except Exception:
            log("resolve", traceback.format_exc())
            self.error_signal.emit("yt-dlp failed")
            return None, 0, 30, 1280, 720

    # ── video reader thread ────────────────────────────────────────

    def _read_video(self):
        log("video_reader", "started")
        frame_size  = self.width * self.height * 3
        frame_index = 0
        try:
            while self.running:
                raw = self.video_proc.stdout.read(frame_size)
                if len(raw) < frame_size:
                    log("video_reader", f"stream ended at frame {frame_index}")
                    break
                pts = self.start_time + frame_index / self.fps
                img = QImage(raw, self.width, self.height, QImage.Format_RGB888).copy()
                while self.running:
                    try:
                        self._video_queue.put((pts, img), timeout=0.05)
                        break
                    except queue.Full:
                        continue
                frame_index += 1
        except Exception:
            log("video_reader", traceback.format_exc())
        log("video_reader", "exited")

    # ── audio player thread ────────────────────────────────────────

    def _play_audio(self):
        log("audio", "started")
        if not PYAUDIO_AVAILABLE:
            self._drain_audio_no_pyaudio()
            return

        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_RATE,
                output=True,
                frames_per_buffer=AUDIO_CHUNK // BYTES_PER_FRAME
            )
            log("audio", "stream opened")

            while self.running and not self._stop_event.is_set():
                data = self.audio_proc.stdout.read(AUDIO_CHUNK)
                if not data:
                    log("audio", "stream ended")
                    break
                # Проверяем ещё раз после блокирующего read()
                if not self.running or self._stop_event.is_set():
                    break
                stream.write(data)
                with self._audio_lock:
                    self._audio_bytes_played += len(data)

        except Exception:
            log("audio", traceback.format_exc())
        finally:
            # PyAudio закрывается ТОЛЬКО здесь, в своём потоке
            log("audio", "closing stream...")
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    log("audio", "stream close error: " + traceback.format_exc())
            if pa:
                try:
                    pa.terminate()
                except Exception:
                    log("audio", "pa.terminate error: " + traceback.format_exc())
            log("audio", "exited")

    def _drain_audio_no_pyaudio(self):
        """Синхронизация по реальному времени если нет PyAudio."""
        t0 = time.monotonic()
        while self.running and not self._stop_event.is_set():
            data = self.audio_proc.stdout.read(AUDIO_CHUNK)
            if not data:
                break
            elapsed = time.monotonic() - t0
            with self._audio_lock:
                self._audio_bytes_played = int(elapsed * AUDIO_RATE * BYTES_PER_FRAME)
        log("audio", "exited (no pyaudio)")

    # ── render loop ────────────────────────────────────────────────

    def _render_loop(self):
        log("render", "started")
        frame_dur = 1.0 / self.fps
        last_ts   = -1.0
        try:
            while self.running:
                audio_pos = self._audio_clock()

                try:
                    pts, img = self._video_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # пропускаем устаревшие кадры
                if pts < audio_pos - frame_dur * 2:
                    continue

                # ждём если кадр опережает аудио
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
            log("render", traceback.format_exc())
        log("render", "exited")

    # ── stop ───────────────────────────────────────────────────────

    def stop(self):
        log("worker", "stop() called")
        self.running = False

        # Сигнализируем аудио-потоку через event (не трогаем PyAudio!)
        self._stop_event.set()

        # Дрейним очередь чтобы _read_video не завис на put()
        try:
            while True:
                self._video_queue.get_nowait()
        except queue.Empty:
            pass

        # Завершаем ffmpeg-процессы — это разблокирует блокирующий read()
        # в аудио и видео потоках, после чего они сами завершатся
        for name, proc in [("video", self.video_proc), ("audio", self.audio_proc)]:
            if proc:
                try:
                    proc.terminate()
                    log("worker", f"{name} proc terminated")
                except Exception:
                    log("worker", f"error terminating {name}: " + traceback.format_exc())


# ══════════════════════════════════════════════════════════════════
class VideoPlayer(QWidget):
    def __init__(self, url):
        super().__init__()
        self.url         = url
        self.duration    = 0
        self.current_sec = 0
        self.is_playing  = True
        self.last_image  = None
        self.worker      = None

        self.hide_timer = QTimer()
        self._init_ui()
        self._start_worker(0)

    def _init_ui(self):
        self.setWindowTitle("NoxTube")
        self.resize(1100, 650)
        self.setStyleSheet("background-color: #050505;")
        self.setMouseTracking(True)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMouseTracking(True)
        self.video_label.installEventFilter(self)
        self.video_label.setMinimumSize(1, 1)
        self.video_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Ignored
        )
        self.main_layout.addWidget(self.video_label)

        self.controls_panel = QFrame(self)
        self.controls_panel.setFixedHeight(90)
        self.controls_panel.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                            stop:0 rgba(0,0,0,240), stop:1 rgba(0,0,0,0));
                border: none;
            }
            QSlider::groove:horizontal {
                height: 4px; background: rgba(255,255,255,0.3); border-radius: 2px;
            }
            QSlider::sub-page:horizontal { background: #FF0000; border-radius: 2px; }
            QSlider::handle:horizontal {
                background: #FF0000; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }
            QPushButton {
                background: transparent; color: white;
                font-size: 22px; border-radius: 20px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); }
            QLabel { color: #EEE; font-family: 'Segoe UI'; font-size: 14px; }
        """)

        ctrl_vbox = QVBoxLayout(self.controls_panel)
        ctrl_vbox.setContentsMargins(20, 0, 20, 10)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._seek_video)
        ctrl_vbox.addWidget(self.slider)

        bottom = QHBoxLayout()
        self.play_btn = QPushButton("⏸")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self._toggle_play)

        self.time_label = QLabel("00:00 / 00:00")

        self.fs_btn = QPushButton("⛶")
        self.fs_btn.setFixedSize(40, 40)
        self.fs_btn.clicked.connect(self._toggle_fullscreen)

        bottom.addWidget(self.play_btn)
        bottom.addSpacing(15)
        bottom.addWidget(self.time_label)
        bottom.addStretch()
        bottom.addWidget(self.fs_btn)
        ctrl_vbox.addLayout(bottom)

        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out_controls)

    def _start_worker(self, start_time):
        log("player", f"_start_worker({start_time})")
        self.current_sec = float(start_time)

        if self.worker:
            # Отключаем сигналы ДО остановки — иначе дедлок
            try:
                self.worker.frame_ready.disconnect()
                self.worker.duration_found.disconnect()
                self.worker.time_update.disconnect()
                self.worker.error_signal.disconnect()
            except Exception:
                pass

            self.worker.stop()

            if not self.worker.wait(5000):
                log("player", "worker did not stop in time, terminating")
                self.worker.terminate()
                self.worker.wait(1000)

        self.worker = AVWorker(self.url, start_time)
        self.worker.frame_ready.connect(self._update_frame)
        self.worker.duration_found.connect(self._set_duration)
        self.worker.time_update.connect(self._sync_time)
        self.worker.error_signal.connect(lambda msg: log("ERROR", msg))
        self.worker.start()
        log("player", "new worker started")

    def _update_frame(self, img):
        self.last_image = img
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self):
        if self.last_image:
            pix = QPixmap.fromImage(self.last_image).scaled(
                self.video_label.size(), Qt.KeepAspectRatio, Qt.FastTransformation
            )
            self.video_label.setPixmap(pix)

    def _set_duration(self, d):
        self.duration = d
        self.slider.setRange(0, int(d))
        self._update_time_label()

    def _sync_time(self, t):
        if not self.slider.isSliderDown():
            self.current_sec = t
            self.slider.setValue(int(t))
            self._update_time_label()

    def _update_time_label(self):
        self.time_label.setText(f"{self._fmt(self.current_sec)} / {self._fmt(self.duration)}")

    @staticmethod
    def _fmt(s):
        s = int(s)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _on_slider_pressed(self):
        self.hide_timer.stop()

    def _seek_video(self):
        self._start_worker(self.slider.value())
        self._show_controls()

    def _toggle_play(self):
        if self.is_playing:
            self.worker.stop()
            self.play_btn.setText("▶")
        else:
            self._start_worker(self.slider.value())
            self.play_btn.setText("⏸")
        self.is_playing = not self.is_playing

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def eventFilter(self, obj, event):
        if obj == self.video_label and event.type() == QEvent.MouseMove:
            self._show_controls()
        return super().eventFilter(obj, event)

    def _show_controls(self):
        self.controls_panel.show()
        self.controls_panel.raise_()
        self.setCursor(Qt.ArrowCursor)
        self.hide_timer.start(3000)

    def _fade_out_controls(self):
        if self.is_playing:
            self.controls_panel.hide()
            self.setCursor(Qt.BlankCursor)

    def resizeEvent(self, event):
        self.controls_panel.setGeometry(0, self.height() - 90, self.width(), 90)
        self._apply_scaled_pixmap()
        super().resizeEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._toggle_fullscreen()

    def closeEvent(self, event):
        log("player", "closeEvent")
        if self.worker:
            try:
                self.worker.frame_ready.disconnect()
                self.worker.duration_found.disconnect()
                self.worker.time_update.disconnect()
                self.worker.error_signal.disconnect()
            except Exception:
                pass
            self.worker.stop()
            self.worker.wait(3000)
        super().closeEvent(event)


if __name__ == "__main__":
    if not PYAUDIO_AVAILABLE:
        print("Install pyaudio: pip install pyaudio")

    app = QApplication(sys.argv)
    player = VideoPlayer("https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    player.show()
    sys.exit(app.exec_())