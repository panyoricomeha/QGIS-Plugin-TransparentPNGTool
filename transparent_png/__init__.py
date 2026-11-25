# -*- coding: utf-8 -*-
"""Entry point for the QGIS plugin."""


def classFactory(iface):
    from .plugin import TransparentPngPlugin
    return TransparentPngPlugin(iface)
