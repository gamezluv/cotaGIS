# -*- coding: utf-8 -*-
"""
map_tool.py - Herramienta interactiva de cotas con Object Snap (OSNAP).

Un solo QgsMapTool maneja todos los tipos de cota; el cursor se atrae
magnéticamente a vértices, extremos, puntos medios, segmentos, centroides
e intersecciones dentro de una tolerancia en píxeles (configurable).

Licencia: GNU GPL v3 o posterior.
"""

import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsWkbTypes, QgsPointXY, QgsGeometry,
    QgsSnappingConfig, QgsTolerance,
)
from qgis.gui import (
    QgsMapTool, QgsRubberBand, QgsVertexMarker, QgsMapCanvasSnappingUtils,
)

from . import dim_engine


# (id, etiqueta, nº de clics; -1 = encadenado hasta clic derecho)
DIM_MODES = [
    ("lineal",    "Cota lineal (DIMLINEAR)", 3),
    ("alineada",  "Cota alineada (DIMALIGNED)", 3),
    ("continua",  "Cota continua (DIMCONTINUE)", -1),
    ("baseline",  "Cota en línea base (DIMBASELINE)", -1),
    ("angular",   "Cota angular (DIMANGULAR)", 4),
    ("radial",    "Cota radial (DIMRADIUS)", 2),
    ("diametral", "Cota diametral (DIMDIAMETER)", 2),
    ("arco",      "Cota de longitud de arco (DIMARC)", 3),
    ("ordenada",  "Cota de coordenadas (DIMORDINATE)", 2),
]

PROMPTS = {
    "lineal":    ["Clic en el primer punto", "Clic en el segundo punto",
                  "Clic en la posición de la cota (arrastre H o V)"],
    "alineada":  ["Clic en el primer punto", "Clic en el segundo punto",
                  "Clic en la posición de la línea de cota"],
    "continua":  ["Clic en el primer punto", "Clic en el segundo punto",
                  "Clic en la posición de la cota",
                  "Siguiente punto de la cadena (clic derecho = terminar)"],
    "baseline":  ["Clic en el punto base", "Clic en el segundo punto",
                  "Clic en la posición de la primera cota",
                  "Siguiente punto desde la base (clic derecho = terminar)"],
    "angular":   ["Clic en el vértice del ángulo",
                  "Clic en un punto del primer lado",
                  "Clic en un punto del segundo lado",
                  "Clic en la posición del arco de cota"],
    "radial":    ["Clic en el centro", "Clic en un punto de la curva"],
    "diametral": ["Clic en un punto del círculo",
                  "Clic en el punto diametralmente opuesto"],
    "arco":      ["Clic en el inicio del arco",
                  "Clic en un punto intermedio del arco",
                  "Clic en el fin del arco"],
    "ordenada":  ["Clic en el punto a coordinar",
                  "Clic en la posición de la etiqueta"],
}


