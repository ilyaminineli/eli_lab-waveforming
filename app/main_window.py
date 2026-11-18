from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from time import time_ns

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QFrame, QSlider, QComboBox, QCheckBox, QSplitter,
    QMessageBox, QGroupBox, QFormLayout, QScrollArea, QListWidget,
    QListWidgetItem, QAbstractItemView, QDoubleSpinBox, QProgressDialog,
)

from engine.audio.playback import PlaybackEngine, MAX_AUDIO_SOURCES
from engine.audio.feature_bus import FeatureBus
from engine.audio.source import AudioSource
from engine.visual.assets import AssetCatalog
from engine.visual.canvas import CompositionCanvas
from engine.visual.compositor import PREVIEW_SIZE, PROJECT_SIZE, VisualCompositor
from engine.visual.generators import GeneratorSettings
from engine.visual.preview_worker import PreviewRenderWorker
from engine.render.offline import OfflineRenderWorker
from engine.timeline import Timeline
from app.timeline_widget import TimelineWidget
from engine.visual.layers import LayerStack, VisualLayer
from engine.visual.composition_director import (
    CompositionDirector, create_auto_composition, vary_composition,
)
from engine.project.session import scan_audio_tree
from engine.render.ffmpeg import resolve_ffmpeg

ROOT = Path(__file__).resolve().parents[1]

