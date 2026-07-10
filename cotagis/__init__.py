# -*- coding: utf-8 -*-
"""
CotaGIS - Plugin de QGIS para acotar (dimensionar) líneas y polígonos
al estilo de los comandos DIM de AutoCAD.

Licencia: GNU GPL v3 o posterior.
"""


def classFactory(iface):
    """Punto de entrada estándar de QGIS."""
    from .cotagis_plugin import CotaGisPlugin
    return CotaGisPlugin(iface)
