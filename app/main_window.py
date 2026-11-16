from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFileDialog, QFrame, QSlider, QComboBox, QCheckBox, QSplitter,
    QMessageBox, QGroupBox, QFormLayout)
from engine.audio.source import AudioSource
from engine.visual.canvas import CompositionCanvas
from engine.visual.assets import AssetCatalog

ROOT = Path(__file__).resolve().parents[1]

class SourceRow(QWidget):
    def __init__(self, source: AudioSource, parent=None):
        super().__init__(parent)
        self.source = source
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        name = QLabel(source.name)
        name.setMinimumWidth(100)
        mute, solo, analysis = QCheckBox("M"), QCheckBox("S"), QCheckBox("AN")
        analysis.setChecked(True)
        gain, pan = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        gain.setRange(0, 200); gain.setValue(100); gain.setFixedWidth(85)
        pan.setRange(-100, 100); pan.setValue(0); pan.setFixedWidth(70)
        for w in (name, mute, solo, analysis, QLabel("GAIN"), gain, QLabel("PAN"), pan):
            row.addWidget(w)
        row.addStretch(1)
        mute.toggled.connect(lambda v: setattr(source, "muted", v))
        solo.toggled.connect(lambda v: setattr(source, "solo", v))
        analysis.toggled.connect(lambda v: setattr(source, "analysis_enabled", v))
        gain.valueChanged.connect(lambda v: setattr(source, "gain", v / 100.0))
        pan.valueChanged.connect(lambda v: setattr(source, "pan", v / 100.0))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ELI LAB / WAVEFORMING")
        self.resize(1480, 960)
        self.sources: list[AudioSource] = []
        self.assets = AssetCatalog(ROOT / "screens")
        self._build_menu()
        self._build_ui()
        self._apply_style()

    def _build_menu(self):
        menu = self.menuBar().addMenu("PROJECT")
        add = QAction("Import audio source…", self)
        add.setShortcut("Ctrl+O")
        add.triggered.connect(self.import_audio)
        menu.addAction(add)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QVBoxLayout(root); main.setContentsMargins(16, 12, 16, 14); main.setSpacing(10)
        header = QHBoxLayout()
        brand = QLabel("ELI LAB  /  WAVEFORMING"); brand.setObjectName("brand")
        subtitle = QLabel("ABSTRACT AUDIO-VISUAL COMPOSITION  ·  1920 × 1440"); subtitle.setObjectName("muted")
        header.addWidget(brand); header.addStretch(); header.addWidget(subtitle); main.addLayout(header)
        split = QSplitter(Qt.Orientation.Horizontal); main.addWidget(split, 1)

        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 10, 0)
        sh = QHBoxLayout(); section = QLabel("SOUND SOURCES"); section.setObjectName("section")
        add_btn = QPushButton("+ ADD SOURCE"); add_btn.clicked.connect(self.import_audio)
        sh.addWidget(section); sh.addStretch(); sh.addWidget(add_btn); ll.addLayout(sh)
        self.source_rows = QVBoxLayout(); self.source_rows.setSpacing(4)
        panel = QFrame(); panel.setObjectName("panel"); panel.setLayout(self.source_rows); ll.addWidget(panel)

        analysis_box = QGroupBox("ANALYSIS FIELD"); af = QFormLayout(analysis_box)
        self.fft = QComboBox(); self.fft.addItems(["1024", "2048", "4096", "8192", "16384"]); self.fft.setCurrentText("4096")
        self.window = QComboBox(); self.window.addItems(["Hann", "Hamming", "Blackman"])
        self.bands = QComboBox(); self.bands.addItems(["24", "48", "64", "96", "128"]); self.bands.setCurrentText("64")
        af.addRow("FFT SIZE", self.fft); af.addRow("WINDOW", self.window); af.addRow("LOG BANDS", self.bands)
        ll.addWidget(analysis_box)

        comp = QGroupBox("COMPOSITION"); cf = QFormLayout(comp)
        self.screen = QComboBox(); self.screen.addItems(["No guide", *self.assets.screen_names()])
        self.pass_map = QComboBox(); self.pass_map.addItems(["None", *self.assets.pass_names()])
        self.blend = QComboBox(); self.blend.addItems(["Normal", "Add", "Multiply", "Screen", "Difference"])
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(0, 100); self.opacity.setValue(100)
        cf.addRow("SCREEN GUIDE", self.screen); cf.addRow("SCREEN PASS", self.pass_map)
        cf.addRow("BLEND", self.blend); cf.addRow("OPACITY", self.opacity); ll.addWidget(comp); ll.addStretch()

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(10, 0, 0, 0)
        ph = QHBoxLayout(); pt = QLabel("COMPOSITION VIEW"); pt.setObjectName("section")
        zoom = QComboBox(); zoom.addItems(["FIT", "50%", "66%", "75%", "100%"])
        ph.addWidget(pt); ph.addStretch(); ph.addWidget(QLabel("CANVAS")); ph.addWidget(zoom); rl.addLayout(ph)
        self.canvas = CompositionCanvas(self.assets); rl.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        self.status = QLabel("NO AUDIO LOADED"); self.status.setObjectName("muted")
        footer.addWidget(QLabel("OUTPUT  1920 × 1440")); footer.addStretch(); footer.addWidget(self.status); rl.addLayout(footer)
        split.addWidget(left); split.addWidget(right); split.setSizes([420, 1000])
        for control in (self.screen, self.pass_map, self.blend):
            control.currentTextChanged.connect(self.update_canvas)
        self.opacity.valueChanged.connect(self.update_canvas)

    def import_audio(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import audio", "",
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg *.mp3);;All files (*)")
        for filename in paths:
            if len(self.sources) >= 7:
                QMessageBox.information(self, "Source limit", "The project supports up to seven audio sources.")
                break
            try:
                source = AudioSource.from_file(Path(filename))
                self.sources.append(source)
                self.source_rows.addWidget(SourceRow(source))
            except Exception as exc:
                QMessageBox.warning(self, "Audio import failed", f"{Path(filename).name}\n{exc}")
        self.status.setText(f"{len(self.sources):02d} / 07 SOURCES READY" if self.sources else "NO AUDIO LOADED")

    def update_canvas(self, *_):
        self.canvas.set_composition(screen=self.screen.currentText(), screen_pass=self.pass_map.currentText(),
            blend=self.blend.currentText(), opacity=self.opacity.value() / 100.0)

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
        QComboBox::drop-down { border:0; width:18px; }
        QSlider::groove:horizontal { height:3px; background:#494949; }
        QSlider::handle:horizontal { background:#dedede; width:10px; margin:-4px 0; border-radius:5px; }
        QCheckBox { spacing:5px; color:#aaa; }
        """)

