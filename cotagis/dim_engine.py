# -*- coding: utf-8 -*-
"""
dim_engine.py - Motor geométrico del CotaGIS.

Tipos de cota (Dimension Types) al estilo AutoCAD:
  - Alineada (DIMALIGNED), Lineal H/V (DIMLINEAR)
  - Continua (DIMCONTINUE), Línea base (DIMBASELINE)
  - Angular (DIMANGULAR), Radial (DIMRADIUS), Diametral (DIMDIAMETER)
  - Longitud de arco (DIMARC), Coordenadas (DIMORDINATE)

Estilos configurables:
  - Extension lines: mostrar/ocultar, separación (gap) y sobrepaso (overshoot)
  - Arrowheads: tick 45°, flecha abierta, flecha rellena, punto, ninguno

Licencia: GNU GPL v3 o posterior.
"""

import math

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis, QgsMessageLog,
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsWkbTypes, QgsDistanceArea, QgsUnitTypes,
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling, QgsProperty, QgsPropertyCollection,
    QgsLineSymbol, QgsMarkerSymbol, QgsFillSymbol, QgsSingleSymbolRenderer,
)

GROUP_NAME = "Cotas (CotaGIS)"
TWO_PI = 2.0 * math.pi


def compat_enum(new_holder_name, member, legacy_owner, legacy_name):
    """Devuelve el enum moderno (Qgis.<holder>.<member>) si existe;
    si no, el alias antiguo (legacy_owner.legacy_name); si tampoco, None.

    En QGIS 3.32+ algunos alias antiguos (p. ej.
    QgsPalLayerSettings.OverPoint) resuelven al enum equivocado, por lo
    que SIEMPRE se prefiere el enum con espacio de nombres de Qgis.
    """
    holder = getattr(Qgis, new_holder_name, None)
    if holder is not None and hasattr(holder, member):
        return getattr(holder, member)
    return getattr(legacy_owner, legacy_name, None)


def _log(msg):
    QgsMessageLog.logMessage(msg, "CotaGIS")


DEFAULT_CFG = {
    # formato general
    "offset": 2.0,            # separación de la línea de cota (unid. mapa)
    "text_size": 1.2,         # altura de texto (unid. mapa)
    "decimales": 2,
    "sufijo": " m",
    "min_len": 0.01,
    "color": "#111111",
    # líneas de extensión
    "ext_lines": True,
    "ext_gap": 0.0,           # 0 = automático
    "ext_over": 0.0,          # 0 = automático
    # extremos
    # tick | flecha | flecha_rellena | punto | ninguno
    "arrow": "tick",
    "arrow_size": 0.0,        # 0 = automático
    # línea base
    "baseline_spacing": 0.0,  # 0 = automático
    # qué acotar (lote / batch)
    "lados": True, "area": True, "perimetro": False,
    "angulos": False, "solo_sel": False,
    # object snap (OSNAP)
    "snap_enabled": True,
    "snap_vertex": True,
    "snap_endpoint": True,
    "snap_middle": True,
    "snap_segment": False,
    "snap_centroid": False,
    "snap_area": False,
    "snap_intersection": True,
    "snap_tol_px": 12,
}

