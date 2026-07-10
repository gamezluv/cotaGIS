# -*- coding: utf-8 -*-
"""
settings_dialog.py - Configuración del CotaGIS:
Object Snap (OSNAP), líneas de extensión, arrowheads y formato de texto.

Licencia: GNU GPL v3 o posterior.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QFormLayout, QCheckBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox, QDialogButtonBox,
    QGroupBox, QLabel, QTabWidget, QWidget,
)

from .dim_engine import ARROW_STYLES


def _dspin(val, dec=3, mx=1e9, mn=0.0, tip=None):
    s = QDoubleSpinBox()
    s.setRange(mn, mx)
    s.setDecimals(dec)
    s.setValue(float(val))
    if tip:
        s.setToolTip(tip)
    return s


class SettingsDialog(QDialog):
    """Configuración global (persistente) de CotaGIS."""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CotaGIS — Configuración")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ================= Pestaña OSNAP =================
        w_snap = QWidget()
        v = QVBoxLayout(w_snap)

        self.chk_snap = QCheckBox("Activar Object Snap (cursor magnético)")
        self.chk_snap.setChecked(bool(cfg.get("snap_enabled", True)))
        v.addWidget(self.chk_snap)

        gb = QGroupBox("Referencias activas")
        g = QGridLayout(gb)
        self.chk_vertex = QCheckBox("Vértice")
        self.chk_endpoint = QCheckBox("Extremo de línea")
        self.chk_middle = QCheckBox("Punto medio de segmento")
        self.chk_segment = QCheckBox("Punto más cercano en segmento")
        self.chk_centroid = QCheckBox("Centroide")
        self.chk_area = QCheckBox("Interior de área")
        self.chk_inter = QCheckBox("Intersección")
        for w, key in ((self.chk_vertex, "snap_vertex"),
                       (self.chk_endpoint, "snap_endpoint"),
                       (self.chk_middle, "snap_middle"),
                       (self.chk_segment, "snap_segment"),
                       (self.chk_centroid, "snap_centroid"),
                       (self.chk_area, "snap_area"),
                       (self.chk_inter, "snap_intersection")):
            w.setChecked(bool(cfg.get(key)))
        g.addWidget(self.chk_vertex, 0, 0)
        g.addWidget(self.chk_endpoint, 0, 1)
        g.addWidget(self.chk_middle, 1, 0)
        g.addWidget(self.chk_segment, 1, 1)
        g.addWidget(self.chk_centroid, 2, 0)
        g.addWidget(self.chk_area, 2, 1)
        g.addWidget(self.chk_inter, 3, 0)
        v.addWidget(gb)

        f = QFormLayout()
        self.spn_tol = QSpinBox()
        self.spn_tol.setRange(1, 60)
        self.spn_tol.setSuffix(" px")
        self.spn_tol.setValue(int(cfg.get("snap_tol_px", 12)))
        f.addRow("Radio de tolerancia:", self.spn_tol)
        v.addLayout(f)

        note = QLabel("El snap actúa sobre todas las capas visibles del "
                      "proyecto y se marca con un cuadro magenta.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        v.addWidget(note)
        v.addStretch()
        tabs.addTab(w_snap, "Object Snap")

        # ================= Pestaña Estilo de cota =================
        w_sty = QWidget()
        vs = QVBoxLayout(w_sty)

        gb_ext = QGroupBox("Líneas de extensión (extension lines)")
        fe = QFormLayout(gb_ext)
        self.chk_ext = QCheckBox("Dibujar líneas de extensión")
        self.chk_ext.setChecked(bool(cfg.get("ext_lines", True)))
        fe.addRow(self.chk_ext)
        self.spn_gap = _dspin(cfg.get("ext_gap", 0.0),
                              tip="0 = automático")
        fe.addRow("Separación del objeto (gap, unid. mapa; 0 = auto):",
                  self.spn_gap)
        self.spn_over = _dspin(cfg.get("ext_over", 0.0),
                               tip="0 = automático")
        fe.addRow("Sobrepaso (overshoot, unid. mapa; 0 = auto):",
                  self.spn_over)
        vs.addWidget(gb_ext)

        gb_arr = QGroupBox("Extremos (arrowheads)")
        fa = QFormLayout(gb_arr)
        self.cbo_arrow = QComboBox()
        for key, label in ARROW_STYLES:
            self.cbo_arrow.addItem(label, key)
        idx = self.cbo_arrow.findData(cfg.get("arrow", "tick"))
        self.cbo_arrow.setCurrentIndex(max(0, idx))
        fa.addRow("Tipo:", self.cbo_arrow)
        self.spn_arrow = _dspin(cfg.get("arrow_size", 0.0),
                                tip="0 = automático")
        fa.addRow("Tamaño (unid. mapa; 0 = auto):", self.spn_arrow)
        vs.addWidget(gb_arr)
        vs.addStretch()
        tabs.addTab(w_sty, "Extensión y flechas")

        # ================= Pestaña Formato =================
        w_fmt = QWidget()
        ff = QFormLayout(w_fmt)
        self.spn_offset = _dspin(cfg.get("offset", 2.0), mn=0.001)
        ff.addRow("Separación de la línea de cota (unid. mapa):",
                  self.spn_offset)
        self.spn_text = _dspin(cfg.get("text_size", 1.2), mn=0.001)
        ff.addRow("Altura de texto (unid. mapa):", self.spn_text)
        self.spn_dec = QSpinBox()
        self.spn_dec.setRange(0, 6)
        self.spn_dec.setValue(int(cfg.get("decimales", 2)))
        ff.addRow("Decimales:", self.spn_dec)
        self.txt_suf = QLineEdit(cfg.get("sufijo", " m"))
        ff.addRow("Sufijo de unidades:", self.txt_suf)
        self.spn_base = _dspin(cfg.get("baseline_spacing", 0.0),
                               tip="0 = automático")
        ff.addRow("Espaciado de línea base (unid. mapa; 0 = auto):",
                  self.spn_base)
        tabs.addTab(w_fmt, "Formato")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ------------------------------------------------------------------
    def config(self):
        return {
            "snap_enabled": self.chk_snap.isChecked(),
            "snap_vertex": self.chk_vertex.isChecked(),
            "snap_endpoint": self.chk_endpoint.isChecked(),
            "snap_middle": self.chk_middle.isChecked(),
            "snap_segment": self.chk_segment.isChecked(),
            "snap_centroid": self.chk_centroid.isChecked(),
            "snap_area": self.chk_area.isChecked(),
            "snap_intersection": self.chk_inter.isChecked(),
            "snap_tol_px": self.spn_tol.value(),
            "ext_lines": self.chk_ext.isChecked(),
            "ext_gap": self.spn_gap.value(),
            "ext_over": self.spn_over.value(),
            "arrow": self.cbo_arrow.currentData(),
            "arrow_size": self.spn_arrow.value(),
            "offset": self.spn_offset.value(),
            "text_size": self.spn_text.value(),
            "decimales": self.spn_dec.value(),
            "sufijo": self.txt_suf.text(),
            "baseline_spacing": self.spn_base.value(),
        }
