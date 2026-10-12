"""Film Desk — a private, offline RAW film conversion desktop application."""
from __future__ import annotations

import os
os.environ.setdefault("OMP_NUM_THREADS", "2")
from pathlib import Path
import argparse
import copy
import json
import sys
import time
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QRectF, QPointF, QSize, QStandardPaths, QUrl, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QIcon, QAction, QKeySequence, QDesktopServices, QFont, QColorSpace, QActionGroup
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QSplitter, QSlider, QComboBox,
    QCheckBox, QFileDialog, QMessageBox, QProgressBar, QScrollArea, QFrame,
    QSpinBox, QDialog, QDialogButtonBox, QAbstractItemView, QSizePolicy, QInputDialog, QLineEdit, QToolButton, QTextBrowser,
)
from engine import (VERSION, RAW_EXTENSIONS, Adjustments, decode_raw, auto_crop,
    reference_from_frame, analyze, render, negative_preview, neutral_balance,
    atomic_json, export_jpeg, clean_crop, neutral_sample_bounds)
from session_state import completion_matches, verified_existing_export, jpeg_digest, finished_export_snapshot

from i18n import (tr as _t, label as _label, button as _push_button, action as _action,
    checkbox as _checkbox, menu as _menu, text as _set_text, tooltip as _set_tip,
    title as _set_title, plain_text as _plain_text, plain_tooltip as _plain_tip,
    combo_item, set_language, default_language, language, retranslate)

LOOK_FIELDS = ["exposure", "contrast", "saturation", "warmth", "tint",
               "shadows", "highlights", "curve", "color_mode", "neutral_gains"]

STYLE = """
QWidget { background: #181b20; color: #e9edf3; font-family: '.AppleSystemUIFont', 'Arial'; font-size: 12px; }
QMainWindow, QMenuBar, QMenu { background: #181b20; }
QMenu::item:selected { background: #343c48; }
QLabel#brand { font-size: 22px; font-weight: 650; color: #f5f7fa; }
QLabel#muted { color: #939eaf; font-size: 11px; }
QLabel#section { color: #aab6c6; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#title { font-size: 14px; font-weight: 600; }
QLabel#hint { color: #a9b5c7; background: #202730; border-radius: 7px; padding: 10px; }
QPushButton { background: #2a303a; border: 1px solid #394252; border-radius: 6px; padding: 7px 11px; }
QPushButton:hover { background: #36404c; border-color: #657384; }
QPushButton:pressed, QPushButton:checked { background: #3a505c; border-color: #7dbdb2; }
QPushButton:disabled { color: #657081; background: #242830; border-color: #2c333d; }
QPushButton#primary { background: #a9dfcf; border-color: #a9dfcf; color: #14251f; font-weight: 650; }
QPushButton#primary:hover { background: #c3eddf; }
QPushButton#primary:disabled { background: #394b47; color: #879b93; border-color: #394b47; }
QComboBox, QSpinBox, QLineEdit { background: #242b34; border: 1px solid #3a4553; border-radius: 5px; padding: 6px; }
QComboBox QAbstractItemView { background: #242b34; selection-background-color: #3b535a; }
QComboBox::drop-down { border: none; width: 20px; }
QSlider::groove:horizontal { background: #3b4450; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #acdcca; border: 1px solid #c5efdf; width: 11px; height: 11px; margin: -4px 0; border-radius: 6px; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; background: #252d35; border: 1px solid #637082; border-radius: 3px; }
QCheckBox::indicator:checked { background: #a9dfcf; border-color: #a9dfcf; image: url(); }
QListWidget { background: #1c2027; border: none; outline: none; padding: 5px; }
QListWidget::item { padding: 7px 4px; margin: 2px; border-radius: 5px; }
QListWidget::item:selected { background: #31474c; color: #e2f8ef; }
QListWidget::item:hover { background: #2a333e; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #1b2028; width: 9px; }
QScrollBar::handle:vertical { background: #495665; min-height: 25px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSplitter::handle { background: #101319; width: 2px; }
QToolButton { text-align: left; background: #242b34; border: 1px solid #394252; border-radius: 6px; padding: 9px; }
QToolButton:hover { background: #303945; }
QProgressBar { border: none; background: #303946; border-radius: 3px; height: 7px; color: transparent; }
QProgressBar::chunk { background: #a9dfcf; border-radius: 3px; }
QToolTip { background: #303945; color: #f0f5fa; border: 1px solid #6a7a8e; padding: 6px; }
"""


def qimage(pixels):
    a = np.ascontiguousarray(pixels, dtype=np.uint8)
    image = QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_RGB888).copy()
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image


class JobSignals(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(object)
    finished = Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.done.emit(self.function(self.signals.progress.emit))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class PhotoCanvas(QWidget):
    crop_changed = Signal(object)
    neutral_clicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pixmap = None
        self.crop = [0, 0, 1, 1]
        self.mode = "view"
        self.zoom = 1.
        self.offset = QPointF()
        self.rect = QRectF()
        self.start = None
        self.drag_start = None
        self.sample_point = None
        self.message = "Open a folder of RAW film scans"
        self.setMouseTracking(True)

    def set_image(self, pixels, reset=False):
        self.pixmap = QPixmap.fromImage(qimage(pixels))
        if reset:
            self.fit()
        self.update()

    def fit(self):
        self.zoom = 1.
        self.offset = QPointF()
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.start = None
        self.sample_point = None
        if mode != "view":
            self.fit()
        self.setCursor(Qt.CursorShape.CrossCursor if mode != "view" else Qt.CursorShape.OpenHandCursor)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), QColor("#11151a"))
        if self.pixmap is None:
            painter.setPen(QColor("#99a6b6"))
            painter.setFont(QFont("Arial", 16))
            painter.drawText(self.rect if not self.rect.isEmpty() else QRectF(0,0,self.width(),self.height()),
                             Qt.AlignmentFlag.AlignCenter, _t(self.message))
            return
        w, h = self.pixmap.width(), self.pixmap.height()
        scale = min((self.width()-36)/w, (self.height()-36)/h) * self.zoom
        self.rect = QRectF((self.width()-w*scale)/2+self.offset.x(),
                           (self.height()-h*scale)/2+self.offset.y(), w*scale, h*scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect, self.pixmap, QRectF(0, 0, w, h))
        if self.mode == "crop":
            x0, y0, x1, y1 = self.crop
            box = QRectF(self.rect.left()+x0*self.rect.width(), self.rect.top()+y0*self.rect.height(),
                         (x1-x0)*self.rect.width(), (y1-y0)*self.rect.height())
            painter.setBrush(QColor(0,0,0,110))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(self.rect.left(),self.rect.top(),self.rect.width(),box.top()-self.rect.top()))
            painter.drawRect(QRectF(self.rect.left(),box.bottom(),self.rect.width(),self.rect.bottom()-box.bottom()))
            painter.drawRect(QRectF(self.rect.left(),box.top(),box.left()-self.rect.left(),box.height()))
            painter.drawRect(QRectF(box.right(),box.top(),self.rect.right()-box.right(),box.height()))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#b8f1dc"), 2))
            painter.drawRect(box)
            painter.setPen(QPen(QColor(184,241,220,100), 1))
            for frac in (1/3, 2/3):
                painter.drawLine(QPointF(box.left()+box.width()*frac,box.top()), QPointF(box.left()+box.width()*frac,box.bottom()))
                painter.drawLine(QPointF(box.left(),box.top()+box.height()*frac), QPointF(box.right(),box.top()+box.height()*frac))
        elif self.mode == "neutral" and self.sample_point is not None:
            box = self.neutral_sample_rect()
            # Two outlines remain legible on both light and dark objects.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#11151a"), 3))
            painter.drawRect(box)
            painter.setPen(QPen(QColor("#b8f1dc"), 1))
            painter.drawRect(box)

    def neutral_sample_rect(self):
        if self.pixmap is None or self.sample_point is None:
            return QRectF()
        w, h = self.pixmap.width(), self.pixmap.height()
        x0, y0, x1, y1 = neutral_sample_bounds(w, h, self.sample_point)
        return QRectF(self.rect.left()+x0*self.rect.width()/w,
                      self.rect.top()+y0*self.rect.height()/h,
                      (x1-x0)*self.rect.width()/w,
                      (y1-y0)*self.rect.height()/h)

    def point(self, position):
        if not self.pixmap or not self.rect.contains(position):
            return None
        return [(position.x()-self.rect.left())/self.rect.width(),
                (position.y()-self.rect.top())/self.rect.height()]

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.point(event.position())
        if self.mode == "neutral" and point:
            self.sample_point = point
            self.update()
            self.neutral_clicked.emit(point)
        elif self.mode == "crop" and point:
            self.start = point
        elif self.mode == "view":
            self.drag_start = event.position()

    def mouseMoveEvent(self, event):
        if self.mode == "neutral":
            self.sample_point = self.point(event.position())
            self.update()
        elif self.mode == "crop" and self.start:
            point = self.point(event.position())
            if point:
                self.crop = [min(self.start[0],point[0]), min(self.start[1],point[1]),
                             max(self.start[0],point[0]), max(self.start[1],point[1])]
                self.update()
        elif self.drag_start is not None:
            self.offset += event.position()-self.drag_start
            self.drag_start = event.position()
            self.update()

    def leaveEvent(self, event):
        self.sample_point = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "crop" and self.start:
            self.start = None
            try:
                self.crop = clean_crop(self.crop)
                self.crop_changed.emit(self.crop.copy())
            except ValueError:
                pass
        self.drag_start = None

    def wheelEvent(self, event):
        if self.mode == "view":
            self.zoom = max(.6, min(8., self.zoom * (1.15 if event.angleDelta().y() > 0 else 1/1.15)))
            self.update()
        event.accept()


