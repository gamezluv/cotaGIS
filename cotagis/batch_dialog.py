# -*- coding: utf-8 -*-
"""
batch_dialog.py - Diálogo de acotado por lote (capa completa).
Los estilos (extensión, flechas, formato, snap) se definen en Configuración.

Licencia: GNU GPL v3 o posterior.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QCheckBox, QDoubleSpinBox,
    QDialogButtonBox, QGroupBox, QLabel,
)
from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox


class BatchDialog(QDialog):

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CotaGIS — Acotar capa")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)

        self.cbo_layer = QgsMapLayerComboBox()
        filters = QgsMapLayerProxyModel.LineLayer
        filters |= QgsMapLayerProxyModel.PolygonLayer
        self.cbo_layer.setFilters(filters)
        self.chk_sel = QCheckBox("Solo entidades seleccionadas")
        self.chk_sel.setChecked(bool(cfg.get("solo_sel")))

        gb_capa = QGroupBox("Capa a acotar (líneas o polígonos)")
        f0 = QFormLayout(gb_capa)
        f0.addRow("Capa:", self.cbo_layer)
        f0.addRow(self.chk_sel)
        lay.addWidget(gb_capa)

        self.chk_lados = QCheckBox(
            "Lados / segmentos (cota alineada, tipo DIMALIGNED)")
        self.chk_lados.setChecked(bool(cfg.get("lados", True)))
        self.chk_area = QCheckBox("Área de polígonos (A = … m²)")
        self.chk_area.setChecked(bool(cfg.get("area", True)))
        self.chk_per = QCheckBox(
            "Perímetro (polígonos) / longitud total (líneas)")
        self.chk_per.setChecked(bool(cfg.get("perimetro", False)))
        self.chk_ang = QCheckBox("Ángulos internos en vértices (polígonos)")
        self.chk_ang.setChecked(bool(cfg.get("angulos", False)))

        gb_que = QGroupBox("Qué acotar")
        v1 = QVBoxLayout(gb_que)
        for w in (self.chk_lados, self.chk_area, self.chk_per, self.chk_ang):
            v1.addWidget(w)
        lay.addWidget(gb_que)

        f2 = QFormLayout()
        self.spn_min = QDoubleSpinBox()
        self.spn_min.setRange(0.0, 1e9)
        self.spn_min.setDecimals(3)
        self.spn_min.setValue(float(cfg.get("min_len", 0.01)))
        f2.addRow("Longitud mínima a acotar (m):", self.spn_min)
        lay.addLayout(f2)

        hint = QLabel(
            "Estilo de flechas, líneas de extensión, texto y OSNAP se "
            "configuran en «Configuración…» ⚙. Usa un CRS proyectado "
            "(p. ej. EPSG:32718 para Lima).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ------------------------------------------------------------------
    def layer(self):
        return self.cbo_layer.currentLayer()

    def config(self):
        return {
            "solo_sel": self.chk_sel.isChecked(),
            "lados": self.chk_lados.isChecked(),
            "area": self.chk_area.isChecked(),
            "perimetro": self.chk_per.isChecked(),
            "angulos": self.chk_ang.isChecked(),
            "min_len": self.spn_min.value(),
        }
