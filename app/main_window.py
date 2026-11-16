from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QFrame, QSlider, QComboBox, QCheckBox, QSplitter,
    QMessageBox, QGroupBox, QFormLayout, QScrollArea,
)

from engine.audio.playback import PlaybackEngine
from engine.audio.source import AudioSource
from engine.visual.assets import AssetCatalog
from engine.visual.canvas import CompositionCanvas
from engine.visual.compositor import VisualCompositor
from engine.visual.generators import GeneratorSettings

ROOT = Path(__file__).resolve().parents[1]


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


class SourceRow(QWidget):
    def __init__(self, source: AudioSource, track_id: str, remove_callback, parent=None):
        super().__init__(parent)
        self.source = source
        self.track_id = track_id
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(5)

        name = QLabel(source.name)
        name.setToolTip(
            f"{source.path}\n{source.sample_rate} Hz · {source.channels} ch · {format_time(source.duration)}")
        name.setMinimumWidth(110)
        name.setMaximumWidth(180)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        mute = QCheckBox("M")
        solo = QCheckBox("S")
        analysis = QCheckBox("AN")
        analysis.setChecked(True)
        gain = QSlider(Qt.Orientation.Horizontal)
        gain.setRange(0, 200)
        gain.setValue(100)
        gain.setFixedWidth(78)
        pan = QSlider(Qt.Orientation.Horizontal)
        pan.setRange(-100, 100)
        pan.setValue(0)
        pan.setFixedWidth(64)
        remove = QPushButton("×")
        remove.setFixedWidth(24)
        remove.setToolTip("Remove source")

        for widget in (name, mute, solo, analysis, QLabel("G"), gain, QLabel("P"), pan, remove):
            row.addWidget(widget)
        row.addStretch(1)

        mute.toggled.connect(lambda value: setattr(source, "muted", value))
        solo.toggled.connect(lambda value: setattr(source, "solo", value))
        analysis.toggled.connect(lambda value: setattr(source, "analysis_enabled", value))
        gain.valueChanged.connect(lambda value: setattr(source, "gain", value / 100.0))
        pan.valueChanged.connect(lambda value: setattr(source, "pan", value / 100.0))
        remove.clicked.connect(lambda: remove_callback(self.track_id, self))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("eli_lab / WAVEFORMING")
        self.resize(1560, 980)
        self.sources: dict[str, AudioSource] = {}
        self._last_packet: dict = {}
        self._last_position = 0.0
        self._settings = GeneratorSettings()

        self.assets = AssetCatalog(ROOT / "screens")
        self.compositor = VisualCompositor(self.assets)
        self.audio = PlaybackEngine(self)
        self.audio.state_changed.connect(self._on_playback_state)
        self.audio.position_changed.connect(self._on_position)
        self.audio.features_ready.connect(self._on_features)
        self.audio.error.connect(self._show_audio_error)

        self._build_menu()
        self._build_ui()
        self._apply_style()
        self._configure_analysis()
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self._render_frame)
        self._render_frame()

    def _build_menu(self):
        menu = self.menuBar().addMenu("PROJECT")
        add = QAction("Import audio source…", self)
        add.setShortcut("Ctrl+O")
        add.triggered.connect(self.import_audio)
        menu.addAction(add)
        menu.addSeparator()
        stop = QAction("Stop playback", self)
        stop.setShortcut("Space")
        stop.triggered.connect(self.toggle_playback)
        menu.addAction(stop)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(16, 12, 16, 14)
        main.setSpacing(10)

        header = QHBoxLayout()
        logo = QLabel()
        logo_path = ROOT / "resources" / "widgets" / "eli_lab_waveformer_logo.png"
        if logo_path.is_file():
            logo_pixmap = QPixmap(str(logo_path))
            logo.setPixmap(logo_pixmap.scaled(
                132, 54, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            logo.setStyleSheet("background:#e8e8e8; padding:3px; border:1px solid #555;")
            logo.setToolTip("eli_lab / WAVEFORMING")
        brand = QLabel("eli_lab  /  WAVEFORMING")
        brand.setObjectName("brand")
        subtitle = QLabel("ABSTRACT AUDIO-VISUAL COMPOSITION  ·  1920 × 1440")
        subtitle.setObjectName("muted")
        if not logo.pixmap().isNull():
            header.addWidget(logo)
        header.addWidget(brand)
        header.addStretch()
        header.addWidget(subtitle)
        main.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(split, 1)

        left_content = QWidget()
        left = QVBoxLayout(left_content)
        left.setContentsMargins(0, 0, 10, 0)
        left.setSpacing(9)

        source_header = QHBoxLayout()
        source_title = QLabel("SOUND SOURCES")
        source_title.setObjectName("section")
        add_button = QPushButton("+ ADD SOURCE")
        add_button.clicked.connect(self.import_audio)
        source_header.addWidget(source_title)
        source_header.addStretch()
        source_header.addWidget(add_button)
        left.addLayout(source_header)

        source_panel = QFrame()
        source_panel.setObjectName("panel")
        self.source_rows = QVBoxLayout(source_panel)
        self.source_rows.setContentsMargins(4, 4, 4, 4)
        self.source_rows.setSpacing(3)
        self.source_rows.addStretch(1)
        source_scroll = QScrollArea()
        source_scroll.setWidgetResizable(True)
        source_scroll.setFrameShape(QFrame.Shape.NoFrame)
        source_scroll.setMaximumHeight(205)
        source_scroll.setWidget(source_panel)
        left.addWidget(source_scroll)

        analysis_box = QGroupBox("ANALYSIS FIELD")
        analysis_form = QFormLayout(analysis_box)
        self.fft = QComboBox()
        self.fft.addItems(["1024", "2048", "4096", "8192", "16384"])
        self.fft.setCurrentText("4096")
        self.window = QComboBox()
        self.window.addItems(["Hann", "Hamming", "Blackman"])
        self.bands = QComboBox()
        self.bands.addItems(["24", "48", "64", "96", "128"])
        self.bands.setCurrentText("64")
        analysis_form.addRow("FFT SIZE", self.fft)
        analysis_form.addRow("WINDOW", self.window)
        analysis_form.addRow("LOG BANDS", self.bands)
        left.addWidget(analysis_box)
        self.fft.currentTextChanged.connect(self._configure_analysis)
        self.window.currentTextChanged.connect(self._configure_analysis)
        self.bands.currentTextChanged.connect(self._configure_analysis)

        generator_box = QGroupBox("MATHEMATICAL GENERATOR")
        generator_form = QFormLayout(generator_box)
        self.generator = QComboBox()
        self.generator.addItems(self.compositor.generator_names())
        self.complexity = self._make_slider(5, 100, 58)
        self.motion = self._make_slider(0, 100, 42)
        self.sensitivity = self._make_slider(0, 200, 110)
        generator_form.addRow("STRUCTURE", self.generator)
        generator_form.addRow("COMPLEXITY", self.complexity)
        generator_form.addRow("MOTION", self.motion)
        generator_form.addRow("AUDIO RESPONSE", self.sensitivity)
        left.addWidget(generator_box)
        self.generator.currentTextChanged.connect(self._render_frame)
        self.complexity.valueChanged.connect(self._settings_changed)
        self.motion.valueChanged.connect(self._settings_changed)
        self.sensitivity.valueChanged.connect(self._settings_changed)

        composition_box = QGroupBox("SCREEN COMPOSITION")
        composition_form = QFormLayout(composition_box)
        self.screen = QComboBox()
        self.screen.addItems(["No guide", *self.assets.screen_names()])
        self.screen.setCurrentText("SCREEN 1 / BLACK")
        self.pass_map = QComboBox()
        self.pass_map.addItems(["None", *self.assets.pass_names()])
        self.blend = QComboBox()
        self.blend.addItems(["Normal", "Add", "Multiply", "Screen", "Difference", "Overlay"])
        self.opacity = self._make_slider(0, 100, 100)
        composition_form.addRow("SCREEN GUIDE", self.screen)
        composition_form.addRow("SCREEN PASS", self.pass_map)
        composition_form.addRow("PASS BLEND", self.blend)
        composition_form.addRow("LAYER OPACITY", self.opacity)
        left.addWidget(composition_box)
        for control in (self.screen, self.pass_map, self.blend):
            control.currentTextChanged.connect(self._render_frame)
        self.opacity.valueChanged.connect(self._render_frame)
        left.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left_content)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_title = QLabel("COMPOSITION VIEW")
        preview_title.setObjectName("section")
        self.zoom = QComboBox()
        self.zoom.addItems(["FIT", "50%", "66%", "75%", "100%"])
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_header.addWidget(QLabel("CANVAS"))
        preview_header.addWidget(self.zoom)
        right_layout.addLayout(preview_header)

        self.canvas = CompositionCanvas(self.assets)
        right_layout.addWidget(self.canvas, 1)

        transport = QHBoxLayout()
        self.play_button = QPushButton("▶  PLAY")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("■  STOP")
        self.stop_button.clicked.connect(self.stop_playback)
        self.loop_check = QCheckBox("LOOP")
        self.loop_check.toggled.connect(self.audio.set_loop)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 10000)
        self.seek.setValue(0)
        self.seek.sliderReleased.connect(self._seek_from_slider)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        self.status = QLabel("NO AUDIO LOADED")
        self.status.setObjectName("muted")
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.loop_check)
        transport.addWidget(self.seek, 1)
        transport.addWidget(self.time_label)
        right_layout.addLayout(transport)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("OUTPUT  1920 × 1440"))
        footer.addStretch()
        footer.addWidget(self.status)
        right_layout.addLayout(footer)

        split.addWidget(left_scroll)
        split.addWidget(right)
        split.setSizes([470, 1040])
        split.setStretchFactor(1, 1)

    @staticmethod
    def _make_slider(minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def import_audio(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import audio sources", "",
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg *.mp3);;All files (*)",
        )
        for filename in paths:
            if len(self.sources) >= 7:
                QMessageBox.information(self, "Source limit", "The project supports up to seven audio sources.")
                break
            try:
                source = AudioSource.from_file(Path(filename))
                track_id = self.audio.add_source(source)
                self.sources[track_id] = source
                row = SourceRow(source, track_id, self._remove_source)
                self.source_rows.insertWidget(self.source_rows.count() - 1, row)
            except Exception as exc:
                QMessageBox.warning(self, "Audio import failed", f"{Path(filename).name}\n{exc}")
        self._update_status()
        self._update_time_label()
        self._render_frame()

    def _remove_source(self, track_id: str, row: SourceRow) -> None:
        self.audio.remove_source(track_id)
        self.sources.pop(track_id, None)
        row.deleteLater()
        self._update_status()
        self._update_time_label()
        self._render_frame()

    def _configure_analysis(self, *_):
        if not hasattr(self, "audio"):
            return
        self.audio.configure_analysis(int(self.fft.currentText()), int(self.bands.currentText()),
                                      self.window.currentText().lower())

    def _settings_changed(self, *_):
        self._settings.complexity = float(self.complexity.value())
        self._settings.motion = float(self.motion.value())
        self._settings.sensitivity = float(self.sensitivity.value())
        self._render_frame()

    def _render_frame(self, *_):
        image = self.compositor.render(
            packet=self._last_packet,
            seconds=self._last_position,
            generator=self.generator.currentText(),
            settings=self._settings,
            screen=self.screen.currentText(),
            screen_pass=self.pass_map.currentText(),
            blend=self.blend.currentText(),
            opacity=self.opacity.value() / 100.0,
        )
        self.canvas.set_frame(image)

    def _on_features(self, packet: dict) -> None:
        self._last_packet = packet
        if not self.audio.is_playing:
            self._render_frame()

    def _on_playback_state(self, playing: bool) -> None:
        self.play_button.setText("Ⅱ  PAUSE" if playing else "▶  PLAY")
        if playing:
            self._render_timer.start()
        else:
            self._render_timer.stop()
        self._update_status()

    def _on_position(self, seconds: float) -> None:
        self._last_position = seconds
        self._update_time_label()
        duration = self.audio.duration
        if duration > 0 and not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(int(np_clip(seconds / duration, 0.0, 1.0) * 10000))
            self.seek.blockSignals(False)

    def _seek_from_slider(self) -> None:
        duration = self.audio.duration
        if duration > 0:
            self.audio.seek((self.seek.value() / 10000.0) * duration)
            self._render_frame()

    def _update_time_label(self) -> None:
        self.time_label.setText(f"{format_time(self._last_position)} / {format_time(self.audio.duration)}")

    def _update_status(self) -> None:
        count = len(self.sources)
        state = "PLAYING" if self.audio.is_playing else "PAUSED" if self._last_position > 0 else "READY"
        if count:
            self.status.setText(f"{state}  ·  {count:02d} / 07 SOURCES")
        else:
            self.status.setText("NO AUDIO LOADED")

    def toggle_playback(self):
        if self.audio.is_playing:
            self.audio.pause()
        else:
            if self.audio.duration > 0 and self.audio.position >= self.audio.duration - 0.03:
                self.audio.seek(0.0)
                self._last_position = 0.0
            self.audio.play()

    def stop_playback(self):
        self.audio.stop()
        self._last_position = 0.0
        self._render_frame()

    def _show_audio_error(self, message: str) -> None:
        QMessageBox.warning(self, "WAVEFORMING audio engine", message)

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#111; color:#e7e7e7; font-family:'Segoe UI'; font-size:10pt; }
        QMenuBar,QMenu { background:#181818; color:#e7e7e7; }
        QMenuBar::item { padding:6px 10px; } QMenuBar::item:selected,QMenu::item:selected { background:#333; }
        QLabel#brand { font-size:15pt; font-weight:700; letter-spacing:2px; }
        QLabel#section { font-size:10pt; font-weight:700; letter-spacing:1.5px; }
        QLabel#muted { color:#888; font-size:9pt; }
        QFrame#panel,QGroupBox { background:#191919; border:1px solid #363636; border-radius:3px; }
        QGroupBox { margin-top:12px; padding:12px 8px 8px; font-weight:700; color:#aaa; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        QPushButton,QComboBox { background:#242424; border:1px solid #454545; padding:7px 10px; border-radius:2px; }
        QPushButton:hover { background:#303030; border-color:#777; }
        QPushButton:disabled { color:#555; }
        QComboBox::drop-down { border:0; width:18px; }
        QSlider::groove:horizontal { height:3px; background:#494949; }
        QSlider::handle:horizontal { background:#dedede; width:10px; margin:-4px 0; border-radius:5px; }
        QCheckBox { spacing:5px; color:#aaa; }
        QScrollArea { border:0; background:transparent; }
        """)

    def closeEvent(self, event):
        self._render_timer.stop()
        self.audio.close()
        super().closeEvent(event)


def np_clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))