class SliderControl(QWidget):
    changed = Signal()
    committed = Signal()

    def __init__(self, title, minimum, maximum, default, scale=100, suffix=""):
        super().__init__()
        self.scale, self.default, self.suffix = scale, default, suffix
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        row.addWidget(_label(title))
        self.value_label = _label()
        self.value_label.setObjectName("muted")
        row.addWidget(self.value_label, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(row)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(minimum*scale), round(maximum*scale))
        self.slider.setValue(round(default*scale))
        self.slider.valueChanged.connect(self.update_value)
        self.slider.sliderReleased.connect(self.committed.emit)
        layout.addWidget(self.slider)
        self.update_value()

    def update_value(self):
        value = self.value()
        _set_text(self.value_label, f'{value:+.2f}{self.suffix}' if self.default == 0 else f'{value:.2f}{self.suffix}')
        self.changed.emit()

    def value(self):
        return self.slider.value()/self.scale

    def set_value(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(round(value*self.scale))
        self.slider.blockSignals(False)
        value = self.value()
        _set_text(self.value_label, f'{value:+.2f}{self.suffix}' if self.default == 0 else f'{value:.2f}{self.suffix}')


class FilmDesk(QMainWindow):
    def __init__(self, start_folder=None, session=None):
        super().__init__()
        _set_title(self, 'Film Desk')
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1320,available.width()-40),min(840,available.height()-60))
        self.setMinimumSize(min(1080,available.width()-40),min(680,available.height()-60))
        self.folder = None
        self.paths = []
        self.adjustments = {}
        self.current = None
        self.reference = None
        self.reference_path = None
        self.roll_model = None
        self.models = {}
        self.cache = OrderedDict()
        self.pending_crops = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs = set()
        self.preview_generation = 0
        self.folder_generation = 0
        self.job_running = False
        self.cancel_export = False
        self.output_folder = None
        self.session_path = None
        self.completed_export = None
        self.dirty = False
        self.loading_controls = False
        self.last_pixels = None
        self.last_model = None
        self.undo_stack, self.redo_stack = [], []
        self.slider_snapshot = None
        self.backlight_kelvin = 5500  # Preserve old session notes without exposing an input.
        self.data_dir = Path(os.environ.get("FILMDESK_DATA_DIR") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.presets_path = self.data_dir/"stock-presets.json"  # Keep existing saved tuning compatible.
        self.presets = {}
        if self.presets_path.exists():
            try:
                self.presets = json.loads(self.presets_path.read_text())
                if not isinstance(self.presets,dict):
                    raise ValueError("Invalid preset collection")
                for name, settings in self.presets.items():
                    if not isinstance(name,str) or not isinstance(settings,dict):
                        raise ValueError("Invalid saved adjustments")
                    Adjustments.from_dict(settings)
            except (OSError, ValueError,TypeError):
                self.presets = {}
        self.preferences_path=self.data_dir/'preferences.json'
        try:
            preferences=json.loads(self.preferences_path.read_text())
            preferred=preferences.get('language',default_language())
        except (OSError,ValueError,TypeError,AttributeError):
            preferred=default_language()
        set_language(os.environ.get('FILMDESK_LANGUAGE') or preferred)
        self.language=language()
        self.build_ui()
        self.build_menu()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(140)
        self.preview_timer.timeout.connect(self.request_preview)
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setSingleShot(True)
        self.recovery_timer.setInterval(1200)
        self.recovery_timer.timeout.connect(self.write_recovery)
        self.thumbnail_timer=QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.setInterval(120)
        self.thumbnail_timer.timeout.connect(self.prepare_roll)
        self.startup_timer=QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(100)
        if session:
            self.startup_timer.timeout.connect(lambda:self.load_session(Path(session)))
            self.startup_timer.start()
        elif start_folder:
            self.startup_timer.timeout.connect(lambda:self.load_folder(Path(start_folder)))
            self.startup_timer.start()
        else:
            recovery = self.data_dir/"last-session.filmdesk"
            if recovery.exists():
                self.startup_timer.timeout.connect(lambda:self.resume_recovery(recovery))
                self.startup_timer.start()

    def resume_recovery(self,path):
        # Show the window before touching a scan folder on an external drive
        # or a folder that may need a macOS file-access grant.
        try:
            data=json.loads(path.read_text())
            if completion_matches(data):
                _set_text(self.recovery_button, 'Reopen last roll')
                self.recovery_button.show()
                _set_text(self.photo_title, 'Ready for a new roll')
                self.canvas.message="Open a scan folder to start a new roll"
                self.canvas.update()
                self.status('Last roll exported. Open a new folder, or reopen the last roll to revise it.')
                return
            available=bool(data.get('folder')) and Path(data['folder']).is_dir() and data.get('app')=='Film Desk'
        except (OSError,ValueError,TypeError):
            available=False
        if available:
            self.load_session(path)
        else:
            self.recovery_button.show()
            self.status("Your last scan folder isn't available. Continue last session to locate it, or open another folder.")

    def button(self, title, function, primary=False, checkable=False, tip=None):
        button = _push_button(title)
        button.setCheckable(checkable)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(function)
        if tip:
            _set_tip(button, tip)
        return button

    def section(self, title):
        label = _label(title.upper())
        label.setObjectName("section")
        return label

    def build_ui(self):
        container=QWidget();self.setCentralWidget(container)
        outer=QVBoxLayout(container);outer.setContentsMargins(16,12,16,10);outer.setSpacing(12)
        header=QHBoxLayout()
        name=_label('Film Desk');name.setObjectName("brand");header.addWidget(name)
        tagline=_label('Scan. Adjust. Enjoy.');tagline.setObjectName("muted");header.addWidget(tagline)
        header.addStretch()
        self.open_button=self.button("Open folder…",self.choose_folder,tip="Choose the folder containing your camera RAW scans.")
        header.addWidget(self.open_button)
        self.export_button=self.button("Export JPEGs…",self.start_export,primary=True,tip="Save the checked photos as full-resolution JPEGs, keeping their original filenames.")
        header.addWidget(self.export_button);outer.addLayout(header)
        self.split=QSplitter(Qt.Orientation.Horizontal);outer.addWidget(self.split,1)

        left=QWidget();left_layout=QVBoxLayout(left);left_layout.setContentsMargins(0,0,8,0)
        left_layout.addWidget(self.section("1 · Choose photos"))
        self.folder_label=_label('No folder open');self.folder_label.setWordWrap(True);self.folder_label.setObjectName("muted")
        left_layout.addWidget(self.folder_label)
        self.list=QListWidget();self.list.setIconSize(QSize(72,48))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        _set_tip(self.list, 'Click a photo to review it. Uncheck any photo you do not want to export.')
        self.list.currentRowChanged.connect(self.select_photo);self.list.itemChanged.connect(self.include_changed)
        left_layout.addWidget(self.list,1)
        self.count_label=_label('Original RAWs stay untouched');self.count_label.setObjectName("muted");left_layout.addWidget(self.count_label)
        self.recovery_button=self.button("Continue last session",lambda:self.load_session(self.data_dir/"last-session.filmdesk"),tip="Reopen the photos and edits from your last visit.")
        self.recovery_button.hide();left_layout.addWidget(self.recovery_button)
        self.reference_label=_label('Blank reference needed\nSelect the unexposed frame first.')
        self.reference_label.setObjectName("hint");self.reference_label.setWordWrap(True);left_layout.addWidget(self.reference_label)
        self.reference_button=self.button("Set blank reference",self.use_current_reference,tip="Use the selected unexposed frame to measure the film's base color. It will be excluded from export.")
        left_layout.addWidget(self.reference_button);self.split.addWidget(left)

        middle=QWidget();middle_layout=QVBoxLayout(middle);middle_layout.setContentsMargins(10,0,10,0)
        self.photo_title=_label('Welcome');self.photo_title.setObjectName("title");middle_layout.addWidget(self.photo_title)
        toolbar=QHBoxLayout()
        self.original_button=self.button("Show negative",self.toggle_original,checkable=True,tip="Compare the original camera scan with the converted positive.")
        toolbar.addWidget(self.original_button)
        self.crop_button=self.button("Crop photo",self.toggle_crop,checkable=True,tip="Drag around one film photo, then click Done cropping to see the positive.")
        toolbar.addWidget(self.crop_button)
        self.rotate_button=self.button("Rotate 90°",self.rotate,tip="Turn the photo clockwise by a quarter turn.")
        toolbar.addWidget(self.rotate_button);toolbar.addStretch()
        toolbar.addWidget(self.button("Fit",lambda:self.canvas.fit(),tip="Fit the entire photo in the preview after zooming."))
        middle_layout.addLayout(toolbar)
        self.canvas=PhotoCanvas();self.canvas.crop_changed.connect(self.set_crop);self.canvas.neutral_clicked.connect(self.pick_neutral)
        middle_layout.addWidget(self.canvas,1)
        navigation=QHBoxLayout()
        self.previous_button=self.button("‹ Previous",lambda:self.navigate(-1),tip="Review the previous scan.")
        self.next_button=self.button("Next ›",lambda:self.navigate(1),tip="Review the next scan.")
        navigation.addWidget(self.previous_button);navigation.addStretch();navigation.addWidget(self.next_button)
        middle_layout.addLayout(navigation)
        self.image_info=_label('Open a scan folder, set the blank reference, then review your photos.')
        self.image_info.setObjectName("muted");self.image_info.setWordWrap(True);middle_layout.addWidget(self.image_info)
        self.warning_label=_label('');self.warning_label.setObjectName("hint");self.warning_label.setWordWrap(True);self.warning_label.hide()
        middle_layout.addWidget(self.warning_label);self.split.addWidget(middle)

        right_scroll=QScrollArea();right_scroll.setWidgetResizable(True)
        right=QWidget();self.adjustment_panel=right;right_layout=QVBoxLayout(right)
        right_layout.setContentsMargins(10,0,0,0);right_layout.setSpacing(14)
        right_layout.addWidget(self.section("2 · Adjust photo"))
        right_layout.addWidget(_label('Output for this roll'))
        self.output_mode_combo=QComboBox();combo_item(self.output_mode_combo,"Color","Color");combo_item(self.output_mode_combo,"Black & white","Black & white")
        _set_tip(self.output_mode_combo, 'Convert the roll to color or grayscale. Individual brightness settings, crops, and orientation are preserved.')
        self.output_mode_combo.currentIndexChanged.connect(lambda: self.output_mode_changed(self.output_mode_combo.currentData()));right_layout.addWidget(self.output_mode_combo)
        self.conversion_hint=_label('Start with the automatic result. Adjust only what you need.')
        self.conversion_hint.setWordWrap(True);self.conversion_hint.setObjectName("muted");right_layout.addWidget(self.conversion_hint)
        self.sliders={}
        specs=[("exposure","Brightness",-3,3,0," EV","Make the positive lighter or darker."),
               ("contrast","Contrast",.5,1.8,1,"","Increase or soften the difference between light and dark."),
               ("saturation","Color intensity",0,2,1,"","Make colors softer or more vivid."),
               ("warmth","Warmth",-1,1,0,"","Move left for cooler colors, right for warmer colors."),
               ("tint","Green / magenta",-1,1,0,"","Correct a green or magenta color cast."),
               ("shadows","Shadow brightness",-1,1,0,"","Adjust darker areas without changing the whole photo's brightness."),
               ("highlights","Highlight brightness",-1,1,0,"","Adjust the lighter areas of the photo."),
               ("curve","Film response",.5,5,2,"","Change how film density becomes positive tones. The default usually works well.")]
        for key,title,low,high,default,suffix,tip in specs:
            control=SliderControl(title,low,high,default,suffix=suffix);_set_tip(control, tip)
            control.changed.connect(self.sliders_changed);control.slider.sliderPressed.connect(self.begin_slider_edit)
            control.committed.connect(self.commit_slider_edit);self.sliders[key]=control
            if key in {"exposure","contrast","saturation","warmth"}:
                right_layout.addWidget(control)
        self.neutral_button=self.button("Balance colors",self.toggle_neutral,checkable=True,tip="Click a known white or gray object in the positive photo to balance its colors.")
        right_layout.addWidget(self.neutral_button)
        self.neutral_hint=_label('Use a known white or gray object.')
        self.neutral_hint.setObjectName("muted");self.neutral_hint.setWordWrap(True);right_layout.addWidget(self.neutral_hint)
        self.apply_look_button=self.button("Apply adjustments to roll",self.apply_look,tip="Copy brightness and color settings to the other photos. Individual crops stay as they are.")
        right_layout.addWidget(self.apply_look_button)
        self.reset_button=self.button("Reset adjustments",self.reset_current,tip="Reset this photo's brightness and color. Keep its color or black-and-white output, crop, and orientation.")
        right_layout.addWidget(self.reset_button)

        self.advanced_toggle=QToolButton();_set_text(self.advanced_toggle, 'Advanced')
        self.advanced_toggle.setCheckable(True);self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        _set_tip(self.advanced_toggle, 'Optional fine tuning, roll matching, saved adjustments, and reference controls.')
        right_layout.addWidget(self.advanced_toggle)
        self.advanced_panel=QWidget();advanced=QVBoxLayout(self.advanced_panel)
        advanced.setContentsMargins(0,4,0,0);advanced.setSpacing(12)
        for key in ["tint","shadows","highlights","curve"]:
            advanced.addWidget(self.sliders[key])
        advanced.addWidget(self.section("Roll matching"))
        self.mode_combo=QComboBox()
        combo_item(self.mode_combo,"Automatic per photo","Auto color")
        combo_item(self.mode_combo,"Use matched roll response","Roll color")
        _set_tip(self.mode_combo, 'Automatic balances each photo separately. The matched response uses the endpoints saved from a representative color photo.')
        self.mode_combo.currentIndexChanged.connect(lambda: self.mode_changed(self.mode_combo.currentData()));advanced.addWidget(self.mode_combo)
        roll_hint=_label('For similar frames, match the roll to a well-balanced photo. Then apply adjustments to the roll.')
        roll_hint.setWordWrap(True);roll_hint.setObjectName("muted");advanced.addWidget(roll_hint)
        self.match_roll_button=self.button("Match roll to this photo",self.set_roll_color,tip="Use this photo's automatic color response for the roll. Apply adjustments to roll to use it on every photo.")
        advanced.addWidget(self.match_roll_button)
        advanced.addWidget(self.section("Crop and orientation"))
        self.mirror_button=self.button("Flip horizontally",self.mirror,checkable=True,tip="Reverse left and right if writing or the photo appears mirrored.")
        advanced.addWidget(self.mirror_button)
        self.auto_crop_button=self.button("Restore automatic crop",self.automatic_crop,tip="Replace the current crop with the app's automatic estimate.")
        advanced.addWidget(self.auto_crop_button)
        advanced.addWidget(self.button("Use this crop for all photos",self.apply_crop,tip="Copy this rectangle to the roll. Use only if every film frame was positioned the same way."))
        self.prepare_button=self.button("Refresh roll thumbnails",self.prepare_roll,tip="Rebuild every preview after changing settings across the roll.")
        advanced.addWidget(self.prepare_button)
        self.clip_checkbox=_checkbox('Highlight lost detail')
        _set_tip(self.clip_checkbox, 'Show clipped highlights in red and clipped shadows in blue. This overlay is not exported.')
        self.clip_checkbox.toggled.connect(self.display_pixels);advanced.addWidget(self.clip_checkbox)
        advanced.addWidget(self.section("Saved adjustments"))
        self.save_preset_button=self.button("Save adjustments…",self.save_preset,tip="Name and save this photo's brightness and color settings for future scans. Crops and sampled white balance are not saved.")
        advanced.addWidget(self.save_preset_button)
        self.load_preset_button=self.button("Load saved adjustments…",self.load_preset,tip="Apply a saved set of brightness and color settings to this photo. Use Apply adjustments to roll to copy them to the other photos.")
        advanced.addWidget(self.load_preset_button)
        advanced.addWidget(self.section("Blank reference"))
        self.other_ref_button=self.button("Choose a blank frame file…",self.choose_reference,tip="Choose a separate RAW photo of clear, unexposed film as the reference.")
        advanced.addWidget(self.other_ref_button)
        advanced.addWidget(self.button("Use selected frame instead",self.use_current_reference,tip="Replace the blank reference with the currently selected frame."))
        self.clear_ref_button=self.button("Remove blank reference",self.clear_reference,tip="Clear the measured film base and return to conversion without a reference.")
        advanced.addWidget(self.clear_ref_button)
        self.quality=QSpinBox();self.quality.setRange(75,100);self.quality.setValue(95)
        _set_tip(self.quality, 'JPEG quality. 95 is a good default for your scans.')
        # JPEG quality belongs in the export dialog, not the editing panel.
        self.quality.setParent(right);self.quality.hide()
        self.advanced_panel.hide();right_layout.addWidget(self.advanced_panel)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        right_layout.addStretch();right_scroll.setWidget(right);self.split.addWidget(right_scroll)
        self.split.setSizes([225,800,270]);self.split.setStretchFactor(0,0);self.split.setStretchFactor(1,1);self.split.setStretchFactor(2,0)
        left.setMinimumWidth(190);left.setMaximumWidth(300);right_scroll.setMinimumWidth(250);right_scroll.setMaximumWidth(320)
        footer=QHBoxLayout()
        self.status_label=_label('Open a scan folder to begin.');self.status_label.setObjectName("muted");footer.addWidget(self.status_label,1)
        self.progress=QProgressBar();self.progress.setFixedWidth(200);self.progress.hide();footer.addWidget(self.progress)
        self.cancel_button=self.button("Stop after this photo",self.cancel);self.cancel_button.hide();footer.addWidget(self.cancel_button)
        outer.addLayout(footer);self.setAcceptDrops(True);self.update_enabled()

    def toggle_advanced(self,shown):
        self.advanced_panel.setVisible(shown)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def refresh_reference_label(self):
        self.reference_label.setVisible(bool(self.folder))
        if self.reference_path:
            _set_text(self.reference_label, 'Blank reference set\n{p0}\nExcluded from export.', p0=Path(self.reference_path).name)
        else:
            _set_text(self.reference_label, 'Blank reference needed\nSelect the unexposed frame first.')
        self.reference_button.setVisible(bool(self.folder) and not bool(self.reference))

    def refresh_tool_labels(self):
        _set_text(self.original_button, 'Show positive' if self.original_button.isChecked() else 'Show negative')
        _set_text(self.crop_button, 'Done cropping' if self.crop_button.isChecked() else 'Crop photo')
        picking=self.neutral_button.isChecked()
        _set_text(self.neutral_button, 'Cancel color picker' if picking else 'Balance colors')
        _set_text(self.neutral_hint, 'The box shows what will be sampled. Keep it inside a white or gray area, away from edges and clipped highlights.' if picking else 'Use a known white or gray object.')

    def build_menu(self):
        menu = _menu(self.menuBar(), 'File')
        for label, shortcut, callback in [
            ("Open folder…", "Ctrl+O", self.choose_folder),
            ("Open saved edits…", "Ctrl+Shift+O", self.choose_session),
            ("Save edits…", "Ctrl+S", self.save_session),
            ("Export JPEGs…", "Ctrl+E", self.start_export),
        ]:
            action = _action(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            menu.addAction(action)
            if callback==self.save_session:
                self.session_action=action
        edit = _menu(self.menuBar(), 'Edit')
        for label,shortcut,callback in [("Undo","Ctrl+Z",self.undo),("Redo","Ctrl+Shift+Z",self.redo)]:
            action=_action(label, self);action.setShortcut(QKeySequence(shortcut));action.triggered.connect(callback);edit.addAction(action)
        language_menu=self.menuBar().addMenu('Language / 语言')
        self.language_actions={};self.language_group=QActionGroup(self)
        self.language_group.setExclusive(True)
        for code,name in [('en','English'),('zh_CN','简体中文')]:
            choice=QAction(name,self);choice.setCheckable(True);choice.setChecked(code==self.language)
            choice.triggered.connect(lambda checked,code=code:self.change_language(code))
            self.language_group.addAction(choice);language_menu.addAction(choice)
            self.language_actions[code]=choice
        help_menu = _menu(self.menuBar(), 'Help')
        action = _action('How to use Film Desk', self)
        action.triggered.connect(self.show_help)
        help_menu.addAction(action)
        scanning=_action('How to photograph film…', self)
        scanning.triggered.connect(self.show_scanning_guide)
        help_menu.addAction(scanning)
        cameras=_action('Camera support…', self)
        cameras.triggered.connect(self.show_camera_support)
        help_menu.addAction(cameras)
        about=_action('About Film Desk', self)
        about.triggered.connect(lambda: QMessageBox.information(self, _t('Film Desk'), _t('Film Desk {p0}\nBuilt for your camera-scanned negatives.\nRAW decoding by LibRaw/rawpy.\nGeneric editable film response; no measured stock profiles.\nNo photos leave your computer.', p0=VERSION)))
        help_menu.addAction(about)
        self.update_enabled()

    def change_language(self,code):
        set_language(code);self.language=language()
        retranslate(self)
        for value,choice in self.language_actions.items():
            choice.setChecked(value==self.language)
        self.canvas.update()
        try:
            atomic_json(self.preferences_path,{'language':self.language})
        except OSError as exc:
            self.show_error(str(exc))

    def status(self, text, **values):
        _set_text(self.status_label, text, **values)

    def submit(self, function, done, error=None, progress=None):
        job = Job(function)
        self.jobs.add(job)
        job.signals.done.connect(done)
        job.signals.error.connect(error or self.show_error)
        if progress:
            job.signals.progress.connect(progress)
        job.signals.finished.connect(lambda: self.jobs.discard(job))
        self.pool.start(job)
        return job

    def show_error(self, message):
        self.status('Couldn’t complete that operation.')
        QMessageBox.warning(self, _t('Film Desk'), _t(message))

    def update_enabled(self):
        ready = self.current is not None and not self.job_running
        for button in [self.reference_button,self.original_button,self.crop_button,self.auto_crop_button,
                       self.rotate_button,self.mirror_button,self.neutral_button]:
            button.setEnabled(ready)
        self.export_button.setEnabled(not self.job_running and any(a.included and key!=self.reference_path for key,a in self.adjustments.items()))
        self.prepare_button.setEnabled(bool(self.paths) and not self.job_running)
        self.open_button.setEnabled(not self.job_running)
        self.other_ref_button.setEnabled(not self.job_running)
        self.clear_ref_button.setEnabled(bool(self.reference) and not self.job_running)
        if hasattr(self,"session_action"):
            self.session_action.setEnabled(bool(self.paths) and not self.job_running)
        self.adjustment_panel.setEnabled(ready)
        self.previous_button.setEnabled(ready and self.list.currentRow()>0)
        self.next_button.setEnabled(ready and self.list.currentRow()<len(self.paths)-1)
        self.neutral_button.setEnabled(ready and self.current!=self.reference_path and
            self.last_model is not None and self.adjustments[self.current].color_mode!="Black & white")
        self.apply_look_button.setEnabled(ready and self.current!=self.reference_path)
        self.reset_button.setEnabled(ready and self.current!=self.reference_path)
        editable=ready and self.current!=self.reference_path
        color=editable and self.adjustments[self.current].color_mode!="Black & white"
        self.mode_combo.setEnabled(color)
        self.match_roll_button.setEnabled(color)
        self.save_preset_button.setEnabled(editable)
        self.load_preset_button.setEnabled(editable and bool(self.presets))
        self.refresh_reference_label()

    def cache_put(self, path, frame):
        key=str(path)
        self.cache[key]=frame
        self.cache.move_to_end(key)
        while len(self.cache)>5:
            self.cache.popitem(last=False)

    def choose_folder(self):
        if self.job_running:
            return
        directory=QFileDialog.getExistingDirectory(self, _t('Choose a folder of RAW film scans'), str(self.folder or Path.home() / 'Desktop'))
        if directory:
            self.load_folder(Path(directory))

    def load_folder(self, folder, restoring=False, loaded=None):
        if self.job_running:
            return
        self.cancel_export=False;self.cancel_button.setEnabled(True)
        self.set_busy(True,"Opening scan folder…",0)
        def discover(progress):
            resolved=Path(folder).expanduser().resolve()
            if not resolved.is_dir():
                raise ValueError(f"Folder not found: {resolved}")
            paths=sorted([p for p in resolved.iterdir() if p.suffix.lower() in RAW_EXTENSIONS and p.is_file()],key=lambda p:p.name.casefold())
            if not paths:
                raise ValueError("No camera RAW scans found in this folder. Choose the folder containing your ARW, DNG, or other camera RAW files.")
            return resolved,paths
        def done(result):
            self.set_busy(False);self.cancel_button.setEnabled(True)
            if self.cancel_export:
                self.status('Opening folder cancelled.')
                return
            resolved,paths=result
            self.install_folder(resolved,paths,restoring)
            if loaded:
                loaded()
        def error(message):
            self.set_busy(False);self.cancel_button.setEnabled(True)
            if not self.cancel_export:
                self.show_error(message)
        self.submit(discover,done,error)

    def install_folder(self,folder,paths,restoring=False):
        if self.paths and not restoring:
            self.write_recovery()
        self.folder_generation+=1
        self.preview_generation+=1
        self.folder=folder.resolve()
        self.paths=paths
        self.adjustments={str(p):Adjustments() for p in paths}
        self.pending_crops={str(p) for p in paths}
        self.models.clear(); self.cache.clear()
        self.current=None
        self.reference=None;self.reference_path=None;self.roll_model=None
        self.session_path=None;self.output_folder=None
        self.completed_export=None
        self.undo_stack.clear();self.redo_stack.clear()
        _plain_text(self.folder_label, folder.name)
        _plain_tip(self.folder_label, str(folder))
        self.list.blockSignals(True); self.list.clear()
        for p in paths:
            item=QListWidgetItem(p.stem)
            _plain_tip(item, p.name)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setSizeHint(QSize(190,64))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.refresh_reference_label()
        self.original_button.setChecked(False);self.crop_button.setChecked(False);self.neutral_button.setChecked(False)
        self.canvas.set_mode("view")
        self.recovery_button.hide()
        self.mark_dirty()
        self.update_count()
        if not restoring:
            self.list.setCurrentRow(0)
        self.update_enabled()
        self.thumbnail_timer.start()

    def update_count(self):
        count=sum(a.included for a in self.adjustments.values())
        _set_text(self.count_label, '{p0} selected for export · {p1} scans', p0=count, p1=len(self.paths))

    def select_photo(self, row):
        if row<0 or row>=len(self.paths):
            return
        self.commit_slider_edit()
        self.current=str(self.paths[row])
        self.last_model=None
        self.canvas.fit()
        self.original_button.setChecked(False);self.crop_button.setChecked(False);self.neutral_button.setChecked(False)
        self.canvas.set_mode("view")
        _plain_text(self.photo_title, self.paths[row].name)
        self.load_controls()
        self.refresh_tool_labels()
        self.update_enabled()
        self.request_preview()

    def include_changed(self, item):
        row=self.list.row(item)
        if row<0:
            return
        key=str(self.paths[row])
        if self.reference_path==key and item.checkState()==Qt.CheckState.Checked:
            self.list.blockSignals(True);item.setCheckState(Qt.CheckState.Unchecked);self.list.blockSignals(False)
            self.status('The blank film-base reference is excluded from JPEG export.')
            return
        self.adjustments[key].included=item.checkState()==Qt.CheckState.Checked
        self.update_count();self.mark_dirty();self.update_enabled()

    def navigate(self,step):
        if self.paths and not self.job_running:
            self.list.setCurrentRow(max(0,min(len(self.paths)-1,self.list.currentRow()+step)))

    def request_preview(self):
        if not self.current:
            return
        self.preview_generation+=1
        generation=self.preview_generation
        folder_generation=self.folder_generation
        key=self.current
        settings=copy.deepcopy(self.adjustments[key])
        reference=copy.deepcopy(self.reference)
        roll_model=copy.deepcopy(self.roll_model)
        frame=self.cache.get(key)
        pending=key in self.pending_crops
        original=self.original_button.isChecked() or self.crop_button.isChecked() or key==self.reference_path
        self.status('Preparing {p0}…', p0=Path(key).name)
        def work(progress):
            decoded=frame or decode_raw(key)
            if pending:
                settings.crop=auto_crop(decoded)
            if original:
                pixels=negative_preview(decoded);model=None
            else:
                pixels,model=render(decoded,settings,reference,roll_model=roll_model)
            return {"key":key,"frame":decoded,"settings":settings,"pixels":pixels,"model":model,
                    "generation":generation,"folder_generation":folder_generation,"original":original}
        self.submit(work,self.preview_ready,lambda e:self.preview_error(e,generation))

    def preview_error(self, message, generation):
        if generation==self.preview_generation:
            self.show_error(message)

    def preview_ready(self, data):
        if data["folder_generation"]!=self.folder_generation:
            return
        key=data["key"]
        self.cache_put(key,data["frame"])
        if key in self.pending_crops:
            self.adjustments[key].crop=data["settings"].crop
            self.pending_crops.discard(key)
        if data["generation"]!=self.preview_generation or key!=self.current:
            return
        self.last_pixels=data["pixels"]
        self.last_model=data["model"]
        if self.last_model:
            self.models[key]=self.last_model
        self.canvas.crop=self.adjustments[key].crop.copy()
        self.display_pixels()
        self.update_thumbnail(key,data["pixels"])
        h,w=data["pixels"].shape[:2]
        metadata=data["frame"].metadata
        _set_text(self.image_info, 'Scroll to zoom · drag to pan · full-resolution JPEGs on export')
        warnings=[]
        if key==self.reference_path:
            warnings.append("Film-base reference. This frame will not be exported. Use Crop to isolate clear, unexposed film.")
        elif not self.reference:
            warnings.append("No blank reference set. Auto color can still convert; add a film-base reference for a repeatable roll setup.")
        if metadata["sensor_clip_percent"]>.05:
            warnings.append(f"{metadata['sensor_clip_percent']:.2f}% of the whole RAW capture is sensor-clipped; check the film area.")
        if key!=self.reference_path and self.adjustments[key].color_mode!="Black & white" and metadata.get('camera_matrix_verified',True) is False:
            warnings.append("Camera color transform could not be verified. Inspect the positive colors before exporting.")
        if self.last_model and self.last_model.get("warning"):
            warnings.append(self.last_model["warning"])
        _set_text(self.warning_label, '\n'.join(warnings));self.warning_label.setVisible(bool(warnings))
        self.update_enabled()
        if not self.job_running:
            self.status('Your original RAWs stay untouched.')

    def display_pixels(self):
        if self.last_pixels is None:
            return
        pixels=self.last_pixels
        if self.clip_checkbox.isChecked() and not(self.original_button.isChecked() or self.crop_button.isChecked() or self.current==self.reference_path):
            pixels=pixels.copy()
            low=np.all(pixels<=1,axis=2);high=np.any(pixels>=254,axis=2)
            pixels[low]=[68,123,255];pixels[high]=[255,63,91]
        self.canvas.set_image(pixels)

    def update_thumbnail(self,key,pixels):
        if key not in self.adjustments:
            return
        index=next((i for i,p in enumerate(self.paths) if str(p)==key),None)
        if index is None:
            return
        pix=QPixmap.fromImage(qimage(pixels)).scaled(72,48,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        self.list.item(index).setIcon(QIcon(pix))

    def load_controls(self):
        if not self.current:
            return
        self.loading_controls=True
        a=self.adjustments[self.current]
        self.output_mode_combo.setCurrentIndex(self.output_mode_combo.findData("Black & white" if a.color_mode=="Black & white" else "Color"))
        self.mode_combo.setCurrentIndex(self.mode_combo.findData("Auto color" if a.color_mode=="Black & white" else a.color_mode))
        self.mode_combo.setEnabled(a.color_mode!="Black & white" and self.current!=self.reference_path and not self.job_running)
        self.match_roll_button.setEnabled(self.mode_combo.isEnabled())
        self.mirror_button.setChecked(a.mirror)
        for key,control in self.sliders.items():
            control.set_value(getattr(a,key))
            control.setEnabled(self.current!=self.reference_path and
                not(a.color_mode=="Black & white" and key in {"saturation","warmth","tint"}))
            control.setVisible(not(a.color_mode=="Black & white" and key in {"saturation","warmth","tint"}))
        self.neutral_button.setVisible(a.color_mode!="Black & white")
        self.neutral_hint.setVisible(a.color_mode!="Black & white")
        _set_text(self.conversion_hint, 'This is your blank reference. Select a photo to adjust.' if self.current == self.reference_path else 'Black-and-white conversion.' if a.color_mode == 'Black & white' else 'Using the matched roll response.' if a.color_mode == 'Roll color' else 'Start with the automatic result. Adjust only what you need.')
        self.loading_controls=False

    def mark_dirty(self):
        self.dirty=True
        if hasattr(self,"recovery_timer"):
            self.recovery_timer.start()

    def checkpoint(self):
        self.undo_stack.append(self.snapshot())
        self.undo_stack=self.undo_stack[-30:]
        self.redo_stack.clear()

    def begin_slider_edit(self):
        self.slider_snapshot=self.snapshot()

    def commit_slider_edit(self):
        if self.slider_snapshot is not None:
            self.undo_stack.append(self.slider_snapshot)
            self.undo_stack=self.undo_stack[-30:]
            self.redo_stack.clear()
            self.slider_snapshot=None

    def sliders_changed(self):
        if self.loading_controls or not self.current or self.job_running:
            return
        if self.slider_snapshot is None:
            self.checkpoint()
        a=self.adjustments[self.current]
        for key,control in self.sliders.items():
            setattr(a,key,control.value())
        self.mark_dirty();self.preview_timer.start()

    def output_mode_changed(self, mode):
        if self.loading_controls or not self.current or self.job_running:
            return
        self.checkpoint()
        for photo,a in self.adjustments.items():
            if photo==self.reference_path:
                continue
            if mode=="Black & white":
                a.color_mode="Black & white"
            elif a.color_mode=="Black & white":
                a.color_mode="Auto color"
        self.neutral_button.setChecked(False);self.canvas.set_mode("crop" if self.crop_button.isChecked() else "view");self.refresh_tool_labels()
        self.load_controls();self.mark_dirty();self.request_preview()
        self.thumbnail_timer.start()
        self.status('{p0} output selected for the roll. Individual adjustments and crops are preserved.', p0=mode)

    def mode_changed(self, mode):
        if self.loading_controls or not self.current or self.job_running:
            return
        if self.adjustments[self.current].color_mode=="Black & white":
            return
        if mode=="Roll color" and not self.roll_model:
            self.status('First click ‘Match roll to this photo’ on a well-balanced positive.')
            self.load_controls()
            return
        self.checkpoint();self.adjustments[self.current].color_mode=mode
        self.load_controls()
        self.mark_dirty();self.request_preview()

    def toggle_original(self):
        self.crop_button.setChecked(False);self.neutral_button.setChecked(False)
        self.canvas.set_mode("view");self.canvas.fit();self.request_preview()
        self.refresh_tool_labels()

    def toggle_crop(self):
        self.original_button.setChecked(False);self.neutral_button.setChecked(False)
        self.canvas.set_mode("crop" if self.crop_button.isChecked() else "view")
        self.refresh_tool_labels()
        self.status('Drag around one film photo, then click Done cropping.' if self.crop_button.isChecked() else 'Crop saved.')
        self.request_preview()

    def toggle_neutral(self):
        if not self.last_model or self.current==self.reference_path:
            self.neutral_button.setChecked(False)
            self.status('Return to the positive preview before picking a neutral point.')
            self.refresh_tool_labels()
            return
        self.original_button.setChecked(False);self.crop_button.setChecked(False)
        self.canvas.set_mode("neutral" if self.neutral_button.isChecked() else "view")
        self.refresh_tool_labels()
        self.status('The box shows the sampled area. Click neutral gray or white; avoid edges and clipped highlights.' if self.neutral_button.isChecked() else 'Color picker closed.')

    def set_crop(self,crop):
        if not self.current or self.job_running:
            return
        self.checkpoint();self.adjustments[self.current].crop=clean_crop(crop)
        self.pending_crops.discard(self.current)
        self.models.pop(self.current,None)
        self.mark_dirty()
        if self.current==self.reference_path and self.current in self.cache:
            try:
                self.reference=reference_from_frame(self.cache[self.current],crop)
                self.models.clear()
                self.status('Film-base sample updated from the new crop.')
            except ValueError as exc:
                self.show_error(str(exc))
        self.request_preview()

    def automatic_crop(self):
        if self.current not in self.cache:
            return
        crop=auto_crop(self.cache[self.current])
        self.set_crop(crop)
        self.canvas.crop=crop
        self.canvas.update()

    def rotate(self):
        if not self.current or self.job_running:
            return
        self.checkpoint();a=self.adjustments[self.current];a.rotation=(a.rotation+1)%4
        self.mark_dirty();self.canvas.fit();self.request_preview()

    def mirror(self):
        if self.loading_controls or not self.current or self.job_running:
            return
        self.checkpoint();self.adjustments[self.current].mirror=self.mirror_button.isChecked()
        self.mark_dirty();self.request_preview()

    def pick_neutral(self,point):
        if self.current not in self.cache or not self.last_model:
            return
        try:
            gains=neutral_balance(self.cache[self.current],self.adjustments[self.current],self.reference,self.last_model,point)
            self.checkpoint();a=self.adjustments[self.current]
            a.neutral_gains=gains;a.warmth=a.tint=0
            self.load_controls();self.mark_dirty()
            self.neutral_button.setChecked(False);self.canvas.set_mode("view")
            self.refresh_tool_labels()
            self.request_preview()
        except ValueError as exc:
            self.show_error(str(exc))

    def reset_balance(self):
        if not self.current or self.job_running:
            return
        self.checkpoint();a=self.adjustments[self.current]
        a.neutral_gains=[1,1,1];a.warmth=a.tint=0
        self.load_controls();self.mark_dirty();self.request_preview()

    def choose_reference(self):
        path,_=QFileDialog.getOpenFileName(self, _t('Choose a clear, unexposed film frame'), str(self.folder or Path.home() / 'Desktop'), _t('Camera RAW (' + ' '.join(('*' + x for x in sorted(RAW_EXTENSIONS))) + ');;All files (*)'))
        if path:
            self.set_reference(path)

    def use_current_reference(self):
        if self.current:
            self.set_reference(self.current)

    def set_reference(self,path):
        if self.job_running:
            return
        path=str(Path(path).resolve())
        self.status('Measuring the unexposed film base…')
        generation=self.folder_generation
        frame=self.cache.get(path)
        crop=self.adjustments[path].crop if path in self.adjustments and path not in self.pending_crops else None
        def work(progress):
            decoded=frame or decode_raw(path)
            return decoded,reference_from_frame(decoded,crop)
        def done(result):
            if generation!=self.folder_generation:
                return
            self.checkpoint()
            decoded,reference=result
            previous=self.reference_path
            self.reference_path=path;self.reference=reference;self.roll_model=None;self.models.clear()
            self.cache_put(path,decoded)
            if previous in self.adjustments and previous!=path:
                self.adjustments[previous].included=True
            if path in self.adjustments:
                self.adjustments[path].included=False;self.adjustments[path].crop=reference["crop"]
                self.pending_crops.discard(path)
            self.sync_checks()
            self.refresh_reference_label()
            _plain_tip(self.reference_label, path)
            if reference["uneven"]:
                self.status('Reference is uneven. Check that its crop contains only clear, unexposed film.')
            self.mark_dirty();self.update_enabled();self.request_preview()
        self.submit(work,done)

    def clear_reference(self):
        if self.job_running:
            return
        self.checkpoint()
        if self.reference_path in self.adjustments:
            self.adjustments[self.reference_path].included=True
        self.reference_path=None;self.reference=None;self.roll_model=None;self.models.clear()
        self.refresh_reference_label()
        self.sync_checks();self.mark_dirty();self.update_enabled();self.request_preview()

    def sync_checks(self):
        self.list.blockSignals(True)
        for i,path in enumerate(self.paths):
            a=self.adjustments[str(path)]
            item=self.list.item(i)
            item.setCheckState(Qt.CheckState.Checked if a.included else Qt.CheckState.Unchecked)
            _plain_text(item, path.stem + (_t(' · base') if str(path) == self.reference_path else ''))
        self.list.blockSignals(False)
        self.update_count()

    def apply_look(self):
        if not self.current or self.job_running:
            return
        self.checkpoint();current=self.adjustments[self.current]
        for key,a in self.adjustments.items():
            if key!=self.reference_path:
                for field in LOOK_FIELDS:
                    setattr(a,field,copy.deepcopy(getattr(current,field)))
        self.models.clear();self.mark_dirty();self.request_preview()
        self.thumbnail_timer.start()
        self.status('Look applied to the roll. Each photo retains its own automatic analysis and crop.')

    def apply_crop(self):
        if not self.current or self.job_running:
            return
        self.checkpoint();crop=self.adjustments[self.current].crop.copy()
        for key,a in self.adjustments.items():
            if key!=self.reference_path:
                a.crop=crop.copy();self.pending_crops.discard(key)
        self.models.clear();self.mark_dirty();self.request_preview()
        self.thumbnail_timer.start()
        self.status('Crop applied to the roll. Check partial scans and differently positioned frames.')

    def set_roll_color(self):
        if not self.last_model or self.job_running or self.current==self.reference_path or self.adjustments[self.current].color_mode=="Black & white":
            self.status('Choose a positive photo first.')
            return
        self.checkpoint();self.roll_model=copy.deepcopy(self.last_model)
        self.adjustments[self.current].color_mode="Roll color"
        self.load_controls();self.mark_dirty();self.request_preview()
        self.status('Roll response saved. Click Apply adjustments to roll to use it for every photo.')

    def save_preset(self):
        if not self.current or self.job_running or self.current==self.reference_path:
            return
        name,accepted=QInputDialog.getText(self, _t('Save adjustments'), _t('Name for these adjustments:'))
        name=name.strip()
        if not accepted or not name:
            return
        if name in self.presets and QMessageBox.question(self, _t('Replace saved adjustments'), _t('Replace ‘{p0}’ with the current adjustments?', p0=name))!=QMessageBox.StandardButton.Yes:
            return
        a=self.adjustments[self.current]
        settings={field:copy.deepcopy(getattr(a,field)) for field in LOOK_FIELDS if field not in {"neutral_gains","color_mode"}}
        settings["color_mode"]="Black & white" if a.color_mode=="Black & white" else "Auto color"
        updated=copy.deepcopy(self.presets);updated[name]=settings
        try:
            atomic_json(self.presets_path,updated)
            self.presets=updated;self.update_enabled()
            self.status('Saved ‘{p0}’ for future scans.', p0=name)
        except OSError as exc:
            self.show_error(str(exc))

    def load_preset(self):
        if not self.current or self.job_running or self.current==self.reference_path or not self.presets:
            return
        name,accepted=QInputDialog.getItem(self, _t('Load saved adjustments'), _t('Apply to this photo:'), sorted(self.presets), 0, False)
        if not accepted or name not in self.presets:
            return
        settings=self.presets[name];defaults=Adjustments.from_dict(settings)
        self.checkpoint();a=self.adjustments[self.current]
        for field in LOOK_FIELDS:
            if field in settings and field!="neutral_gains":
                value=getattr(defaults,field)
                if field=="color_mode" and value=="Roll color":
                    value="Auto color"
                setattr(a,field,copy.deepcopy(value))
        self.neutral_button.setChecked(False);self.canvas.set_mode("crop" if self.crop_button.isChecked() else "view");self.refresh_tool_labels()
        self.models.pop(self.current,None);self.load_controls();self.mark_dirty();self.request_preview()
        self.status('Loaded ‘{p0}’ for this photo. Apply adjustments to roll to copy it to the other photos.', p0=name)

    def reset_current(self):
        if not self.current or self.job_running:
            return
        self.checkpoint();old=self.adjustments[self.current]
        self.adjustments[self.current]=Adjustments(film_stock=old.film_stock,crop=old.crop.copy(),included=old.included,
            rotation=old.rotation,mirror=old.mirror,color_mode="Black & white" if old.color_mode=="Black & white" else "Auto color")
        self.models.pop(self.current,None);self.load_controls();self.mark_dirty();self.request_preview()

    def prepare_roll(self):
        if self.job_running or not self.paths:
            return
        paths=list(self.paths);settings=copy.deepcopy(self.adjustments);reference=copy.deepcopy(self.reference)
        roll=copy.deepcopy(self.roll_model);pending=self.pending_crops.copy();generation=self.folder_generation
        self.set_busy(True,"Preparing photo previews…",len(paths))
        self.cancel_export=False
        def work(progress):
            for index,path in enumerate(paths):
                if self.cancel_export:
                    break
                key=str(path)
                try:
                    frame=decode_raw(path)
                    a=settings[key]
                    if key in pending:
                        a.crop=auto_crop(frame)
                    if key==self.reference_path:
                        pixels=negative_preview(frame);model=None
                    else:
                        pixels,model=render(frame,a,reference,roll_model=roll)
                    image=Image.fromarray(pixels);image.thumbnail((144,96))
                    progress({"index":index+1,"key":key,"pixels":np.array(image),"model":model,"crop":a.crop,"generation":generation})
                except Exception as exc:
                    progress({"index":index+1,"key":key,"error":str(exc),"generation":generation})
            return None
        def progress(data):
            if data["generation"]!=self.folder_generation:
                return
            self.progress.setValue(data["index"])
            if "error" in data:
                self.status('{p0}: {p1}', p0=Path(data['key']).name, p1=data['error'])
                return
            self.update_thumbnail(data["key"],data["pixels"])
            if data["key"] in self.pending_crops:
                self.adjustments[data["key"]].crop=data["crop"];self.pending_crops.discard(data["key"])
            if data["model"]:
                self.models[data["key"]]=data["model"]
            self.status('Prepared {p0} / {p1} previews', p0=data['index'], p1=len(paths))
        def done(result):
            self.set_busy(False);self.mark_dirty();self.request_preview()
        self.submit(work,done,lambda e:(self.set_busy(False),self.show_error(e)),progress)

    def set_busy(self,busy,message="",maximum=1):
        self.job_running=busy
        self.progress.setVisible(busy);self.cancel_button.setVisible(busy)
        self.progress.setRange(0,maximum);self.progress.setValue(0)
        self.split.setEnabled(not busy)
        self.update_enabled()
        if message:
            self.status(message)

    def cancel(self):
        self.cancel_export=True
        self.cancel_button.setEnabled(False)
        self.status('Finishing the current image, then stopping…')

    def start_export(self):
        if self.job_running or not self.paths:
            return
        self.commit_slider_edit()
        selected=[p for p in self.paths if self.adjustments[str(p)].included and str(p)!=self.reference_path]
        if not selected:
            self.show_error("Select at least one photo for export using the checkboxes beside the filenames.")
            return
        dialog=QDialog(self)
        _set_title(dialog, 'Export positive JPEGs')
        dialog.setMinimumWidth(560)
        layout=QVBoxLayout(dialog)
        layout.addWidget(_label('{p0} photos · full resolution · sRGB', p0=len(selected)))
        layout.addWidget(_label('Save in:'))
        row=QHBoxLayout()
        destination_field=QLineEdit(str(self.output_folder or self.folder/"Positive JPEG"))
        row.addWidget(destination_field,1)
        browse=_push_button('Choose…')
        def choose_destination():
            folder=QFileDialog.getExistingDirectory(dialog, _t('Choose an output folder'), destination_field.text())
            if folder:
                _set_text(destination_field, folder)
        browse.clicked.connect(choose_destination);row.addWidget(browse);layout.addLayout(row)
        quality_row=QHBoxLayout();quality_row.addWidget(_label('JPEG quality'))
        export_quality=QSpinBox();export_quality.setRange(75,100);export_quality.setValue(self.quality.value())
        _set_tip(export_quality, '95 is recommended. Higher values create larger files.')
        quality_row.addWidget(export_quality);quality_row.addWidget(_label('95 recommended'));quality_row.addStretch()
        layout.addLayout(quality_row)
        explanation=_label('Original filenames are kept, and your RAWs stay untouched.\nExisting JPEGs are skipped. Choose a new folder for revised edits.')
        explanation.setObjectName("muted");explanation.setWordWrap(True);layout.addWidget(explanation)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        _set_text(buttons.button(QDialogButtonBox.StandardButton.Save), 'Export JPEGs')
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            return
        self.quality.setValue(export_quality.value())
        destination=Path(destination_field.text()).expanduser().resolve()
        if destination.exists() and not destination.is_dir():
            self.show_error("Choose a folder, rather than an existing file, for the JPEG export.")
            return
        # Prevent two differently formatted RAW files with the same stem from
        # silently targeting one JPEG.
        stems=[p.stem.casefold() for p in selected]
        if len(stems)!=len(set(stems)):
            self.show_error("Two selected RAW files have the same base name. Deselect one or place them in separate scan folders before exporting.")
            return
        self.output_folder=destination
        previous=self.snapshot()
        # Persist an unfinished attempt before the worker starts. A crash,
        # cancellation, or failed sidecar write must not hide work at launch.
        self.completed_export=None
        snapshot=self.snapshot();self.write_recovery()
        settings=copy.deepcopy(self.adjustments);reference=copy.deepcopy(self.reference);roll=copy.deepcopy(self.roll_model)
        pending=self.pending_crops.copy();quality=self.quality.value()
        self.cancel_export=False;self.cancel_button.setEnabled(True)
        self.preview_generation+=1
        self.set_busy(True,"Exporting full-resolution JPEGs…",len(selected))
        def work(progress):
            results=[]
            for index,path in enumerate(selected):
                if self.cancel_export:
                    break
                key=str(path);a=settings[key]
                try:
                    output=destination/(path.stem+".jpg")
                    if output.exists():
                        result={"status":"skipped","source":key,"destination":str(output),"reason":"File already exists"}
                        result["verified"]=verified_existing_export(previous,destination,output)
                        if result["verified"]:
                            result["sha256"]=previous['completed_export']['files'][output.name]
                    else:
                        preview=decode_raw(path)
                        if key in pending:
                            a.crop=auto_crop(preview)
                        model=analyze(preview,a,reference,roll)
                        result=export_jpeg(path,output,a,reference,model,quality)
                        result["adjustments"]=asdict(a);result["analysis"]=model
                        if result["status"]=="exported":
                            result["sha256"]=jpeg_digest(output)
                    results.append(result)
                    progress({"index":index+1,"name":path.name,"result":result})
                except Exception as exc:
                    result={"status":"error","source":key,"reason":str(exc)}
                    results.append(result);progress({"index":index+1,"name":path.name,"result":result})
            stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            manifest=destination/("Film-Desk-export-"+stamp+".json")
            finished=finished_export_snapshot(snapshot,results,destination,self.cancel_export)
            atomic_json(manifest,{"app":"Film Desk","version":VERSION,"date":datetime.now().isoformat(),
                "cancelled":self.cancel_export,"reference":reference,"results":results,
                "completed":bool(finished['completed_export'])})
            atomic_json(destination/("Film-Desk-session-"+stamp+".filmdesk"),finished)
            return results,manifest,finished
        def progress(data):
            self.progress.setValue(data["index"])
            self.status('{p0} / {p1} · {p2} · {p3}', p0=data['index'], p1=len(selected), p2=data['name'], p3=data['result']['status'])
        def done(result):
            results,manifest,finished=result
            # Save the crop actually used for export and the completion record.
            for name,settings in finished['photos'].items():
                key=str(self.folder/name)
                if key in self.adjustments:
                    self.adjustments[key]=Adjustments.from_dict(settings)
            self.pending_crops=set(finished.get('pending_crops',[]))
            self.completed_export=finished['completed_export']
            self.set_busy(False);self.cancel_button.setEnabled(True);self.mark_dirty()
            self.load_controls();self.write_recovery()
            exported=sum(r["status"]=="exported" for r in results)
            skipped=sum(r["status"]=="skipped" for r in results)
            errors=[r for r in results if r["status"]=="error"]
            text=f"{exported} JPEGs exported. {skipped} existing files skipped."
            if self.cancel_export:
                text+="\nExport stopped after the current image."
            if errors:
                text+=f"\n{len(errors)} files could not be converted.\n"+"\n".join(Path(r["source"]).name+": "+r["reason"] for r in errors[:5])
            if any(r['status']=='skipped' and not r.get('verified') for r in results):
                text+="\nSkipped JPEGs were not confirmed to match these edits. Choose a new folder to export the current version."
            if self.completed_export:
                text+="\nThis roll is finished. Next launch will be ready for a new roll; your edits remain available."
            text+=f"\n\nSaved in:\n{destination}\n\nOriginal RAW filenames were preserved."
            message=QMessageBox(self);_set_title(message, 'Export finished');_set_text(message, text)
            message.setIcon(QMessageBox.Icon.Warning if errors else QMessageBox.Icon.Information)
            reveal=message.addButton("Show folder",QMessageBox.ButtonRole.ActionRole)
            message.addButton(QMessageBox.StandardButton.Ok);message.exec()
            if message.clickedButton()==reveal:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))
            self.status('Export finished · {p0} saved, {p1} skipped, {p2} errors.', p0=exported, p1=skipped, p2=len(errors))
        def error(message):
            self.set_busy(False);self.cancel_button.setEnabled(True);self.show_error(message)
        self.submit(work,done,error,progress)

    def snapshot(self):
        return {"app":"Film Desk","version":VERSION,"folder":str(self.folder) if self.folder else None,
            "reference_path":self.reference_path,"reference":copy.deepcopy(self.reference),
            "roll_model":copy.deepcopy(self.roll_model),"current":self.current,
            "output_folder":str(self.output_folder) if self.output_folder else None,
            "quality":self.quality.value(),"backlight_kelvin":self.backlight_kelvin,"pending_crops":list(self.pending_crops),
            "completed_export":copy.deepcopy(self.completed_export),
            "photos":{Path(k).name:asdict(v) for k,v in self.adjustments.items()}}

    def restore_snapshot(self,data):
        if not self.folder:
            return
        for name,a in data.get("photos",{}).items():
            key=str(self.folder/Path(name).name)
            if key in self.adjustments:
                self.adjustments[key]=Adjustments.from_dict(a)
        self.reference_path=data.get("reference_path");self.reference=data.get("reference")
        self.roll_model=data.get("roll_model")
        self.pending_crops=set(data.get("pending_crops",[]))&set(self.adjustments)
        self.quality.setValue(data.get("quality",95))
        self.backlight_kelvin=data.get("backlight_kelvin",5500)
        self.output_folder=Path(data["output_folder"]) if data.get("output_folder") else None
        self.completed_export=copy.deepcopy(data.get('completed_export'))
        self.refresh_reference_label()
        self.models.clear();self.sync_checks();self.load_controls();self.mark_dirty();self.update_enabled()

    def write_recovery(self):
        if not self.folder:
            return
        try:
            atomic_json(self.data_dir/"last-session.filmdesk",self.snapshot())
        except OSError:
            self.status('Automatic saving failed. Use File → Save edits to choose another location.')

    def save_session(self):
        if not self.folder or self.job_running:
            return
        filename=str(self.session_path or self.folder/(self.folder.name+".filmdesk"))
        if not self.session_path:
            filename,_=QFileDialog.getSaveFileName(self, _t('Save your edits'), filename, _t('Film Desk saved edits (*.filmdesk)'))
        if filename:
            path=Path(filename)
            if path.suffix.lower()!=".filmdesk":
                path=Path(str(path)+".filmdesk")
            try:
                atomic_json(path,self.snapshot());self.session_path=path;self.dirty=False
                self.status('Session saved: {p0}', p0=path.name)
            except OSError as exc:
                self.show_error(str(exc))

    def choose_session(self):
        if self.job_running:
            return
        filename,_=QFileDialog.getOpenFileName(self, _t('Open saved edits'), str(self.folder or Path.home()), _t('Film Desk saved edits (*.filmdesk)'))
        if filename:
            self.load_session(Path(filename))

    def load_session(self,path):
        if self.job_running:
            return
        try:
            data=json.loads(path.read_text())
            if data.get("app")!="Film Desk" or not data.get("folder"):
                raise ValueError("This is not a Film Desk session")
            folder=Path(data["folder"])
            if not folder.is_dir():
                replacement=QFileDialog.getExistingDirectory(self, _t('Locate the original RAW scan folder'))
                if not replacement:
                    return
                old=folder;folder=Path(replacement);data["folder"]=str(folder)
                if data.get("reference_path") and Path(data["reference_path"]).parent==old:
                    data["reference_path"]=str(folder/Path(data["reference_path"]).name)
                data["pending_crops"]=[str(folder/Path(k).name) for k in data.get("pending_crops",[])]
            # Validate before replacing the active session.
            for a in data.get("photos",{}).values():
                Adjustments.from_dict(a)
            if data.get("reference"):
                base=np.asarray(data["reference"]["base"],dtype=float)
                if base.shape!=(3,) or not np.all(np.isfinite(base)) or np.any(base<=0):
                    raise ValueError("Invalid film-base reference in session")
                clean_crop(data["reference"].get("crop",[0,0,1,1]))
            if data.get("roll_model"):
                low=np.asarray(data["roll_model"]["low"],dtype=float)
                high=np.asarray(data["roll_model"]["high"],dtype=float)
                if low.shape!=(3,) or high.shape!=(3,) or not np.all(np.isfinite([low,high])) or np.any(high<=low):
                    raise ValueError("Invalid roll color model in session")
            def restored():
                self.restore_snapshot(data)
                self.session_path=None if path.resolve()==(self.data_dir/'last-session.filmdesk').resolve() else path
                current=data.get("current")
                row=next((i for i,p in enumerate(self.paths) if p.name==Path(current).name),0) if current else 0
                self.list.setCurrentRow(row);self.dirty=False
                self.status('Opened saved edits: {p0}', p0=path.name)
            self.load_folder(folder,restoring=True,loaded=restored)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.show_error(f"Could not open session: {exc}")

    def undo(self):
        if self.job_running or not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot());self.restore_snapshot(self.undo_stack.pop());self.request_preview()

    def redo(self):
        if self.job_running or not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot());self.restore_snapshot(self.redo_stack.pop());self.request_preview()

    def show_help(self):
        QMessageBox.information(self, _t('Using Film Desk'), _t("1. Open folder: choose your camera RAW scans. Photo previews are prepared automatically.\n\n2. Select the blank, unexposed frame and click Set blank reference. It is excluded from export.\n\n3. Choose Color or Black & white for this roll. Start with the automatic result, then adjust each photo's brightness, contrast, color intensity, or warmth as needed.\n\n4. Balance colors: click a known white or gray object in the photo. Crop photo: drag around one film image, then click Done cropping. Rotate 90° turns the photo clockwise.\n\n5. Apply adjustments to roll copies the color and brightness settings to the other photos, keeping their individual crops. Undo: ⌘Z.\n\n6. Export JPEGs: check the destination, then export. Original filenames and full cropped resolution are retained. Existing JPEGs are skipped, so choose a new folder for revised versions.\n\nUnfinished work reopens on launch. After a confirmed export of every selected photo, the next launch starts fresh; Reopen last roll restores your edits if needed. Editing after export makes the roll unfinished again. Canceled or failed exports keep your work ready to resume. File → Save edits saves a named session; File → Open saved edits reopens it. Original RAWs are never changed.\n\nAdvanced contains optional roll matching, extra tone controls, flipping, saved adjustments, and reference replacement. Save adjustments lets you name tuning for later; Load saved adjustments applies it to the current photo.\n\nHelp → How to photograph film covers scanning light, camera settings, white balance, and the blank reference."))

    def show_scanning_guide(self):
        dialog=QDialog(self);_set_title(dialog, 'How to photograph film')
        available=QApplication.primaryScreen().availableGeometry()
        dialog.resize(min(720,available.width()-60),min(720,available.height()-80))
        layout=QVBoxLayout(dialog)
        guide=QTextBrowser();guide.setOpenExternalLinks(True)
        root=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
        guide.setHtml((root/("assets/scanning-guide.zh-CN.html" if self.language=="zh_CN" else "assets/scanning-guide.html")).read_text(encoding="utf-8"))
        layout.addWidget(guide)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.exec()

    def show_camera_support(self):
        dialog=QDialog(self);_set_title(dialog,'Camera support')
        available=QApplication.primaryScreen().availableGeometry()
        dialog.resize(min(720,available.width()-60),min(720,available.height()-80))
        layout=QVBoxLayout(dialog)
        guide=QTextBrowser();guide.setOpenExternalLinks(True)
        root=Path(sys._MEIPASS) if hasattr(sys,'_MEIPASS') else Path(__file__).parent.parent
        name='SUPPORTED_CAMERAS.zh-CN.md' if self.language=='zh_CN' else 'SUPPORTED_CAMERAS.md'
        guide.setMarkdown((root/name).read_text(encoding='utf-8'))
        layout.addWidget(guide)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.exec()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self,event):
        if self.job_running:
            return
        urls=event.mimeData().urls()
        if urls:
            path=Path(urls[0].toLocalFile())
            if path.suffix==".filmdesk":
                self.load_session(path)
            elif path.is_dir():
                self.load_folder(path)
            elif path.suffix.lower() in RAW_EXTENSIONS:
                self.load_folder(path.parent)

    def closeEvent(self,event):
        self.startup_timer.stop();self.preview_timer.stop();self.recovery_timer.stop();self.thumbnail_timer.stop()
        if self.job_running or self.jobs:
            self.cancel_export=True
            self.status('Finishing background work before closing…')
            event.ignore()
            QTimer.singleShot(300,self.close)
            return
        self.write_recovery()
        event.accept()