ARROW_STYLES = [
    ("tick", "Tick arquitectónico (45°)"),
    ("flecha", "Flecha abierta"),
    ("flecha_rellena", "Flecha rellena"),
    ("punto", "Punto"),
    ("ninguno", "Ninguno"),
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _unit(dx, dy):
    mag = math.hypot(dx, dy)
    if mag == 0:
        return 0.0, 0.0
    return dx / mag, dy / mag


def _fmt_num(value, cfg, sufijo=None):
    suf = cfg["sufijo"] if sufijo is None else sufijo
    fmt = "{:,.%df}" % int(cfg["decimales"])
    return fmt.format(value).replace(",", "\u2009") + suf


def _readable_angle_deg(dx, dy):
    """Rotación de etiqueta (grados horarios QGIS) siempre legible."""
    ang = math.degrees(math.atan2(dy, dx))
    if ang > 90.0:
        ang -= 180.0
    elif ang <= -90.0:
        ang += 180.0
    return -ang


def _sizes(cfg):
    off = float(cfg["offset"])
    ts = float(cfg["text_size"])
    gap = float(cfg.get("ext_gap") or 0) or max(off * 0.12, ts * 0.25)
    over = float(cfg.get("ext_over") or 0) or max(off * 0.15, ts * 0.5)
    mark = float(cfg.get("arrow_size") or 0) or max(ts * 0.9, off * 0.2)
    return off, ts, gap, over, mark


def _distance_area_for(crs):
    da = QgsDistanceArea()
    da.setSourceCrs(crs, QgsProject.instance().transformContext())
    ell = QgsProject.instance().ellipsoid()
    if ell:
        da.setEllipsoid(ell)
    return da


def _len_m(da, p1, p2):
    try:
        d = da.measureLine(p1, p2)
        return da.convertLengthMeasurement(d, QgsUnitTypes.DistanceMeters)
    except Exception:
        return math.hypot(p2.x() - p1.x(), p2.y() - p1.y())


def _polyline_len_m(da, pts):
    try:
        d = da.measureLine(pts)
        return da.convertLengthMeasurement(d, QgsUnitTypes.DistanceMeters)
    except Exception:
        return sum(math.hypot(pts[i + 1].x() - pts[i].x(),
                              pts[i + 1].y() - pts[i].y())
                   for i in range(len(pts) - 1))


def _area_m2(da, geom):
    try:
        a = da.measureArea(geom)
        return da.convertAreaMeasurement(a, QgsUnitTypes.AreaSquareMeters)
    except Exception:
        return geom.area()


# ---------------------------------------------------------------------------
# Arrowheads (extremos)
# ---------------------------------------------------------------------------

def _add_arrowhead(tip, inx, iny, cfg, mark, lines, polys):
    """Extremo en `tip`; (inx, iny) apunta hacia el interior de la cota."""
    style = cfg.get("arrow", "tick")
    if style == "ninguno":
        return
    nx, ny = -iny, inx
    if style == "tick":
        tx, ty = _unit(inx + nx, iny + ny)
        h = mark / 2.0
        a = QgsPointXY(tip.x() - tx * h, tip.y() - ty * h)
        b = QgsPointXY(tip.x() + tx * h, tip.y() + ty * h)
        lines.append((QgsGeometry.fromPolylineXY([a, b]), "tick"))
    elif style == "flecha":
        ang = math.radians(18.0)
        for s in (+1, -1):
            wx = inx * math.cos(s * ang) - iny * math.sin(s * ang)
            wy = inx * math.sin(s * ang) + iny * math.cos(s * ang)
            w = QgsPointXY(tip.x() + wx * mark, tip.y() + wy * mark)
            lines.append((QgsGeometry.fromPolylineXY([tip, w]), "tick"))
    elif style == "flecha_rellena":
        half = mark * 0.30
        base = QgsPointXY(tip.x() + inx * mark, tip.y() + iny * mark)
        w1 = QgsPointXY(base.x() + nx * half, base.y() + ny * half)
        w2 = QgsPointXY(base.x() - nx * half, base.y() - ny * half)
        ring = [[tip, w1, w2, tip]]
        polys.append((QgsGeometry.fromPolygonXY(ring), "flecha"))
    elif style == "punto":
        r = mark * 0.32
        ring = [QgsPointXY(tip.x() + r * math.cos(t),
                           tip.y() + r * math.sin(t))
                for t in [i * TWO_PI / 14.0 for i in range(15)]]
        polys.append((QgsGeometry.fromPolygonXY([ring]), "punto"))


def _ext_line(p, nx, ny, gap, top, lines):
    a = QgsPointXY(p.x() + nx * gap, p.y() + ny * gap)
    b = QgsPointXY(p.x() + nx * top, p.y() + ny * top)
    lines.append((QgsGeometry.fromPolylineXY([a, b]), "extension"))


# ---------------------------------------------------------------------------
# Builders de cotas.  Todos devuelven (lines, polys, texts)
#   lines: [(QgsGeometry LineString, tipo)]
#   polys: [(QgsGeometry Polygon, tipo)]
#   texts: [(QgsPointXY, angulo, texto, tipo)]
# ---------------------------------------------------------------------------

def build_aligned(p1, p2, normal, cfg, texto):
    """Cota alineada (DIMALIGNED)."""
    lines, polys, texts = [], [], []
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    L = math.hypot(dx, dy)
    if L <= 0:
        return lines, polys, texts
    ux, uy = dx / L, dy / L
    nx, ny = normal
    off, ts, gap, over, mark = _sizes(cfg)

    d1 = QgsPointXY(p1.x() + nx * off, p1.y() + ny * off)
    d2 = QgsPointXY(p2.x() + nx * off, p2.y() + ny * off)

    if cfg.get("ext_lines", True):
        _ext_line(p1, nx, ny, gap, off + over, lines)
        _ext_line(p2, nx, ny, gap, off + over, lines)
    lines.append((QgsGeometry.fromPolylineXY([d1, d2]), "cota"))
    _add_arrowhead(d1, ux, uy, cfg, mark, lines, polys)
    _add_arrowhead(d2, -ux, -uy, cfg, mark, lines, polys)

    tx = (d1.x() + d2.x()) / 2.0 + nx * ts * 0.85
    ty = (d1.y() + d2.y()) / 2.0 + ny * ts * 0.85
    texts.append((QgsPointXY(tx, ty), _readable_angle_deg(dx, dy),
                  texto, "cota"))
    return lines, polys, texts


def build_linear_axis(p1, p2, horizontal, coord, cfg, da, texto=None):
    """Cota lineal (DIMLINEAR) sobre eje fijo.
    horizontal=True → línea de cota horizontal en y=coord (mide ΔX);
    horizontal=False → vertical en x=coord (mide ΔY)."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)

    if horizontal:
        A = QgsPointXY(p1.x(), coord)
        B = QgsPointXY(p2.x(), coord)
        if abs(A.x() - B.x()) <= 0:
            return lines, polys, texts, 0.0
        if cfg.get("ext_lines", True):
            for p in (p1, p2):
                s = 1.0 if coord >= p.y() else -1.0
                _ext_line(p, 0.0, s, gap, abs(coord - p.y()) + over, lines)
        lines.append((QgsGeometry.fromPolylineXY([A, B]), "cota"))
        ux = 1.0 if B.x() > A.x() else -1.0
        _add_arrowhead(A, ux, 0.0, cfg, mark, lines, polys)
        _add_arrowhead(B, -ux, 0.0, cfg, mark, lines, polys)
        val = _len_m(da, A, B)
        st = 1.0 if coord >= (p1.y() + p2.y()) / 2.0 else -1.0
        tp = QgsPointXY((A.x() + B.x()) / 2.0, coord + st * ts * 0.85)
        texts.append((tp, 0.0, texto or _fmt_num(val, cfg), "cota"))
    else:
        A = QgsPointXY(coord, p1.y())
        B = QgsPointXY(coord, p2.y())
        if abs(A.y() - B.y()) <= 0:
            return lines, polys, texts, 0.0
        if cfg.get("ext_lines", True):
            for p in (p1, p2):
                s = 1.0 if coord >= p.x() else -1.0
                _ext_line(p, s, 0.0, gap, abs(coord - p.x()) + over, lines)
        lines.append((QgsGeometry.fromPolylineXY([A, B]), "cota"))
        uy = 1.0 if B.y() > A.y() else -1.0
        _add_arrowhead(A, 0.0, uy, cfg, mark, lines, polys)
        _add_arrowhead(B, 0.0, -uy, cfg, mark, lines, polys)
        val = _len_m(da, A, B)
        st = 1.0 if coord >= (p1.x() + p2.x()) / 2.0 else -1.0
        tp = QgsPointXY(coord + st * ts * 0.85, (A.y() + B.y()) / 2.0)
        texts.append((tp, -90.0, texto or _fmt_num(val, cfg), "cota"))
    return lines, polys, texts, val


def linear_orientation(p1, p2, pos):
    """Decide H/V como AutoCAD según hacia dónde se arrastra la cota."""
    mx, my = (p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0
    horizontal = abs(pos.y() - my) >= abs(pos.x() - mx)
    coord = pos.y() if horizontal else pos.x()
    return horizontal, coord


def build_angular(v, pa, pb, pos, cfg):
    """Cota angular (DIMANGULAR): vértice + punto en cada lado + posición."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)

    a1 = math.atan2(pa.y() - v.y(), pa.x() - v.x()) % TWO_PI
    a2 = math.atan2(pb.y() - v.y(), pb.x() - v.x()) % TWO_PI
    am = math.atan2(pos.y() - v.y(), pos.x() - v.x()) % TWO_PI
    R = math.hypot(pos.x() - v.x(), pos.y() - v.y())
    d1 = math.hypot(pa.x() - v.x(), pa.y() - v.y())
    d2 = math.hypot(pb.x() - v.x(), pb.y() - v.y())
    if R <= 0 or d1 <= 0 or d2 <= 0:
        return lines, polys, texts

    sweep = (a2 - a1) % TWO_PI
    if (am - a1) % TWO_PI > sweep:      # el clic cae en el otro arco
        a1, a2 = a2, a1
        d1, d2 = d2, d1
        sweep = TWO_PI - sweep
    if sweep <= 1e-9:
        return lines, polys, texts

    # arco
    n = max(8, int(math.degrees(sweep) / 4.0))
    arc = [QgsPointXY(v.x() + R * math.cos(a1 + sweep * i / n),
                      v.y() + R * math.sin(a1 + sweep * i / n))
           for i in range(n + 1)]
    lines.append((QgsGeometry.fromPolylineXY(arc), "cota"))

    # extensión radial hacia los puntos elegidos
    if cfg.get("ext_lines", True):
        for ang, dref in ((a1, d1), (a2, d2)):
            ux, uy = math.cos(ang), math.sin(ang)
            s = 1.0 if R >= dref else -1.0
            r0 = dref + gap * s
            r1 = R + over * s
            lines.append((QgsGeometry.fromPolylineXY(
                [QgsPointXY(v.x() + ux * r0, v.y() + uy * r0),
                 QgsPointXY(v.x() + ux * r1, v.y() + uy * r1)]), "extension"))

    # flechas tangentes
    t1x, t1y = -math.sin(a1), math.cos(a1)
    ae = a1 + sweep
    t2x, t2y = -math.sin(ae), math.cos(ae)
    _add_arrowhead(arc[0], t1x, t1y, cfg, mark, lines, polys)
    _add_arrowhead(arc[-1], -t2x, -t2y, cfg, mark, lines, polys)

    amid = a1 + sweep / 2.0
    rp = R + ts * 0.9
    tp = QgsPointXY(v.x() + rp * math.cos(amid), v.y() + rp * math.sin(amid))
    rot = _readable_angle_deg(-math.sin(amid), math.cos(amid))
    texts.append((tp, rot, _fmt_num(math.degrees(sweep), cfg, "°"), "angulo"))
    return lines, polys, texts


def build_radial(center, edge, cfg, da):
    """Cota radial (DIMRADIUS): centro + punto sobre la curva."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)
    dx, dy = edge.x() - center.x(), edge.y() - center.y()
    ux, uy = _unit(dx, dy)
    if ux == 0 and uy == 0:
        return lines, polys, texts

    lines.append((QgsGeometry.fromPolylineXY([center, edge]), "cota"))
    _add_arrowhead(edge, -ux, -uy, cfg, mark, lines, polys)

    # cruz en el centro
    h = mark * 0.55
    lines.append((QgsGeometry.fromPolylineXY(
        [QgsPointXY(center.x() - h, center.y()),
         QgsPointXY(center.x() + h, center.y())]), "tick"))
    lines.append((QgsGeometry.fromPolylineXY(
        [QgsPointXY(center.x(), center.y() - h),
         QgsPointXY(center.x(), center.y() + h)]), "tick"))

    val = _len_m(da, center, edge)
    nx, ny = -uy, ux
    tp = QgsPointXY((center.x() + edge.x()) / 2.0 + nx * ts * 0.9,
                    (center.y() + edge.y()) / 2.0 + ny * ts * 0.9)
    texts.append((tp, _readable_angle_deg(dx, dy),
                  "R = " + _fmt_num(val, cfg), "radio"))
    return lines, polys, texts


def build_diameter(p1, p2, cfg, da):
    """Cota diametral (DIMDIAMETER): dos puntos opuestos del círculo."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    ux, uy = _unit(dx, dy)
    if ux == 0 and uy == 0:
        return lines, polys, texts

    lines.append((QgsGeometry.fromPolylineXY([p1, p2]), "cota"))
    _add_arrowhead(p1, ux, uy, cfg, mark, lines, polys)
    _add_arrowhead(p2, -ux, -uy, cfg, mark, lines, polys)

    val = _len_m(da, p1, p2)
    nx, ny = -uy, ux
    tp = QgsPointXY((p1.x() + p2.x()) / 2.0 + nx * ts * 0.9,
                    (p1.y() + p2.y()) / 2.0 + ny * ts * 0.9)
    texts.append((tp, _readable_angle_deg(dx, dy),
                  "Ø = " + _fmt_num(val, cfg), "diametro"))
    return lines, polys, texts


def _circumcenter(p1, pm, p2):
    ax, ay = p1.x(), p1.y()
    bx, by = pm.x(), pm.y()
    cx, cy = p2.x(), p2.y()
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    sq_a = ax * ax + ay * ay
    sq_b = bx * bx + by * by
    sq_c = cx * cx + cy * cy
    ux = (sq_a * (by - cy) + sq_b * (cy - ay) + sq_c * (ay - by)) / d
    uy = (sq_a * (cx - bx) + sq_b * (ax - cx) + sq_c * (bx - ax)) / d
    return QgsPointXY(ux, uy)


def build_arc_length(p1, pm, p2, cfg, da):
    """Cota de longitud de arco (DIMARC): 3 puntos sobre el arco."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)

    c = _circumcenter(p1, pm, p2)
    if c is None:  # puntos colineales → cota alineada de respaldo
        val = _len_m(da, p1, p2)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        ux, uy = _unit(dx, dy)
        return build_aligned(p1, p2, (-uy, ux), cfg, _fmt_num(val, cfg))

    r = math.hypot(p1.x() - c.x(), p1.y() - c.y())
    a1 = math.atan2(p1.y() - c.y(), p1.x() - c.x()) % TWO_PI
    am = math.atan2(pm.y() - c.y(), pm.x() - c.x()) % TWO_PI
    a2 = math.atan2(p2.y() - c.y(), p2.x() - c.x()) % TWO_PI
    sweep = (a2 - a1) % TWO_PI
    if (am - a1) % TWO_PI > sweep:
        a1, a2 = a2, a1
        sweep = TWO_PI - sweep
    if sweep <= 1e-9 or r <= 0:
        return lines, polys, texts

    n = max(10, int(math.degrees(sweep) / 3.0))
    # arco real (para medir) y arco de cota desplazado hacia afuera
    real = [QgsPointXY(c.x() + r * math.cos(a1 + sweep * i / n),
                       c.y() + r * math.sin(a1 + sweep * i / n))
            for i in range(n + 1)]
    r2 = r + off
    dim = [QgsPointXY(c.x() + r2 * math.cos(a1 + sweep * i / n),
                      c.y() + r2 * math.sin(a1 + sweep * i / n))
           for i in range(n + 1)]
    lines.append((QgsGeometry.fromPolylineXY(dim), "cota"))

    if cfg.get("ext_lines", True):
        for ang in (a1, a1 + sweep):
            ux, uy = math.cos(ang), math.sin(ang)
            lines.append((QgsGeometry.fromPolylineXY(
                [QgsPointXY(c.x() + ux * (r + gap), c.y() + uy * (r + gap)),
                 QgsPointXY(c.x() + ux * (r2 + over),
                            c.y() + uy * (r2 + over))]),
                "extension"))

    t1x, t1y = -math.sin(a1), math.cos(a1)
    ae = a1 + sweep
    t2x, t2y = -math.sin(ae), math.cos(ae)
    _add_arrowhead(dim[0], t1x, t1y, cfg, mark, lines, polys)
    _add_arrowhead(dim[-1], -t2x, -t2y, cfg, mark, lines, polys)

    val = _polyline_len_m(da, real)
    amid = a1 + sweep / 2.0
    rp = r2 + ts * 0.9
    tp = QgsPointXY(c.x() + rp * math.cos(amid), c.y() + rp * math.sin(amid))
    rot = _readable_angle_deg(-math.sin(amid), math.cos(amid))
    texts.append((tp, rot, "⌒ " + _fmt_num(val, cfg), "arco"))
    return lines, polys, texts


def build_ordinate(pt, pos, cfg):
    """Cota de coordenadas (DIMORDINATE): punto + posición de la etiqueta."""
    lines, polys, texts = [], [], []
    off, ts, gap, over, mark = _sizes(cfg)

    land = ts * 1.8
    dirx = 1.0 if pos.x() >= pt.x() else -1.0
    elbow = QgsPointXY(pos.x() - dirx * land, pos.y())
    lines.append((QgsGeometry.fromPolylineXY([pt, elbow, pos]), "lider"))

    # marca en el punto
    h = mark * 0.4
    lines.append((QgsGeometry.fromPolylineXY(
        [QgsPointXY(pt.x() - h, pt.y() - h),
         QgsPointXY(pt.x() + h, pt.y() + h)]), "tick"))
    lines.append((QgsGeometry.fromPolylineXY(
        [QgsPointXY(pt.x() - h, pt.y() + h),
         QgsPointXY(pt.x() + h, pt.y() - h)]), "tick"))

    txt = "E = %s   N = %s" % (
        _fmt_num(pt.x(), cfg, ""),
        _fmt_num(pt.y(), cfg, ""))
    tp = QgsPointXY(pos.x(), pos.y() + ts * 0.85)
    texts.append((tp, 0.0, txt, "coordenada"))
    return lines, polys, texts


# ---------------------------------------------------------------------------
# Capas de salida y estilo
# ---------------------------------------------------------------------------

def _find_group():
    root = QgsProject.instance().layerTreeRoot()
    grp = root.findGroup(GROUP_NAME)
    if grp is None:
        grp = root.insertGroup(0, GROUP_NAME)
    return grp


def _find_layer(name):
    for lyr in QgsProject.instance().mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer):
            continue
        if lyr.name() == name and lyr.isValid():
            return lyr
    return None


def get_or_create_dim_layers(crs, prefix, cfg):
    """Devuelve (capa líneas, capa textos, capa flechas)."""
    authid = crs.authid() or QgsProject.instance().crs().authid()
    if not authid:
        authid = "EPSG:4326"
    names = ("%s · líneas de cota" % prefix,
             "%s · textos de cota" % prefix,
             "%s · flechas" % prefix)
    grp = _find_group()

    line_lyr = _find_layer(names[0])
    if line_lyr is None:
        line_lyr = QgsVectorLayer("LineString?crs=%s" % authid,
                                  names[0], "memory")
        line_lyr.dataProvider().addAttributes(
            [QgsField("tipo", QVariant.String)])
        line_lyr.updateFields()
        sym = QgsLineSymbol.createSimple({
            "line_color": cfg.get("color", "#111111"),
            "line_width": "0.35", "line_width_unit": "MM",
            "capstyle": "round"})
        line_lyr.setRenderer(QgsSingleSymbolRenderer(sym))
        QgsProject.instance().addMapLayer(line_lyr, False)
        grp.insertLayer(0, line_lyr)

    text_lyr = _find_layer(names[1])
    if text_lyr is None:
        text_lyr = QgsVectorLayer("Point?crs=%s" % authid, names[1], "memory")
        text_lyr.dataProvider().addAttributes([
            QgsField("texto", QVariant.String),
            QgsField("angulo", QVariant.Double),
            QgsField("tipo", QVariant.String)])
        text_lyr.updateFields()
        _style_text_layer(text_lyr, cfg)
        QgsProject.instance().addMapLayer(text_lyr, False)
        grp.insertLayer(0, text_lyr)

    poly_lyr = _find_layer(names[2])
    if poly_lyr is None:
        poly_lyr = QgsVectorLayer("Polygon?crs=%s" % authid,
                                  names[2], "memory")
        poly_lyr.dataProvider().addAttributes(
            [QgsField("tipo", QVariant.String)])
        poly_lyr.updateFields()
        sym = QgsFillSymbol.createSimple({
            "color": cfg.get("color", "#111111"),
            "outline_style": "no"})
        poly_lyr.setRenderer(QgsSingleSymbolRenderer(sym))
        QgsProject.instance().addMapLayer(poly_lyr, False)
        grp.insertLayer(0, poly_lyr)

    return line_lyr, text_lyr, poly_lyr


def _style_text_layer(layer, cfg):
    sym = QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "0.1", "size_unit": "MM",
        "color": "0,0,0,0", "outline_style": "no"})
    layer.setRenderer(QgsSingleSymbolRenderer(sym))

    settings = QgsPalLayerSettings()
    settings.fieldName = "texto"

    placement = compat_enum(
        "LabelPlacement", "OverPoint", QgsPalLayerSettings, "OverPoint")
    if placement is not None:
        try:
            settings.placement = placement
        except (TypeError, ValueError) as exc:
            _log("placement OverPoint no aplicado: %s" % exc)
    quadrant = compat_enum(
        "LabelQuadrantPosition", "Over", QgsPalLayerSettings, "QuadrantOver")
    if quadrant is not None:
        try:
            settings.quadOffset = quadrant
        except (TypeError, ValueError) as exc:
            _log("quadOffset Over no aplicado: %s" % exc)

    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial"))
    fmt.setSize(float(cfg["text_size"]))
    fmt.setSizeUnit(compat_enum(
        "RenderUnit", "MapUnits", QgsUnitTypes, "RenderMapUnits"))
    fmt.setColor(QColor(cfg.get("color", "#111111")))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.8)
    buf.setSizeUnit(compat_enum(
        "RenderUnit", "Millimeters", QgsUnitTypes, "RenderMillimeters"))
    buf.setColor(QColor(255, 255, 255, 220))
    fmt.setBuffer(buf)
    settings.setFormat(fmt)

    prop_holder = getattr(QgsPalLayerSettings, "Property", None)
    if prop_holder is not None and hasattr(prop_holder, "LabelRotation"):
        rot_key = prop_holder.LabelRotation
    else:
        rot_key = QgsPalLayerSettings.LabelRotation
    ddp = QgsPropertyCollection()
    ddp.setProperty(rot_key, QgsProperty.fromField("angulo"))
    settings.setDataDefinedProperties(ddp)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def commit(prefix, crs, cfg, lines, polys, texts):
    line_lyr, text_lyr, poly_lyr = get_or_create_dim_layers(crs, prefix, cfg)
    if lines:
        fs = []
        for g, tipo in lines:
            f = QgsFeature(line_lyr.fields())
            f.setGeometry(g)
            f["tipo"] = tipo
            fs.append(f)
        line_lyr.dataProvider().addFeatures(fs)
        line_lyr.updateExtents()
        line_lyr.triggerRepaint()
    if polys:
        fs = []
        for g, tipo in polys:
            f = QgsFeature(poly_lyr.fields())
            f.setGeometry(g)
            f["tipo"] = tipo
            fs.append(f)
        poly_lyr.dataProvider().addFeatures(fs)
        poly_lyr.updateExtents()
        poly_lyr.triggerRepaint()
    if texts:
        fs = []
        for pt, ang, txt, tipo in texts:
            f = QgsFeature(text_lyr.fields())
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f["texto"] = txt
            f["angulo"] = float(ang)
            f["tipo"] = tipo
            fs.append(f)
        text_lyr.dataProvider().addFeatures(fs)
        text_lyr.updateExtents()
        text_lyr.triggerRepaint()


# ---------------------------------------------------------------------------
# Acotado por lote (capa completa)
# ---------------------------------------------------------------------------

def _polygon_rings(geom):
    rings = []
    if geom.isMultipart():
        for poly in geom.asMultiPolygon():
            rings.extend(poly)
    else:
        rings.extend(geom.asPolygon())
    return rings


def _line_parts(geom):
    if geom.isMultipart():
        return geom.asMultiPolyline()
    pl = geom.asPolyline()
    return [pl] if pl else []


def acotar_capa(layer, cfg, iface=None):
    is_poly = layer.geometryType() == QgsWkbTypes.PolygonGeometry
    da = _distance_area_for(layer.crs())

    if cfg.get("solo_sel") and layer.selectedFeatureCount() > 0:
        feats = layer.selectedFeatures()
    else:
        feats = layer.getFeatures()

    L, P, T = [], [], []
    n = 0
    for f in feats:
        geom = QgsGeometry(f.geometry())
        if geom is None or geom.isEmpty():
            continue
        if hasattr(geom, "convertToStraightSegment"):
            geom.convertToStraightSegment()  # curvas → segmentos
        if is_poly:
            n += _acotar_poligono(geom, cfg, da, L, P, T)
        else:
            n += _acotar_linea(geom, cfg, da, L, P, T)

    commit("Cotas", layer.crs(), cfg, L, P, T)
    return n


def _acotar_poligono(geom, cfg, da, L, P, T):
    n = 0
    centroid = geom.centroid()
    c = centroid.asPoint() if centroid and not centroid.isEmpty() else None

    if cfg.get("lados"):
        for ring in _polygon_rings(geom):
            pts = list(ring)
            if len(pts) >= 2 and pts[0] == pts[-1]:
                pts = pts[:-1]
            m = len(pts)
            for i in range(m):
                n += _emit_segment(pts[i], pts[(i + 1) % m],
                                   cfg, da, L, P, T, c)

    if cfg.get("angulos"):
        for ring in _polygon_rings(geom):
            _acotar_angulos(ring, cfg, T)

    if cfg.get("area") or cfg.get("perimetro"):
        pos_g = geom.pointOnSurface()
        if pos_g and not pos_g.isEmpty():
            pos = pos_g.asPoint()
            ts = float(cfg["text_size"])
            if cfg.get("area"):
                a = _area_m2(da, geom)
                T.append((QgsPointXY(pos), 0.0,
                          "A = " + _fmt_num(a, cfg, " m²"), "area"))
            if cfg.get("perimetro"):
                per = 0.0
                for ring in _polygon_rings(geom):
                    for i in range(len(ring) - 1):
                        per += _len_m(da, ring[i], ring[i + 1])
                dy = -ts * 1.6 if cfg.get("area") else 0.0
                T.append((QgsPointXY(pos.x(), pos.y() + dy), 0.0,
                          "P = " + _fmt_num(per, cfg), "perimetro"))
    return n


def _acotar_linea(geom, cfg, da, L, P, T):
    n = 0
    for part in _line_parts(geom):
        if len(part) < 2:
            continue
        if cfg.get("lados"):
            for i in range(len(part) - 1):
                n += _emit_segment(part[i], part[i + 1],
                                   cfg, da, L, P, T, None)
        if cfg.get("perimetro"):
            total = sum(_len_m(da, part[i], part[i + 1])
                        for i in range(len(part) - 1))
            pos = part[len(part) // 2]
            T.append((QgsPointXY(pos.x(), pos.y()), 0.0,
                      "L = " + _fmt_num(total, cfg), "longitud"))
    return n


def _emit_segment(p1, p2, cfg, da, L, P, T, away_from):
    length_m = _len_m(da, p1, p2)
    if length_m < float(cfg.get("min_len", 0)):
        return 0
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    ux, uy = _unit(dx, dy)
    if ux == 0 and uy == 0:
        return 0
    nx, ny = -uy, ux
    if away_from is not None:
        mx, my = (p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0
        d_pos = (mx + nx - away_from.x()) ** 2 + (my + ny - away_from.y()) ** 2
        d_neg = (mx - nx - away_from.x()) ** 2 + (my - ny - away_from.y()) ** 2
        if d_neg > d_pos:
            nx, ny = -nx, -ny
    l, p, t = build_aligned(p1, p2, (nx, ny), cfg, _fmt_num(length_m, cfg))
    L.extend(l)
    P.extend(p)
    T.extend(t)
    return 1


def _acotar_angulos(ring, cfg, T):
    pts = list(ring)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    m = len(pts)
    if m < 3:
        return
    s = 0.0
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        s += a.x() * b.y() - b.x() * a.y()
    ccw = s > 0
    off = float(cfg["offset"]) * 0.8
    for i in range(m):
        v = pts[i]
        prev = pts[(i - 1) % m]
        nxt = pts[(i + 1) % m]
        ax, ay = _unit(prev.x() - v.x(), prev.y() - v.y())
        bx, by = _unit(nxt.x() - v.x(), nxt.y() - v.y())
        if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
            continue
        dot = max(-1.0, min(1.0, ax * bx + ay * by))
        base = math.degrees(math.acos(dot))
        e1x, e1y = v.x() - prev.x(), v.y() - prev.y()
        e2x, e2y = nxt.x() - v.x(), nxt.y() - v.y()
        crossz = e1x * e2y - e1y * e2x
        convex = (crossz > 0) == ccw
        interior = base if convex else 360.0 - base
        bx2, by2 = _unit(ax + bx, ay + by)
        if bx2 == 0 and by2 == 0:
            bx2, by2 = -ay, ax
        sgn = 1.0 if convex else -1.0
        pos = QgsPointXY(v.x() + bx2 * off * sgn, v.y() + by2 * off * sgn)
        T.append((pos, 0.0, "%.1f°" % interior, "angulo"))
