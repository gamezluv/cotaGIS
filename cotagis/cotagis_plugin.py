# -*- coding: utf-8 -*-
"""
cotagis_plugin.py - Clase principal del plugin CotaGIS.
Licencia: GNU GPL v3 o posterior.
"""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QActionGroup, QMenu, QMessageBox, QDialog, QToolButton,
)
from qgis.core import QgsSettings

from . import dim_engine
from .dim_engine import DEFAULT_CFG
from .batch_dialog import BatchDialog
from .settings_dialog import SettingsDialog
from .map_tool import DimensionTool, DIM_MODES

PLUGIN_DIR = os.path.dirname(__file__)
MENU = "&CotaGIS"
SETTINGS_PREFIX = "cotagis/"


def _load_cfg():
    s = QgsSettings()
    cfg = dict(DEFAULT_CFG)
    for k, default in DEFAULT_CFG.items():
        raw = s.value(SETTINGS_PREFIX + k, None)
        if raw is None:
            continue
        try:
            if isinstance(default, bool):
                cfg[k] = str(raw).lower() in ("true", "1", "yes")
            elif isinstance(default, int) and not isinstance(default, bool):
                cfg[k] = int(float(raw))
            elif isinstance(default, float):
                cfg[k] = float(raw)
            else:
                cfg[k] = str(raw)
        except (TypeError, ValueError):
            continue  # valor corrupto: se mantiene el predeterminado
    # compatibilidad con v1.0 ("estilo" → "arrow")
    old = s.value(SETTINGS_PREFIX + "estilo", None)
    if old and s.value(SETTINGS_PREFIX + "arrow", None) is None:
        cfg["arrow"] = str(old)
    return cfg


def _save_cfg(cfg):
    s = QgsSettings()
    for k in DEFAULT_CFG:
        s.setValue(SETTINGS_PREFIX + k, cfg.get(k))


class CotaGisPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.cfg = _load_cfg()
        self.actions = []
        self.toolbar = None
        self.dim_tool = None
        self.mode_group = None
        self.dim_button = None

    # ------------------------------------------------------------------
    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icon.png"))
        icon_cfg = QIcon(os.path.join(PLUGIN_DIR, "icon_settings.png"))
        self.toolbar = self.iface.addToolBar("CotaGIS")
        self.toolbar.setObjectName("CotaGisToolbar")

        # --- Acotar capa (lote) ---
        self.act_capa = QAction(icon, "Acotar capa…", self.iface.mainWindow())
        self.act_capa.setToolTip(
            "Acota todos los lados, áreas, perímetros y ángulos de una capa "
            "de líneas o polígonos")
        self.act_capa.triggered.connect(self.run_dialog)
        self.toolbar.addAction(self.act_capa)

        # --- Menú de tipos de cota (herramienta interactiva con OSNAP) ---
        self.dim_menu = QMenu(self.iface.mainWindow())
        self.mode_group = QActionGroup(self.iface.mainWindow())
        self.mode_group.setExclusive(True)
        self.mode_actions = {}
        for mode, label, _clicks in DIM_MODES:
            a = QAction(icon, label, self.iface.mainWindow())
            a.setCheckable(True)
            a.setData(mode)
            a.triggered.connect(
                lambda checked, mm=mode: self.activate_mode(mm, checked))
            self.mode_group.addAction(a)
            self.dim_menu.addAction(a)
            self.mode_actions[mode] = a
            self.iface.addPluginToVectorMenu(MENU, a)
            self.actions.append(a)

        self.dim_button = QToolButton()
        self.dim_button.setMenu(self.dim_menu)
        self.dim_button.setDefaultAction(self.mode_actions["alineada"])
        self.dim_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.dim_button.setToolTip(
            "Tipos de cota (con Object Snap): lineal, alineada, continua, "
            "línea base, angular, radial, diametral, arco y coordenadas")
        self.toolbar.addWidget(self.dim_button)

        # --- Configuración ---
        self.act_cfg = QAction(icon_cfg, "Configuración…",
                               self.iface.mainWindow())
        self.act_cfg.setToolTip(
            "Object Snap, líneas de extensión, arrowheads y formato")
        self.act_cfg.triggered.connect(self.run_settings)
        self.toolbar.addAction(self.act_cfg)

        # --- Menú vectorial ---
        self.act_about = QAction(icon, "Acerca de…", self.iface.mainWindow())
        self.act_about.triggered.connect(self.show_about)
        for a in (self.act_capa, self.act_cfg, self.act_about):
            self.iface.addPluginToVectorMenu(MENU, a)
            self.actions.append(a)

    def unload(self):
        if self.dim_tool is not None:
            self.iface.mapCanvas().unsetMapTool(self.dim_tool)
            self.dim_tool = None
        for a in self.actions:
            self.iface.removePluginVectorMenu(MENU, a)
        self.actions = []
        if self.toolbar is not None:
            del self.toolbar
            self.toolbar = None

    # ------------------------------------------------------------------
    def _ensure_tool(self):
        if self.dim_tool is None:
            self.dim_tool = DimensionTool(self.iface.mapCanvas(), self)
            self.dim_tool.deactivated.connect(self._tool_deactivated)
        return self.dim_tool

    def _tool_deactivated(self):
        a = self.mode_group.checkedAction()
        if a:
            a.setChecked(False)

    def activate_mode(self, mode, checked=True):
        tool = self._ensure_tool()
        if not checked:
            self.iface.mapCanvas().unsetMapTool(tool)
            return
        self.dim_button.setDefaultAction(self.mode_actions[mode])
        tool.set_mode(mode)
        tool.apply_snap_config()
        self.iface.mapCanvas().setMapTool(tool)

    # ------------------------------------------------------------------
    def run_dialog(self):
        dlg = BatchDialog(self.cfg, self.iface.mainWindow())
        if dlg.exec_() != QDialog.Accepted:
            return
        layer = dlg.layer()
        if layer is None:
            self.iface.messageBar().pushWarning(
                "CotaGIS", "No hay ninguna capa de líneas o polígonos.")
            return
        self.cfg.update(dlg.config())
        _save_cfg(self.cfg)

        if layer.crs().isGeographic():
            self.iface.messageBar().pushWarning(
                "CotaGIS",
                "La capa está en coordenadas geográficas: las separaciones "
                "se medirán en grados. Se recomienda un CRS proyectado "
                "(p. ej. EPSG:32718 para Lima).")

        n = dim_engine.acotar_capa(layer, self.cfg, self.iface)
        self.iface.messageBar().pushSuccess(
            "CotaGIS",
            "Se generaron %d cotas para la capa «%s»." % (n, layer.name()))
        self.iface.mapCanvas().refreshAllLayers()

    def run_settings(self):
        dlg = SettingsDialog(self.cfg, self.iface.mainWindow())
        if dlg.exec_() != QDialog.Accepted:
            return
        self.cfg.update(dlg.config())
        _save_cfg(self.cfg)
        if self.dim_tool is not None:
            self.dim_tool.apply_snap_config()
        self.iface.messageBar().pushInfo(
            "CotaGIS", "Configuración guardada.")

    def show_about(self):
        QMessageBox.about(
            self.iface.mainWindow(), "CotaGIS",
            "<b>CotaGIS</b><br>"
            "Cotas al estilo AutoCAD para QGIS: lineal, alineada, continua, "
            "línea base, angular, radial, diametral, longitud de arco y "
            "coordenadas, con Object Snap (vértices, extremos, puntos "
            "medios, intersecciones…), acotado por lote de capas completas "
            "y estilos configurables de extensión y flechas.<br><br>"
            "Las cotas se generan como capas de memoria en el grupo "
            "«Cotas (CotaGIS)»; expórtalas a GeoPackage o Shapefile "
            "para conservarlas.<br><br>Licencia: GNU GPL v3+")
