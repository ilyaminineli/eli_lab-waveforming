from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QFrame, QSlider, QComboBox, QCheckBox, QSplitter,
    QMessageBox, QGroupBox, QFormLayout, QScrollArea, QListWidget,
    QListWidgetItem, QAbstractItemView,
)

from engine.audio.playback import PlaybackEngine
from engine.audio.source import AudioSource
from engine.visual.assets import AssetCatalog
from engine.visual.canvas import CompositionCanvas
from engine.visual.compositor import VisualCompositor
from engine.visual.generators import GeneratorSettings
from engine.visual.layers import LayerStack, VisualLayer

ROOT = Path(__file__).resolve().parents[1]


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


class SourceRow(QWidget):
    def __init__(self, source: AudioSource, track_id: str, remove_callback, parent=None):
        super().__init__(parent)
        self.source = source
        self.track_id = track_id
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 4, 7, 4)
        row.setSpacing(5)

        name = QLabel(source.name)
        name.setToolTip(
            f"{source.path}\n{source.sample_rate} Hz · {source.channels} ch · {format_time(source.duration)}"
        )
        name.setMinimumWidth(85)
        name.setMaximumWidth(155)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        mute, solo, analysis = QCheckBox("M"), QCheckBox("S"), QCheckBox("AN")
        analysis.setChecked(True)
        gain = QSlider(Qt.Orientation.Horizontal)
        gain.setRange(0, 200)
        gain.setValue(100)
        gain.setFixedWidth(68)
        pan = QSlider(Qt.Orientation.Horizontal)
        pan.setRange(-100, 100)
        pan.setValue(0)
        pan.setFixedWidth(58)
        remove = QPushButton("×")
        remove.setFixedWidth(23)
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
        self.resize(1640, 1000)
        self.sources: dict[str, AudioSource] = {}
        self._last_packet: dict = {}
        self._last_position = 0.0
        self._settings = GeneratorSettings()
        self.layer_stack = LayerStack()
        self._updating_layer_controls = False
        self._item_ids: dict[str, QListWidgetItem] = {}

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

        initial = self.layer_stack.add("PHASE LATTICE", "PHASE LATTICE 01")
        initial.pass_mode = "PAPER RELIEF"
        initial.pass_map = "DISPLACEMENT"
        self._refresh_layer_list(select_id=initial.layer_id)
        self._render_frame()

    def _build_menu(self):
        menu = self.menuBar().addMenu("PROJECT")
        add = QAction("Import audio sources…", self)
        add.setShortcut("Ctrl+O")
        add.triggered.connect(self.import_audio)
        menu.addAction(add)
        menu.addSeparator()
        play = QAction("Play / Pause", self)
        play.setShortcut("Space")
        play.triggered.connect(self.toggle_playback)
        menu.addAction(play)
        stop = QAction("Stop", self)
        stop.setShortcut("Shift+Space")
        stop.triggered.connect(self.stop_playback)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(16, 11, 16, 13)
        main.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(13)
        self.logo = QLabel()
        logo_path = ROOT / "resources" / "widgets" / "eli_lab_waveformer_logo.png"
        if logo_path.is_file():
            pixmap = QPixmap(str(logo_path))
            self.logo.setPixmap(pixmap.scaled(
                116, 48, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self.logo.setStyleSheet("background:#101010; padding:2px; border:0;")
            self.logo.setToolTip("eli_lab / WAVEFORMING")
            self.logo.setFixedSize(120, 50)
        brand = QLabel("eli_lab  /  WAVEFORMING")
        brand.setObjectName("brand")
        subtitle = QLabel("ABSTRACT AUDIO-VISUAL COMPOSITION  ·  1920 × 1440")
        subtitle.setObjectName("muted")
        if logo_path.is_file():
            header.addWidget(self.logo)
        header.addWidget(brand)
        header.addStretch()
        header.addWidget(subtitle)
        main.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        main.addWidget(split, 1)

        left_content = QWidget()
        left = QVBoxLayout(left_content)
        left.setContentsMargins(0, 0, 10, 0)
        left.setSpacing(8)

        source_heading = QHBoxLayout()
        source_title = QLabel("SOUND SOURCES")
        source_title.setObjectName("section")
        add_source = QPushButton("+ ADD SOURCE")
        add_source.clicked.connect(self.import_audio)
        source_heading.addWidget(source_title)
        source_heading.addStretch()
        source_heading.addWidget(add_source)
        left.addLayout(source_heading)

        source_panel = QFrame()
        source_panel.setObjectName("panel")
        self.source_rows = QVBoxLayout(source_panel)
        self.source_rows.setContentsMargins(3, 3, 3, 3)
        self.source_rows.setSpacing(2)
        self.source_rows.addStretch(1)
        self.source_scroll = QScrollArea()
        self.source_scroll.setWidgetResizable(True)
        self.source_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.source_scroll.setMaximumHeight(165)
        self.source_scroll.setWidget(source_panel)
        left.addWidget(self.source_scroll)

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

        generator_box = QGroupBox("GENERATOR ENGINE")
        generator_form = QFormLayout(generator_box)
        self.complexity = self._make_slider(5, 100, 58)
        self.motion = self._make_slider(0, 100, 42)
        self.sensitivity = self._make_slider(0, 200, 110)
        generator_form.addRow("COMPLEXITY", self.complexity)
        generator_form.addRow("MOTION", self.motion)
        generator_form.addRow("AUDIO RESPONSE", self.sensitivity)
        left.addWidget(generator_box)
        self.complexity.valueChanged.connect(self._settings_changed)
        self.motion.valueChanged.connect(self._settings_changed)
        self.sensitivity.valueChanged.connect(self._settings_changed)

        layers_box = QGroupBox("LAYER STACK  ·  BOTTOM TO TOP")
        layers_layout = QVBoxLayout(layers_box)
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.layer_list.setMinimumHeight(100)
        self.layer_list.setMaximumHeight(142)
        self.layer_list.itemSelectionChanged.connect(self._select_layer)
        self.layer_list.itemChanged.connect(self._layer_visibility_changed)
        layers_layout.addWidget(self.layer_list)
        layer_buttons = QHBoxLayout()
        self.add_layer_button = QPushButton("+ LAYER")
        self.duplicate_layer_button = QPushButton("DUPLICATE")
        self.layer_up_button = QPushButton("↑")
        self.layer_down_button = QPushButton("↓")
        self.remove_layer_button = QPushButton("REMOVE")
        for button in (self.add_layer_button, self.duplicate_layer_button,
                       self.layer_up_button, self.layer_down_button, self.remove_layer_button):
            layer_buttons.addWidget(button)
        layers_layout.addLayout(layer_buttons)
        left.addWidget(layers_box)
        self.add_layer_button.clicked.connect(self.add_layer)
        self.duplicate_layer_button.clicked.connect(self.duplicate_layer)
        self.layer_up_button.clicked.connect(lambda: self.move_layer(1))
        self.layer_down_button.clicked.connect(lambda: self.move_layer(-1))
        self.remove_layer_button.clicked.connect(self.remove_layer)

        layer_box = QGroupBox("SELECTED LAYER")
        layer_form = QFormLayout(layer_box)
        self.layer_generator = QComboBox()
        self.layer_generator.addItems(self.compositor.generator_names())
        self.layer_blend = QComboBox()
        self.layer_blend.addItems(["Normal", "Add", "Screen", "Multiply", "Difference", "Overlay", "Lighten", "Darken"])
        self.layer_opacity = self._make_slider(0, 100, 100)
        self.layer_x = self._make_slider(-50, 50, 0)
        self.layer_y = self._make_slider(-50, 50, 0)
        self.layer_scale = self._make_slider(10, 300, 100)
        self.layer_rotation = self._make_slider(-180, 180, 0)
        self.layer_mask = QComboBox()
        self.layer_mask.addItems(["FRAME", "INSET", "ELLIPSE", "FULL"])
        self.layer_pass_map = QComboBox()
        self.layer_pass_map.addItems(self.compositor.pass_names())
        self.layer_pass_mode = QComboBox()
        self.layer_pass_mode.addItems(["PAPER RELIEF", "DISPLACE", "NORMAL LIGHT", "TEXTURE", "EDGE", "NONE"])
        self.layer_pass_strength = self._make_slider(0, 100, 55)
        self.layer_shader = QComboBox()
        self.layer_shader.addItems(["NONE", "HALFTONE", "DITHER", "POSTERIZE", "SCANLINES", "WAVE WARP", "EDGE"])
        self.layer_shader_amount = self._make_slider(0, 100, 45)

        layer_form.addRow("GENERATOR", self.layer_generator)
        layer_form.addRow("BLEND MODE", self.layer_blend)
        layer_form.addRow("OPACITY", self.layer_opacity)
        layer_form.addRow("X OFFSET", self.layer_x)
        layer_form.addRow("Y OFFSET", self.layer_y)
        layer_form.addRow("SCALE", self.layer_scale)
        layer_form.addRow("ROTATION", self.layer_rotation)
        layer_form.addRow("FRAME MASK", self.layer_mask)
        layer_form.addRow("PASS MAP", self.layer_pass_map)
        layer_form.addRow("PASS OPERATION", self.layer_pass_mode)
        layer_form.addRow("RELIEF AMOUNT", self.layer_pass_strength)
        layer_form.addRow("SHADER EFFECT", self.layer_shader)
        layer_form.addRow("SHADER AMOUNT", self.layer_shader_amount)
        left.addWidget(layer_box)

        feedback_box = QGroupBox("TEMPORAL FEEDBACK")
        feedback_form = QFormLayout(feedback_box)
        self.feedback_enabled = QCheckBox("ENABLE FRAME FEEDBACK")
        self.feedback_amount = self._make_slider(0, 100, 28)
        self.feedback_decay = self._make_slider(0, 99, 88)
        self.feedback_shift = self._make_slider(-20, 20, 0)
        feedback_form.addRow(self.feedback_enabled)
        feedback_form.addRow("RETURN MIX", self.feedback_amount)
        feedback_form.addRow("DECAY", self.feedback_decay)
        feedback_form.addRow("DRIFT", self.feedback_shift)
        left.addWidget(feedback_box)

        composition_box = QGroupBox("SCREEN / PAPER")
        composition_form = QFormLayout(composition_box)
        self.screen = QComboBox()
        self.screen.addItems(["No guide", *self.assets.screen_names()])
        self.screen.setCurrentText("SCREEN 1 / BLACK")
        composition_form.addRow("SCREEN GUIDE", self.screen)
        left.addWidget(composition_box)
        self.screen.currentTextChanged.connect(self._screen_changed)

        left.addStretch(1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left_content)

        # A compact property panel remains usable on smaller displays.
        left_scroll.setMinimumWidth(435)
        left_scroll.setMaximumWidth(610)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_title = QLabel("COMPOSITION VIEW")
        preview_title.setObjectName("section")
        canvas_label = QLabel("CANVAS")
        self.zoom = QComboBox()
        self.zoom.addItems(["FIT", "50%", "66%", "75%", "100%"])
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_header.addWidget(canvas_label)
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
        self.seek = self._make_slider(0, 10000, 0)
        self.seek.sliderReleased.connect(self._seek_from_slider)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.loop_check)
        transport.addWidget(self.seek, 1)
        transport.addWidget(self.time_label)
        right_layout.addLayout(transport)

        footer = QHBoxLayout()
        output_label = QLabel("OUTPUT  1920 × 1440")
        self.status = QLabel("NO AUDIO LOADED")
        self.status.setObjectName("muted")
        footer.addWidget(output_label)
        footer.addStretch()
        footer.addWidget(self.status)
        right_layout.addLayout(footer)

        split.addWidget(left_scroll)
        split.addWidget(right)
        split.setSizes([520, 1080])
        split.setStretchFactor(1, 1)

        # All layer property edits update the selected layer, never the audio callback.
        for control in (
            self.layer_generator, self.layer_blend, self.layer_mask,
            self.layer_pass_map, self.layer_pass_mode, self.layer_shader,
        ):
            control.currentTextChanged.connect(self._layer_property_changed)
        for control in (
            self.layer_opacity, self.layer_x, self.layer_y, self.layer_scale,
            self.layer_rotation, self.layer_pass_strength, self.layer_shader_amount,
        ):
            control.valueChanged.connect(self._layer_property_changed)
        for control in (self.feedback_enabled,):
            control.toggled.connect(self._feedback_changed)
        for control in (self.feedback_amount, self.feedback_decay, self.feedback_shift):
            control.valueChanged.connect(self._render_frame)

    @staticmethod
    def _make_slider(minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def _current_layer(self) -> VisualLayer | None:
        item = self.layer_list.currentItem()
        if item is None:
            return None
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        return next((layer for layer in self.layer_stack.layers if layer.layer_id == layer_id), None)

    def _refresh_layer_list(self, select_id: str | None = None) -> None:
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        self._item_ids.clear()
        for layer in self.layer_stack.layers:
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, layer.layer_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            self.layer_list.addItem(item)
            self._item_ids[layer.layer_id] = item
            if layer.layer_id == select_id:
                self.layer_list.setCurrentItem(item)
        if self.layer_list.count() and self.layer_list.currentRow() < 0:
            self.layer_list.setCurrentRow(0)
        self.layer_list.blockSignals(False)
        self._select_layer()

    def add_layer(self) -> None:
        generator = self.layer_generator.currentText()
        layer = self.layer_stack.add(generator)
        self._refresh_layer_list(layer.layer_id)
        self._render_frame()

    def duplicate_layer(self) -> None:
        layer = self._current_layer()
        if layer is None:
            return
        clone = self.layer_stack.duplicate(layer.layer_id)
        if clone:
            self._refresh_layer_list(clone.layer_id)
            self._render_frame()

    def move_layer(self, direction: int) -> None:
        layer = self._current_layer()
        if layer is None:
            return
        self.layer_stack.move(layer.layer_id, direction)
        self._refresh_layer_list(layer.layer_id)
        self._render_frame()

    def remove_layer(self) -> None:
        layer = self._current_layer()
        if layer is None:
            return
        layer_id = layer.layer_id
        self.layer_stack.remove(layer_id)
        self.compositor.generators.release_state(layer_id)
        selected = self.layer_stack.layers[-1].layer_id if self.layer_stack.layers else None
        self._refresh_layer_list(selected)
        self._render_frame()

    def _layer_visibility_changed(self, item: QListWidgetItem) -> None:
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layer = next((entry for entry in self.layer_stack.layers if entry.layer_id == layer_id), None)
        if layer is not None:
            layer.visible = item.checkState() == Qt.CheckState.Checked
            self._render_frame()

    def _select_layer(self) -> None:
        layer = self._current_layer()
        self._updating_layer_controls = True
        controls = (
            self.layer_generator, self.layer_blend, self.layer_opacity,
            self.layer_x, self.layer_y, self.layer_scale, self.layer_rotation,
            self.layer_mask, self.layer_pass_map, self.layer_pass_mode,
            self.layer_pass_strength, self.layer_shader, self.layer_shader_amount,
        )
        for control in controls:
            control.setEnabled(layer is not None)
        if layer is not None:
            self.layer_generator.setCurrentText(layer.generator)
            self.layer_blend.setCurrentText(layer.blend_mode)
            self.layer_opacity.setValue(int(layer.opacity*100))
            self.layer_x.setValue(int(layer.x_offset*100))
            self.layer_y.setValue(int(layer.y_offset*100))
            self.layer_scale.setValue(int(layer.scale*100))
            self.layer_rotation.setValue(int(layer.rotation))
            self.layer_mask.setCurrentText(layer.mask_mode)
            self.layer_pass_map.setCurrentText(layer.pass_map)
            self.layer_pass_mode.setCurrentText(layer.pass_mode)
            self.layer_pass_strength.setValue(int(layer.pass_strength*100))
            self.layer_shader.setCurrentText(layer.shader)
            self.layer_shader_amount.setValue(int(layer.shader_amount*100))
        self._updating_layer_controls = False

    def _layer_property_changed(self, *_args) -> None:
        if self._updating_layer_controls:
            return
        layer = self._current_layer()
        if layer is None:
            return
        layer.generator = self.layer_generator.currentText()
        layer.blend_mode = self.layer_blend.currentText()
        layer.opacity = self.layer_opacity.value()/100.0
        layer.x_offset = self.layer_x.value()/100.0
        layer.y_offset = self.layer_y.value()/100.0
        layer.scale = self.layer_scale.value()/100.0
        layer.rotation = float(self.layer_rotation.value())
        layer.mask_mode = self.layer_mask.currentText()
        layer.pass_map = self.layer_pass_map.currentText()
        layer.pass_mode = self.layer_pass_mode.currentText()
        layer.pass_strength = self.layer_pass_strength.value()/100.0
        layer.shader = self.layer_shader.currentText()
        layer.shader_amount = self.layer_shader_amount.value()/100.0
        item = self._item_ids.get(layer.layer_id)
        if item is not None:
            self.layer_list.blockSignals(True)
            item.setText(layer.name + ("  ·  " + layer.generator if layer.name != layer.generator else ""))
            self.layer_list.blockSignals(False)
        self._render_frame()

    def _screen_changed(self, *_args) -> None:
        self.compositor.reset_feedback()
        self._render_frame()

    def _feedback_changed(self, *_args) -> None:
        if not self.feedback_enabled.isChecked():
            self.compositor.reset_feedback()
        self._render_frame()

    def import_audio(self) -> None:
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
                self.source_rows.insertWidget(self.source_rows.count()-1, row)
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

    def _settings_changed(self, *_args) -> None:
        self._settings.complexity = float(self.complexity.value())
        self._settings.motion = float(self.motion.value())
        self._settings.sensitivity = float(self.sensitivity.value())
        self._render_frame()

    def _configure_analysis(self, *_args) -> None:
        if not hasattr(self, "audio"):
            return
        self.audio.configure_analysis(
            int(self.fft.currentText()),
            int(self.bands.currentText()),
            self.window.currentText().lower(),
        )

    def _render_frame(self, *_args) -> None:
        image = self.compositor.render(
            packet=self._last_packet,
            seconds=self._last_position,
            layers=self.layer_stack.layers,
            settings=self._settings,
            screen=self.screen.currentText(),
            feedback_enabled=self.feedback_enabled.isChecked(),
            feedback_amount=self.feedback_amount.value()/100.0,
            feedback_decay=self.feedback_decay.value()/100.0,
            feedback_shift=self.feedback_shift.value()/100.0,
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
        previous = self._last_position
        self._last_position = seconds
        if seconds < previous:
            self.compositor.reset_feedback()
        self._update_time_label()
        duration = self.audio.duration
        if duration > 0 and not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(int(clamp(seconds/duration,0.0,1.0)*10000))
            self.seek.blockSignals(False)

    def _seek_from_slider(self) -> None:
        duration = self.audio.duration
        if duration > 0:
            self.audio.seek((self.seek.value()/10000.0)*duration)
            self.compositor.reset_feedback()
            self._render_frame()

    def _update_time_label(self) -> None:
        self.time_label.setText(f"{format_time(self._last_position)} / {format_time(self.audio.duration)}")

    def _update_status(self) -> None:
        count = len(self.sources)
        state = "PLAYING" if self.audio.is_playing else "PAUSED" if self._last_position > 0 else "READY"
        self.status.setText(f"{state}  ·  {count:02d} / 07 SOURCES" if count else "NO AUDIO LOADED")

    def toggle_playback(self) -> None:
        if self.audio.is_playing:
            self.audio.pause()
        else:
            if self.audio.duration > 0 and self.audio.position >= self.audio.duration-0.03:
                self.audio.seek(0.0)
                self._last_position = 0.0
                self.compositor.reset_feedback()
            self.audio.play()

    def stop_playback(self) -> None:
        self.audio.stop()
        self._last_position = 0.0
        self.compositor.reset_feedback()
        self._update_status()
        self._update_time_label()
        self._render_frame()

    def _show_audio_error(self, message: str) -> None:
        QMessageBox.warning(self, "WAVEFORMING audio engine", message)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#111; color:#e7e7e7; font-family:'Segoe UI'; font-size:10pt; }
        QMenuBar,QMenu { background:#181818; color:#e7e7e7; }
        QMenuBar::item { padding:6px 10px; } QMenuBar::item:selected,QMenu::item:selected { background:#333; }
        QLabel#brand { font-size:15pt; font-weight:700; letter-spacing:2px; }
        QLabel#section { font-size:10pt; font-weight:700; letter-spacing:1.5px; }
        QLabel#muted { color:#888; font-size:9pt; }
        QFrame#panel,QGroupBox { background:#191919; border:1px solid #363636; border-radius:3px; }
        QGroupBox { margin-top:11px; padding:10px 8px 7px; font-weight:700; color:#aaa; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        QPushButton,QComboBox { background:#242424; border:1px solid #454545; padding:6px 8px; border-radius:2px; }
        QPushButton:hover { background:#303030; border-color:#777; }
        QPushButton:disabled { color:#555; }
        QComboBox::drop-down { border:0; width:18px; }
        QSlider::groove:horizontal { height:3px; background:#494949; }
        QSlider::handle:horizontal { background:#dedede; width:10px; margin:-4px 0; border-radius:5px; }
        QCheckBox { spacing:5px; color:#aaa; }
        QListWidget { background:#171717; border:1px solid #353535; alternate-background-color:#1d1d1d; }
        QListWidget::item { padding:4px 6px; }
        QListWidget::item:selected { background:#343434; color:#fff; }
        QScrollArea { border:0; background:transparent; }
        """)

    def closeEvent(self, event):
        self._render_timer.stop()
        self.audio.close()
        super().closeEvent(event)