class FilmDeskApplication(QApplication):
    """Receive Finder document-open events as well as command-line paths."""
    def __init__(self,arguments):
        super().__init__(arguments)
        self.window=None
        self.pending_file=None

    def event(self,event):
        if event.type()==QEvent.Type.FileOpen:
            self.pending_file=Path(event.file())
            if self.window:
                QTimer.singleShot(0,self.open_pending)
            return True
        return super().event(event)

    def open_pending(self):
        if not self.pending_file or not self.window:
            return
        path=self.pending_file;self.pending_file=None
        if self.window.job_running:
            self.window.status('Finish the current export before opening another session.')
        elif path.suffix.lower()==".filmdesk":
            self.window.load_session(path)
        elif path.is_dir():
            self.window.load_folder(path)
        elif path.suffix.lower() in RAW_EXTENSIONS:
            self.window.load_folder(path.parent)


def main():
    parser=argparse.ArgumentParser(description="Film Desk RAW negative converter")
    parser.add_argument("input",nargs="?",help="A .filmdesk session, RAW scan, or scan folder")
    parser.add_argument("--folder")
    parser.add_argument("--session")
    parser.add_argument("--check-report",help=argparse.SUPPRESS)
    parser.add_argument("--check-raw",help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.input and not(args.folder or args.session):
        path=Path(args.input)
        if path.suffix.lower()==".filmdesk":
            args.session=str(path)
        else:
            args.folder=str(path if path.is_dir() else path.parent)
    if args.check_report:
        import rawpy
        from PySide6.QtCore import qVersion
        report={"app":"Film Desk","version":VERSION,"Qt":qVersion(),"rawpy":rawpy.__version__,
                "LibRaw":list(rawpy.libraw_version),"numpy":np.__version__,"success":True}
        if args.check_raw:
            f=decode_raw(args.check_raw)
            a=Adjustments(crop=auto_crop(f))
            pixels,model=render(f,a)
            report["RAW"]={"source":str(args.check_raw),"preview_size":[pixels.shape[1],pixels.shape[0]],
                           "metadata":f.metadata,"analysis":model}
        atomic_json(args.check_report,report)
        return
    app=FilmDeskApplication(sys.argv)
    app.setApplicationName("Film Desk")
    app.setOrganizationName("Film Desk")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    asset_root=Path(getattr(sys,"_MEIPASS",Path(__file__).parent))
    if (asset_root/"assets/icon.png").exists():
        app.setWindowIcon(QIcon(str(asset_root/"assets/icon.png")))
    window=FilmDesk(args.folder,args.session)
    app.window=window
    window.show()
    if app.pending_file:
        QTimer.singleShot(100,app.open_pending)
    sys.exit(app.exec())


if __name__=="__main__":
    main()