# Preview work is deliberately capped for the integrated Radeon 820M / low-power
# CPU target. Offline rendering remains native 1920×1440 regardless of this choice.
PREVIEW_PROFILES = {
    "ECO  ·  320×240  ·  5 FPS": ((320, 240), 200),
    "LOW  ·  360×270  ·  6 FPS": ((360, 270), 167),
    "BALANCED  ·  480×360  ·  8 FPS": ((480, 360), 125),
}
DEFAULT_PREVIEW_PROFILE = "ECO  ·  320×240  ·  5 FPS"


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
        analysis.setChecked(source.analysis_enabled)
        mute.setChecked(source.muted)
        solo.setChecked(source.solo)
        gain = QSlider(Qt.Orientation.Horizontal)
        gain.setRange(0, 200)
        gain.setValue(int(round(source.gain*100)))
        gain.setFixedWidth(68)
        pan = QSlider(Qt.Orientation.Horizontal)
        pan.setRange(-100, 100)
        pan.setValue(int(round(source.pan*100)))
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
        self.director = CompositionDirector("SEMI-AUTO")
        self.feature_bus = FeatureBus(analysis_rate=8.0)
        self.timeline = Timeline()
        self.layer_stack = LayerStack()
        self._loading_project = False
        self._render_sequence = 0
        self._displayed_sequence = -1
        self._export_worker = None
        self._export_progress = None
        self._project_path: Path | None = None
        self._updating_layer_controls = False
        self._item_ids: dict[str, QListWidgetItem] = {}

        self.assets = AssetCatalog(AssetCatalog.locate_project_assets(ROOT))
        # UI-side compositor is used for generator/pass metadata only.
        self.compositor = VisualCompositor(self.assets, render_size=PREVIEW_SIZE)
        self.preview_worker = PreviewRenderWorker(self.assets, render_size=PREVIEW_SIZE)
        self.preview_worker.signals.frame_ready.connect(self._on_preview_frame)
        self.preview_worker.signals.render_error.connect(self._on_preview_error)
        self.preview_worker.start()
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
        self._render_timer.setInterval(200)
        self._render_timer.timeout.connect(self._render_frame)
        self.preview_quality.currentIndexChanged.connect(self._preview_quality_changed)
        self._variation_timer = QTimer(self)
        self._variation_timer.setInterval(12000)
        self._variation_timer.timeout.connect(self.vary_composition)

        initial = self.layer_stack.add("PHASE LATTICE", "PHASE LATTICE 01")
        initial.pass_mode = "PAPER RELIEF"
        initial.pass_map = "DISPLACEMENT"
        self._refresh_layer_list(select_id=initial.layer_id)
        self.preview_worker.request_reset()
        self._preview_quality_changed()
        self._update_timeline_duration()

    def _build_menu(self):
        menu = self.menuBar().addMenu("PROJECT")
        open_project = QAction("Open project…", self)
        open_project.setShortcut("Ctrl+Shift+O")
        open_project.triggered.connect(self.load_project)
        menu.addAction(open_project)
        save_project = QAction("Save project…", self)
        save_project.setShortcut("Ctrl+S")
        save_project.triggered.connect(self.save_project)
        menu.addAction(save_project)
        menu.addSeparator()
        add = QAction("Import audio sources…", self)
        add.setShortcut("Ctrl+O")
        add.triggered.connect(self.import_audio)
        menu.addAction(add)
        add_folder = QAction("Import audio folder…", self)
        add_folder.triggered.connect(self.import_audio_folder)
        menu.addAction(add_folder)
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
        add_folder = QPushButton("+ IMPORT FOLDER")
        add_folder.clicked.connect(self.import_audio_folder)
        source_heading.addWidget(source_title)
        source_heading.addStretch()
        source_heading.addWidget(add_folder)
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
        self.director_mode = QComboBox()
        self.director_mode.addItems(CompositionDirector.MODES)
        self.director_mode.setCurrentText(self.director.mode)
        generator_form.addRow("COMPLEXITY", self.complexity)
        generator_form.addRow("MOTION", self.motion)
        generator_form.addRow("AUDIO RESPONSE", self.sensitivity)
        generator_form.addRow("COMPOSITION DIRECTOR", self.director_mode)
        self.director_mode.currentTextChanged.connect(self._director_mode_changed)
        auto_row = QHBoxLayout()
        self.auto_compose_button = QPushButton("AUTO COMPOSE")
        self.vary_button = QPushButton("VARIATE")
        self.auto_variation_check = QCheckBox("AUTO VARIATE")
        auto_row.addWidget(self.auto_compose_button)
        auto_row.addWidget(self.vary_button)
        auto_row.addWidget(self.auto_variation_check)
        generator_form.addRow(auto_row)
        self.auto_compose_button.clicked.connect(self.auto_compose)
        self.vary_button.clicked.connect(self.vary_composition)
        self.auto_variation_check.toggled.connect(self._auto_variation_changed)
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
        self.layer_source = QComboBox()
        self.layer_source.addItem("MIX / ALL", "")
        self.layer_palette = QComboBox()
        self.layer_palette.addItems(["EDITORIAL TRICOLOR", "MONOCHROME"])
        self.layer_blend = QComboBox()
        self.layer_blend.addItems(["Normal", "Add", "Screen", "Multiply", "Difference", "Overlay", "Lighten", "Darken"])
        self.layer_opacity = self._make_slider(0, 100, 100)
        self.layer_x = self._make_slider(-50, 50, 0)
        self.layer_y = self._make_slider(-50, 50, 0)
        self.layer_scale = self._make_slider(10, 300, 100)
        self.layer_rotation = QComboBox()
        for degrees in (0, 90, 180, 270):
            self.layer_rotation.addItem(f"{degrees}°", degrees)
        self.layer_mask = QComboBox()
        self.layer_mask.addItems(["FRAME", "INSET", "ELLIPSE", "FULL"])
        self.layer_pass_map = QComboBox()
        self.layer_pass_map.addItems(self.compositor.pass_names())
        self.layer_pass_mode = QComboBox()
        self.layer_pass_mode.addItems(["PAPER RELIEF", "DISPLACE", "NORMAL LIGHT", "TEXTURE", "NONE"])
        self.layer_pass_strength = self._make_slider(0, 100, 55)

        layer_form.addRow("GENERATOR", self.layer_generator)
        layer_form.addRow("SOURCE CHANNEL", self.layer_source)
        layer_form.addRow("INK PALETTE", self.layer_palette)
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
        preview_label = QLabel("PREVIEW")
        self.preview_quality = QComboBox()
        self.preview_quality.addItems(list(PREVIEW_PROFILES))
        self.preview_quality.setCurrentText(DEFAULT_PREVIEW_PROFILE)
        canvas_label = QLabel("CANVAS")
        self.zoom = QComboBox()
        self.zoom.addItems(["FIT", "50%", "66%", "75%", "100%"])
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_header.addWidget(preview_label)
        preview_header.addWidget(self.preview_quality)
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

        timeline_box = QGroupBox("TIMELINE  /  AUTOMATION")
        timeline_layout = QVBoxLayout(timeline_box)
        timeline_layout.setContentsMargins(7, 8, 7, 6)
        timeline_controls = QHBoxLayout()
        timeline_controls.addWidget(QLabel("BPM"))
        self.bpm = QDoubleSpinBox()
        self.bpm.setRange(20.0, 300.0)
        self.bpm.setDecimals(1)
        self.bpm.setSingleStep(0.5)
        self.bpm.setValue(self.timeline.bpm)
        self.bpm.setFixedWidth(72)
        self.snap_beat = QCheckBox("SNAP TO BEAT")
        self.snap_beat.setChecked(True)
        self.add_marker_button = QPushButton("+ MARKER")
        self.add_section_button = QPushButton("+ SECTION")
        self.delete_marker_button = QPushButton("- MARKER")
        self.record_automation = QCheckBox("RECORD AUTOMATION")
        self.record_automation.toggled.connect(self._record_automation_toggled)
        self.export_fps = QComboBox()
        self.export_fps.addItems(["15", "24", "25", "30"])
        self.export_fps.setCurrentText("24")
        self.export_button = QPushButton("EXPORT MP4")
        timeline_controls.addWidget(self.bpm)
        timeline_controls.addWidget(self.snap_beat)
        timeline_controls.addWidget(self.add_marker_button)
        timeline_controls.addWidget(self.add_section_button)
        timeline_controls.addWidget(self.delete_marker_button)
        timeline_controls.addWidget(self.record_automation)
        timeline_controls.addStretch()
        timeline_controls.addWidget(QLabel("FPS"))
        timeline_controls.addWidget(self.export_fps)
        timeline_controls.addWidget(self.export_button)
        timeline_layout.addLayout(timeline_controls)
        self.timeline_widget = TimelineWidget(self.timeline)
        self.timeline_widget.seek_requested.connect(self._seek_to_time)
        timeline_layout.addWidget(self.timeline_widget)
        self.bpm.valueChanged.connect(self._bpm_changed)
        self.add_marker_button.clicked.connect(lambda: self._add_timeline_marker("MARKER"))
        self.add_section_button.clicked.connect(lambda: self._add_timeline_marker("SECTION"))
        self.delete_marker_button.clicked.connect(self._delete_timeline_marker)
        self.export_button.clicked.connect(self.export_video)
        right_layout.addWidget(timeline_box)

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
            self.layer_generator, self.layer_source, self.layer_palette,
            self.layer_blend, self.layer_rotation, self.layer_mask,
            self.layer_pass_map, self.layer_pass_mode,
        ):
            control.currentTextChanged.connect(self._layer_property_changed)
        for control in (
            self.layer_opacity, self.layer_x, self.layer_y, self.layer_scale,
            self.layer_pass_strength,
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
            channel = ""
            if layer.source_id and layer.source_id in self.sources:
                channel = f"  ·  CH {list(self.sources).index(layer.source_id) + 1:02d}"
            item = QListWidgetItem(layer.name + channel)
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
        layer.palette_index = len(self.layer_stack.layers) - 1
        self._refresh_layer_list(layer.layer_id)
        self._render_frame()

    def auto_compose(self) -> None:
        seed = int(time_ns() & 0x7FFFFFFF)
        self.layer_stack.layers = create_auto_composition(
            self.compositor.generator_names(), list(self.sources.keys()), seed
        )
        self._settings.seed = seed
        self.preview_worker.request_reset()
        selected = self.layer_stack.layers[0].layer_id if self.layer_stack.layers else None
        self._refresh_layer_list(selected)
        self._render_frame()

    def vary_composition(self) -> None:
        if not self.layer_stack.layers:
            self.auto_compose()
            return
        seed = int(time_ns() & 0x7FFFFFFF)
        selected = self._current_layer()
        selected_id = selected.layer_id if selected else self.layer_stack.layers[0].layer_id
        self.layer_stack.layers = vary_composition(
            self.layer_stack.layers, self.compositor.generator_names(), seed
        )
        self._settings.seed = seed
        self.preview_worker.request_reset()
        self._refresh_layer_list(selected_id)
        self._render_frame()

    def _auto_variation_changed(self, enabled: bool) -> None:
        if enabled and self.audio.is_playing:
            self._variation_timer.start()
        else:
            self._variation_timer.stop()

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
        self.preview_worker.request_reset()
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
            self.layer_generator, self.layer_source, self.layer_palette,
            self.layer_blend, self.layer_opacity, self.layer_x, self.layer_y,
            self.layer_scale, self.layer_rotation, self.layer_mask,
            self.layer_pass_map, self.layer_pass_mode, self.layer_pass_strength,
        )
        for control in controls:
            control.setEnabled(layer is not None)
        if layer is not None:
            self.layer_generator.setCurrentText(layer.generator)
            source_index = self.layer_source.findData(layer.source_id)
            self.layer_source.setCurrentIndex(max(0, source_index))
            self.layer_palette.setCurrentText(layer.palette_mode)
            self.layer_blend.setCurrentText(layer.blend_mode)
            self.layer_opacity.setValue(int(layer.opacity*100))
            self.layer_x.setValue(int(layer.x_offset*100))
            self.layer_y.setValue(int(layer.y_offset*100))
            self.layer_scale.setValue(int(layer.scale*100))
            rotation_index = self.layer_rotation.findData(int(layer.rotation) % 360)
            self.layer_rotation.setCurrentIndex(max(0, rotation_index))
            self.layer_mask.setCurrentText(layer.mask_mode)
            self.layer_pass_map.setCurrentText(layer.pass_map)
            self.layer_pass_mode.setCurrentText(layer.pass_mode)
            self.layer_pass_strength.setValue(int(layer.pass_strength*100))
        self._updating_layer_controls = False

    def _layer_property_changed(self, *_args) -> None:
        if self._updating_layer_controls:
            return
        layer = self._current_layer()
        if layer is None:
            return
        new_generator = self.layer_generator.currentText()
        if new_generator != layer.generator:
            self.preview_worker.request_reset()
        layer.generator = new_generator
        layer.source_id = str(self.layer_source.currentData() or "")
        layer.palette_mode = self.layer_palette.currentText()
        layer.blend_mode = self.layer_blend.currentText()
        layer.opacity = self.layer_opacity.value()/100.0
        layer.x_offset = self.layer_x.value()/100.0
        layer.y_offset = self.layer_y.value()/100.0
        layer.scale = self.layer_scale.value()/100.0
        layer.rotation = float(self.layer_rotation.currentData() or 0)
        layer.mask_mode = self.layer_mask.currentText()
        layer.pass_map = self.layer_pass_map.currentText()
        layer.pass_mode = self.layer_pass_mode.currentText()
        layer.pass_strength = self.layer_pass_strength.value()/100.0
        item = self._item_ids.get(layer.layer_id)
        if item is not None:
            channel = ""
            if layer.source_id and layer.source_id in self.sources:
                channel = f"  ·  CH {list(self.sources).index(layer.source_id) + 1:02d}"
            label = layer.name + ("  ·  " + layer.generator if layer.name != layer.generator else "")
            self.layer_list.blockSignals(True)
            item.setText(label + channel)
            self.layer_list.blockSignals(False)
        self._render_frame()

    def _screen_changed(self, *_args) -> None:
        self.preview_worker.request_reset()
        self._render_frame()

    def _feedback_changed(self, *_args) -> None:
        if not self.feedback_enabled.isChecked():
            self.preview_worker.request_reset()
        self._render_frame()

    def import_audio(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import audio sources", "",
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg *.mp3);;All files (*)",
        )
        self._import_audio_paths([Path(path) for path in paths])

    def import_audio_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import audio folder", "")
        if not folder:
            return
        grouped = scan_audio_tree(Path(folder))
        paths = [path for members in grouped.values() for path in members]
        if not paths:
            QMessageBox.information(self, "Import audio folder", "No supported audio files were found.")
            return
        self._import_audio_paths(paths)

    def _import_audio_paths(self, paths: list[Path]) -> None:
        imported = 0
        errors: list[str] = []
        limit_reached = False
        for path in paths:
            if len(self.sources) >= MAX_AUDIO_SOURCES:
                limit_reached = True
                break
            try:
                source = AudioSource.from_file(
                    Path(path), target_sample_rate=self.audio.sample_rate
                )
                track_id = self.audio.add_source(source)
                self.sources[track_id] = source
                row = SourceRow(source, track_id, self._remove_source)
                self.source_rows.insertWidget(self.source_rows.count()-1, row)
                imported += 1
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")

        if limit_reached:
            QMessageBox.information(
                self, "Source limit",
                f"WAVEFORMING supports up to {MAX_AUDIO_SOURCES} audio sources. "
                "The remaining files were not imported.",
            )
        if errors:
            QMessageBox.warning(
                self, "Some audio files could not be imported",
                "\n".join(errors[:10]) + (
                    f"\n…and {len(errors)-10} more." if len(errors) > 10 else ""
                ),
            )
        if imported:
            self.feature_bus.reset()
            self._last_packet = {}
            self._refresh_source_options()
            self._update_status()
            self._update_time_label()
            self._update_timeline_duration()
            self._render_frame()

    def _refresh_source_options(self) -> None:
        if not hasattr(self, "layer_source"):
            return
        current = str(self.layer_source.currentData() or "")
        self.layer_source.blockSignals(True)
        self.layer_source.clear()
        self.layer_source.addItem("MIX / ALL", "")

        groups: dict[str, str] = {}
        for source in self.sources.values():
            if source.group_id:
                groups[source.group_id] = source.group_name or source.group_id
        for group_id, group_name in sorted(groups.items(), key=lambda item: item[1].casefold()):
            self.layer_source.addItem(f"GROUP / {group_name}", f"group:{group_id}")

        for track_id, source in self.sources.items():
            self.layer_source.addItem(source.name, track_id)
        index = self.layer_source.findData(current)
        self.layer_source.setCurrentIndex(max(0, index))
        self.layer_source.blockSignals(False)

    def _remove_source(self, track_id: str, row: SourceRow) -> None:
        self.audio.remove_source(track_id)
        self.sources.pop(track_id, None)
        for layer in self.layer_stack.layers:
            if layer.source_id == track_id:
                layer.source_id = ""
        row.deleteLater()
        self._refresh_source_options()
        self._refresh_layer_list(self._current_layer().layer_id if self._current_layer() else None)
        self._update_status()
        self._update_time_label()
        self._update_timeline_duration()
        self._render_frame()

    def save_project(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save WAVEFORMING project",
            str(self._project_path or (ROOT / "untitled.wfp")),
            "WAVEFORMING project (*.wfp);;JSON project (*.json)",
        )
        if not filename:
            return
        data = {
            "format": "eli_lab.waveforming",
            "version": 1,
            "director_mode": self.director.mode,
            "settings": asdict(self._settings),
            "layers": self.layer_stack.to_list(),
            "timeline": self.timeline.to_dict(),
            "screen": self.screen.currentText(),
            "feedback": {
                "enabled": self.feedback_enabled.isChecked(),
                "amount": self.feedback_amount.value(),
                "decay": self.feedback_decay.value(),
                "shift": self.feedback_shift.value(),
            },
            "sources": [
                {
                    "track_id": track_id,
                    "path": str(source.path.resolve()),
                    "gain": source.gain,
                    "pan": source.pan,
                    "muted": source.muted,
                    "solo": source.solo,
                    "analysis_enabled": source.analysis_enabled,
                    "group_id": source.group_id,
                    "group_name": source.group_name,
                }
                for track_id, source in self.sources.items()
            ],
        }
        try:
            path = Path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._project_path = path
            self.status.setText(f"SAVED  ·  {path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Project save failed", str(exc))

    def load_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open WAVEFORMING project", "",
            "WAVEFORMING project (*.wfp *.json);;All files (*)",
        )
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if data.get("format") != "eli_lab.waveforming":
                raise ValueError("This file is not a WAVEFORMING project.")
        except Exception as exc:
            QMessageBox.warning(self, "Project open failed", str(exc))
            return

        self._loading_project = True
        self.audio.stop()
        for track_id in list(self.sources):
            self.audio.remove_source(track_id)
        self.sources.clear()
        while self.source_rows.count() > 1:
            item = self.source_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        source_id_map = {}
        missing_sources = []
        for saved in data.get("sources", []):
            path = Path(saved.get("path", ""))
            if not path.is_file():
                missing_sources.append(str(path))
                continue
            try:
                source = AudioSource.from_file(
                    path, target_sample_rate=self.audio.sample_rate
                )
                source.group_id = str(saved.get("group_id") or source.group_id)
                source.group_name = str(saved.get("group_name") or source.group_name)
                source.gain = float(saved.get("gain", 1.0))
                source.pan = float(saved.get("pan", 0.0))
                source.muted = bool(saved.get("muted", False))
                source.solo = bool(saved.get("solo", False))
                source.analysis_enabled = bool(saved.get("analysis_enabled", True))
                track_id = self.audio.add_source(source)
                source_id_map[str(saved.get("track_id", ""))] = track_id
                self.sources[track_id] = source
                row = SourceRow(source, track_id, self._remove_source)
                self.source_rows.insertWidget(self.source_rows.count()-1, row)
            except Exception as exc:
                missing_sources.append(f"{path}: {exc}")

        self._settings = GeneratorSettings(**data.get("settings", {}))
        self.complexity.setValue(int(self._settings.complexity))
        self.motion.setValue(int(self._settings.motion))
        self.sensitivity.setValue(int(self._settings.sensitivity))
        self.layer_stack.from_list(data.get("layers", []))
        valid_groups = {source.group_id for source in self.sources.values() if source.group_id}
        for layer in self.layer_stack.layers:
            if layer.source_id.startswith("group:"):
                group_id = layer.source_id[len("group:"):]
                if group_id not in valid_groups:
                    layer.source_id = ""
            elif layer.source_id:
                layer.source_id = source_id_map.get(layer.source_id, "")
        self.timeline = Timeline.from_dict(data.get("timeline"))
        saved_director_mode = str(data.get("director_mode", "SEMI-AUTO"))
        if saved_director_mode not in CompositionDirector.MODES:
            saved_director_mode = "SEMI-AUTO"
        self.director_mode.setCurrentText(saved_director_mode)
        self.director.set_mode(saved_director_mode)
        self.director.reset()
        self.feature_bus.reset()
        self.timeline_widget.set_timeline(self.timeline)
        self.bpm.setValue(self.timeline.bpm)
        self.screen.setCurrentText(data.get("screen", "SCREEN 1 / BLACK"))
        feedback = data.get("feedback", {})
        self.feedback_enabled.setChecked(bool(feedback.get("enabled", False)))
        self.feedback_amount.setValue(int(feedback.get("amount", 28)))
        self.feedback_decay.setValue(int(feedback.get("decay", 88)))
        self.feedback_shift.setValue(int(feedback.get("shift", 0)))
        self._last_packet = {}
        self._last_position = 0.0
        self.audio.seek(0.0)
        self._refresh_source_options()
        selected = self.layer_stack.layers[0].layer_id if self.layer_stack.layers else None
        self._refresh_layer_list(selected)
        self._update_timeline_duration()
        self._update_status()
        self._update_time_label()
        self._loading_project = False
        self._project_path = Path(filename)
        self.preview_worker.request_reset()
        self._render_frame()
        if missing_sources:
            QMessageBox.warning(
                self, "Some audio sources were not loaded",
                "The project was opened, but these sources are unavailable:\n\n"
                + "\n".join(missing_sources[:12]),
            )

    @staticmethod
    def _export_source_samples(source: AudioSource):
        samples = source.samples if source.samples is not None else source.load_into_memory()
        if getattr(samples, "ndim", 0) != 2 or samples.shape[1] < 1:
            raise ValueError(f"Audio source {source.name!r} has an invalid channel layout.")
        if samples.shape[1] == 1:
            samples = samples.repeat(2, axis=1)
        elif samples.shape[1] > 2:
            samples = samples[:, :2]
        return samples

    def export_video(self) -> None:
        if resolve_ffmpeg() is None:
            QMessageBox.warning(
                self, "FFmpeg is unavailable",
                "MP4 export needs FFmpeg. Reinstall the project requirements "
                "(pip install -r requirements.txt), or set FFMPEG_BINARY to ffmpeg.exe. "
                "A system-wide PATH change is no longer required when imageio-ffmpeg is installed.",
            )
            return
        if not self.sources:
            QMessageBox.information(self, "Export video", "Import audio sources before exporting.")
            return
        if self._export_worker is not None and self._export_worker.isRunning():
            QMessageBox.information(self, "Export video", "An export is already running.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export deterministic video", "",
            "MP4 video (*.mp4)",
        )
        if not filename:
            return
        output_path = Path(filename)
        if output_path.suffix.lower() != ".mp4":
            output_path = output_path.with_suffix(".mp4")

        if self.audio.is_playing:
            self.audio.pause()
        fps = int(self.export_fps.currentText())
        source_snapshot = [
            {
                "track_id": track_id,
                "samples": self._export_source_samples(source),
                "gain": source.gain,
                "pan": source.pan,
                "muted": source.muted,
                "solo": source.solo,
                "analysis_enabled": source.analysis_enabled,
                "group_id": source.group_id,
                "group_name": source.group_name,
            }
            for track_id, source in self.sources.items()
        ]
        frame_total = max(1, int(self.audio.duration * fps + 0.999))
        self._export_progress = QProgressDialog(
            "Rendering 1920 × 1440 frames…", "CANCEL", 0, frame_total, self
        )
        self._export_progress.setWindowTitle("WAVEFORMING / OFFLINE RENDER")
        self._export_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress.setMinimumDuration(0)

        self._export_worker = OfflineRenderWorker(
            output_path=output_path,
            assets_root=self.assets.root,
            sources=source_snapshot,
            layers=self.layer_stack.to_list(),
            settings=asdict(self._settings),
            timeline=self.timeline.to_dict(),
            screen=self.screen.currentText(),
            sample_rate=self.audio.sample_rate,
            fft_size=int(self.fft.currentText()),
            band_count=int(self.bands.currentText()),
            window=self.window.currentText().lower(),
            fps=fps,
            resolution=PROJECT_SIZE,
            feedback={
                "enabled": self.feedback_enabled.isChecked(),
                "amount": self.feedback_amount.value()/100.0,
                "decay": self.feedback_decay.value()/100.0,
                "shift": self.feedback_shift.value()/100.0,
            },
            director_mode=self.director.mode,
        )
        self._export_progress.canceled.connect(self._export_worker.cancel)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.completed.connect(self._on_export_completed)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.render_cancelled.connect(self._on_export_cancelled)
        self._export_worker.finished.connect(self._on_export_thread_finished)
        self._export_worker.start()

    def _on_export_progress(self, current: int, total: int) -> None:
        if self._export_progress is not None:
            self._export_progress.setMaximum(total)
            self._export_progress.setValue(current)
            self._export_progress.setLabelText(
                f"Rendering deterministic frames…  {current:,} / {total:,}"
            )

    def _close_export_progress(self) -> None:
        if self._export_progress is not None:
            self._export_progress.close()
            self._export_progress = None

    def _on_export_thread_finished(self) -> None:
        worker = self._export_worker
        self._export_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_export_completed(self, filename: str) -> None:
        self._close_export_progress()
        QMessageBox.information(self, "Export complete", f"Video saved:\n{filename}")

    def _on_export_failed(self, message: str) -> None:
        self._close_export_progress()
        QMessageBox.warning(self, "Export failed", message)

    def _on_export_cancelled(self) -> None:
        self._close_export_progress()
        self.status.setText("EXPORT CANCELLED")

    def _record_automation_toggled(self, enabled: bool) -> None:
        if not enabled:
            return
        # Anchor each empty lane to the current base value at t=0. Later
        # edits then interpolate from the original setting rather than
        # changing the composition retroactively before the first edit.
        for target in Timeline.TARGETS:
            lane = self.timeline.lanes[target]
            if not lane.points:
                self.timeline.record(target, 0.0, float(getattr(self._settings, target)))
        self.timeline_widget.set_timeline(self.timeline)
        self._render_frame()

    def _settings_changed(self, *_args) -> None:
        self._settings.complexity = float(self.complexity.value())
        self._settings.motion = float(self.motion.value())
        self._settings.sensitivity = float(self.sensitivity.value())
        if self.record_automation.isChecked() and self.audio.is_playing and not self._loading_project:
            target = {
                self.complexity: "complexity",
                self.motion: "motion",
                self.sensitivity: "sensitivity",
            }.get(self.sender())
            if target:
                self.timeline.record(target, self._last_position, float(getattr(self._settings, target)))
                self.timeline_widget.set_timeline(self.timeline)
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
        self._render_sequence += 1
        seconds = self._last_position
        director_output = self.director.update(self._last_packet, seconds)

        if director_output.request_variation and self.audio.is_playing and self.layer_stack.layers:
            selected = self._current_layer()
            selected_id = selected.layer_id if selected else self.layer_stack.layers[0].layer_id
            seed = (int(self._settings.seed) + int(seconds * 10000.0) * 104729) & 0x7FFFFFFF
            self.layer_stack.layers = vary_composition(
                self.layer_stack.layers, self.compositor.generator_names(), seed
            )
            self._settings.seed = seed
            self.preview_worker.request_reset()
            self._refresh_layer_list(selected_id)

        base_settings = self.timeline.settings_at(seconds, self._settings)
        effective_settings = GeneratorSettings(
            complexity=clamp(base_settings.complexity * director_output.complexity_scale, 5.0, 100.0),
            motion=clamp(base_settings.motion * director_output.motion_scale, 0.0, 100.0),
            sensitivity=base_settings.sensitivity,
            seed=base_settings.seed,
        )
        frame_packet = dict(self._last_packet)
        frame_packet["director_output"] = {
            "glitch_amount": director_output.glitch_amount,
            "accent_amount": director_output.accent_amount,
            "state": director_output.state,
        }
        self.preview_worker.submit(
            packet=frame_packet,
            seconds=seconds,
            layers=self.layer_stack.layers,
            settings=effective_settings,
            screen=self.screen.currentText(),
            feedback_enabled=self.feedback_enabled.isChecked(),
            feedback_amount=self.feedback_amount.value()/100.0,
            feedback_decay=self.feedback_decay.value()/100.0,
            feedback_shift=self.feedback_shift.value()/100.0,
            sequence=self._render_sequence,
        )

    def _on_preview_frame(self, image, seconds: float, sequence: int) -> None:
        # A render may finish after several newer requests have been queued.
        # Drop visibly stale frames instead of making the preview jump backwards.
        if sequence < self._render_sequence - 1:
            return
        if sequence >= self._displayed_sequence:
            self._displayed_sequence = sequence
            self.canvas.set_frame(image)

    def _preview_quality_changed(self, *_args) -> None:
        profile = PREVIEW_PROFILES.get(
            self.preview_quality.currentText(),
            PREVIEW_PROFILES[DEFAULT_PREVIEW_PROFILE],
        )
        render_size, interval_ms = profile
        self.preview_worker.set_render_size(render_size)
        self._render_timer.setInterval(interval_ms)
        self.preview_worker.request_reset()
        self._render_frame()

    def _on_preview_error(self, message: str) -> None:
        self.status.setText(message[:90])

    def _on_features(self, packet: dict) -> None:
        source_groups = {
            track_id: source.group_id
            for track_id, source in self.sources.items()
            if source.group_id
        }
        self._last_packet = self.feature_bus.update(packet, source_groups)
        if not self.audio.is_playing:
            self._render_frame()

    def _director_mode_changed(self, mode: str) -> None:
        if mode not in CompositionDirector.MODES:
            return
        self.director.set_mode(mode)
        self.director.reset()
        self._render_frame()

    def _on_playback_state(self, playing: bool) -> None:
        self.play_button.setText("Ⅱ  PAUSE" if playing else "▶  PLAY")
        if playing:
            self._render_timer.start()
            if self.auto_variation_check.isChecked():
                self._variation_timer.start()
        else:
            self._render_timer.stop()
            self._variation_timer.stop()
        self._update_status()

    def _on_position(self, seconds: float) -> None:
        previous = self._last_position
        self._last_position = seconds
        if seconds < previous:
            self.preview_worker.request_reset()
            self.feature_bus.reset()
            self.director.reset()
            self._last_packet = {}
        if hasattr(self, "timeline_widget"):
            self.timeline_widget.set_position(seconds)
        self._update_time_label()
        duration = self.audio.duration
        if duration > 0 and not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(int(clamp(seconds/duration,0.0,1.0)*10000))
            self.seek.blockSignals(False)

    def _seek_from_slider(self) -> None:
        duration = self.audio.duration
        if duration > 0:
            self._seek_to_time((self.seek.value()/10000.0)*duration)

    def _seek_to_time(self, seconds: float) -> None:
        duration = self.audio.duration
        target = min(max(0.0, float(seconds)), duration) if duration > 0 else 0.0
        if target < self._last_position:
            self.feature_bus.reset()
            self.director.reset()
            self._last_packet = {}
        self.audio.seek(target)
        self._last_position = self.audio.position
        self.preview_worker.request_reset()
        self._render_frame()

    def _bpm_changed(self, value: float) -> None:
        self.timeline.bpm = float(value)
        self.timeline_widget.update()

    def _add_timeline_marker(self, kind: str) -> None:
        seconds = self._last_position
        if self.snap_beat.isChecked():
            seconds = self.timeline.snap_to_beat(seconds)
        self.timeline.add_marker(seconds, kind=kind)
        self.timeline_widget.set_timeline(self.timeline)

    def _delete_timeline_marker(self) -> None:
        if self.timeline.remove_nearest_marker(self._last_position):
            self.timeline_widget.set_timeline(self.timeline)

    def _update_timeline_duration(self) -> None:
        self.timeline.set_duration(self.audio.duration)
        if hasattr(self, "timeline_widget"):
            self.timeline_widget.set_duration(self.audio.duration)

    def _update_time_label(self) -> None:
        self.time_label.setText(f"{format_time(self._last_position)} / {format_time(self.audio.duration)}")
        self._update_timeline_duration()

    def _update_status(self) -> None:
        count = len(self.sources)
        state = "PLAYING" if self.audio.is_playing else "PAUSED" if self._last_position > 0 else "READY"
        self.status.setText(
            f"{state}  ·  {count:02d} / {MAX_AUDIO_SOURCES:02d} SOURCES"
            if count else "NO AUDIO LOADED"
        )

    def toggle_playback(self) -> None:
        if self.audio.is_playing:
            self.audio.pause()
        else:
            if self.audio.duration > 0 and self.audio.position >= self.audio.duration-0.03:
                self.audio.seek(0.0)
                self._last_position = 0.0
                self.preview_worker.request_reset()
            self.audio.play()

    def stop_playback(self) -> None:
        self.audio.stop()
        self.feature_bus.reset()
        self.director.reset()
        self._last_packet = {}
        self._last_position = 0.0
        self.preview_worker.request_reset()
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
        self._variation_timer.stop()
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.cancel()
            if not self._export_worker.wait(3000):
                # Never destroy a running QThread. The current full-resolution
                # frame must reach its cancellation checkpoint first.
                self.status.setText("EXPORT CANCELLING  ·  CLOSE AGAIN WHEN COMPLETE")
                event.ignore()
                return
        self.preview_worker.close(timeout=3.0)
        self.audio.close()
        super().closeEvent(event)