class DimensionTool(QgsMapTool):
    """Herramienta única para todos los tipos de cota, con OSNAP."""

    def __init__(self, canvas, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.plugin = plugin
        self.mode = "alineada"
        self.points = []
        self.chain = None       # estado de continua / línea base

        self.rb = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.rb.setColor(QColor(230, 60, 60))
        self.rb.setWidth(2)
        self.rb.setLineStyle(Qt.DashLine)
        self.markers = []

        # marcador de snap (cuadro magenta estilo QGIS/AutoCAD)
        self.snap_marker = QgsVertexMarker(canvas)
        self.snap_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.snap_marker.setColor(QColor(255, 0, 200))
        self.snap_marker.setIconSize(13)
        self.snap_marker.setPenWidth(3)
        self.snap_marker.hide()

        self.snap_utils = QgsMapCanvasSnappingUtils(canvas)
        self.apply_snap_config()
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    # OSNAP
    # ------------------------------------------------------------------
    def apply_snap_config(self):
        cfg = self.plugin.cfg
        sc = QgsSnappingConfig(QgsProject.instance())
        sc.setMode(QgsSnappingConfig.AllLayers)
        sc.setTolerance(float(cfg.get("snap_tol_px", 12)))
        sc.setUnits(QgsTolerance.Pixels)
        sc.setIntersectionSnapping(bool(cfg.get("snap_intersection", True)))

        pairs = [
            ("VertexFlag", "snap_vertex"),
            ("SegmentFlag", "snap_segment"),
            ("MiddleOfSegmentFlag", "snap_middle"),
            ("LineEndpointFlag", "snap_endpoint"),
            ("CentroidFlag", "snap_centroid"),
            ("AreaFlag", "snap_area"),
        ]
        flags = None
        for attr, key in pairs:
            if cfg.get(key) and hasattr(QgsSnappingConfig, attr):
                v = getattr(QgsSnappingConfig, attr)
                flags = v if flags is None else (flags | v)

        enabled = bool(cfg.get("snap_enabled", True)) and (
            flags is not None or cfg.get("snap_intersection"))
        sc.setEnabled(enabled)
        if flags is not None:
            if hasattr(sc, "setTypeFlag"):
                sc.setTypeFlag(flags)
            elif hasattr(QgsSnappingConfig, "VertexAndSegment"):
                sc.setType(QgsSnappingConfig.VertexAndSegment)
        self.snap_utils.setConfig(sc)

    def _snap(self, e):
        """Devuelve el punto ajustado (o el crudo) y actualiza el marcador."""
        raw = QgsPointXY(e.mapPoint())
        if not self.plugin.cfg.get("snap_enabled", True):
            self.snap_marker.hide()
            return raw
        try:
            match = self.snap_utils.snapToMap(e.pos())
        except Exception:
            match = None
        if match is not None and match.isValid():
            pt = QgsPointXY(match.point())
            self.snap_marker.setCenter(pt)
            self.snap_marker.show()
            return pt
        self.snap_marker.hide()
        return raw

    # ------------------------------------------------------------------
    # Modo
    # ------------------------------------------------------------------
    def set_mode(self, mode):
        self.mode = mode
        self._reset()
        self._prompt()

    def _prompt(self):
        msgs = PROMPTS.get(self.mode, [])
        i = min(len(self.points), len(msgs) - 1)
        if self.chain is not None:
            i = len(msgs) - 1
        if msgs:
            self.plugin.iface.mainWindow().statusBar().showMessage(
                "CotaGIS [%s] — %s" % (self.mode, msgs[i]))

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    def canvasReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self._reset()
            self._prompt()
            return
        pt = self._snap(e)
        self.points.append(pt)
        self._add_marker(pt)

        try:
            self._maybe_commit()
        except Exception as ex:  # nunca dejar la herramienta rota
            self.plugin.iface.messageBar().pushWarning(
                "CotaGIS", "No se pudo crear la cota: %s" % ex)
            self._reset()
        self._prompt()

    def canvasMoveEvent(self, e):
        cur = self._snap(e)
        self._preview(cur)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._reset()
            self._prompt()

    def deactivate(self):
        self._reset()
        self.snap_marker.hide()
        super().deactivate()

    # ------------------------------------------------------------------
    # Creación de cotas
    # ------------------------------------------------------------------
    def _maybe_commit(self):
        m, pts, cfg = self.mode, self.points, self.plugin.cfg
        crs = QgsProject.instance().crs()
        da = dim_engine._distance_area_for(crs)

        def out(lpt):
            dim_engine.commit("Cotas manuales", crs, cfg, *lpt)
            self.plugin.iface.messageBar().pushSuccess(
                "CotaGIS", "Cota creada.")

        if m == "alineada" and len(pts) == 3:
            p1, p2, pos = pts
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            mag = math.hypot(dx, dy)
            if mag == 0:
                self._reset()
                return
            nx, ny = -dy / mag, dx / mag
            s = (pos.x() - p1.x()) * nx + (pos.y() - p1.y()) * ny
            if s < 0:
                nx, ny, s = -nx, -ny, -s
            c2 = dict(cfg)
            c2["offset"] = max(abs(s), float(cfg["text_size"]) * 0.5)
            val = dim_engine._len_m(da, p1, p2)
            out(dim_engine.build_aligned(
                p1, p2, (nx, ny), c2, dim_engine._fmt_num(val, c2)))
            self._reset()

        elif m == "lineal" and len(pts) == 3:
            p1, p2, pos = pts
            horiz, coord = dim_engine.linear_orientation(p1, p2, pos)
            l, p, t, _ = dim_engine.build_linear_axis(
                p1, p2, horiz, coord, cfg, da)
            out((l, p, t))
            self._reset()

        elif m in ("continua", "baseline"):
            if self.chain is None and len(pts) == 3:
                p1, p2, pos = pts
                horiz, coord = dim_engine.linear_orientation(p1, p2, pos)
                l, p, t, _ = dim_engine.build_linear_axis(
                    p1, p2, horiz, coord, cfg, da)
                out((l, p, t))
                spacing = float(cfg.get("baseline_spacing") or 0) or \
                    float(cfg["text_size"]) * 2.4
                self.chain = {"horiz": horiz, "coord": coord,
                              "base": p1, "last": p2,
                              "spacing": spacing, "i": 1}
            elif self.chain is not None and len(pts) >= 4:
                ch = self.chain
                new = pts[-1]
                if m == "continua":
                    pa, coord = ch["last"], ch["coord"]
                else:  # baseline: siempre desde la base, apilando
                    pa = ch["base"]
                    sgn = 1.0 if ch["coord"] >= (
                        ch["base"].y() if ch["horiz"]
                        else ch["base"].x()) else -1.0
                    coord = ch["coord"] + sgn * ch["spacing"] * ch["i"]
                l, p, t, _ = dim_engine.build_linear_axis(
                    pa, new, ch["horiz"], coord, cfg, da)
                out((l, p, t))
                ch["last"] = new
                ch["i"] += 1

        elif m == "angular" and len(pts) == 4:
            out(dim_engine.build_angular(pts[0], pts[1], pts[2], pts[3], cfg))
            self._reset()

        elif m == "radial" and len(pts) == 2:
            out(dim_engine.build_radial(pts[0], pts[1], cfg, da))
            self._reset()

        elif m == "diametral" and len(pts) == 2:
            out(dim_engine.build_diameter(pts[0], pts[1], cfg, da))
            self._reset()

        elif m == "arco" and len(pts) == 3:
            out(dim_engine.build_arc_length(pts[0], pts[1], pts[2], cfg, da))
            self._reset()

        elif m == "ordenada" and len(pts) == 2:
            out(dim_engine.build_ordinate(pts[0], pts[1], cfg))
            self._reset()

    # ------------------------------------------------------------------
    # Vista previa
    # ------------------------------------------------------------------
    def _preview(self, cur):
        pts = self.points
        if self.chain is not None and pts:
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([self.chain["last"], cur]), None)
            return
        if not pts:
            return
        m = self.mode
        if len(pts) == 1:
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([pts[0], cur]), None)
        elif m == "alineada" and len(pts) == 2:
            p1, p2 = pts
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            mag = math.hypot(dx, dy)
            if mag == 0:
                return
            nx, ny = -dy / mag, dx / mag
            s = (cur.x() - p1.x()) * nx + (cur.y() - p1.y()) * ny
            d1 = QgsPointXY(p1.x() + nx * s, p1.y() + ny * s)
            d2 = QgsPointXY(p2.x() + nx * s, p2.y() + ny * s)
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([p1, d1, d2, p2]), None)
        elif m in ("lineal", "continua", "baseline") and len(pts) == 2:
            p1, p2 = pts
            horiz, coord = dim_engine.linear_orientation(p1, p2, cur)
            if horiz:
                a = QgsPointXY(p1.x(), coord)
                b = QgsPointXY(p2.x(), coord)
            else:
                a = QgsPointXY(coord, p1.y())
                b = QgsPointXY(coord, p2.y())
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([p1, a, b, p2]), None)
        elif m == "angular":
            v = pts[0]
            chain = [pts[i] for i in range(1, len(pts))]
            geoms = []
            for q in chain + [cur]:
                geoms += [v, q]
            self.rb.setToGeometry(QgsGeometry.fromPolylineXY(geoms), None)
        elif m == "arco" and len(pts) == 2:
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([pts[0], pts[1], cur]), None)
        else:
            self.rb.setToGeometry(
                QgsGeometry.fromPolylineXY([pts[-1], cur]), None)

    # ------------------------------------------------------------------
    def _add_marker(self, pt):
        mk = QgsVertexMarker(self.canvas)
        mk.setCenter(pt)
        mk.setColor(QColor(230, 60, 60))
        mk.setIconType(QgsVertexMarker.ICON_CROSS)
        mk.setIconSize(12)
        mk.setPenWidth(2)
        self.markers.append(mk)

    def _reset(self):
        self.points = []
        self.chain = None
        self.rb.reset(QgsWkbTypes.LineGeometry)
        for mk in self.markers:
            self.canvas.scene().removeItem(mk)
        self.markers = []
