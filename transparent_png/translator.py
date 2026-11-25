"""Load optional JSON translations; English is the default language."""
import json
import os
import logging

_catalog = {}


def load(locale=None):
    """Use the QGIS UI locale, or an explicit locale for standalone tests."""
    global _catalog
    _catalog = {}
    if locale is None:
        from qgis.PyQt.QtCore import QLocale
        from qgis.core import QgsSettings
        settings = QgsSettings()
        if settings.value('locale/overrideFlag', False, type=bool):
            locale = settings.value('locale/userLocale', '', type=str)
        else:
            locale = QLocale.system().name()
    language = str(locale or '').replace('-', '_').split('_')[0].lower()
    if language != 'ja':
        return
    path = os.path.join(os.path.dirname(__file__), 'i18n', 'ja.json')
    try:
        with open(path, encoding='utf-8') as stream:
            catalog = json.load(stream)
        if isinstance(catalog, dict):
            _catalog = {key: value for key, value in catalog.items()
                        if isinstance(key, str) and isinstance(value, str)}
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning('Could not load Japanese translations: %s', exc)


def tr(message):
    """Translate a source string, falling back to English if unavailable."""
    return _catalog.get(message, message)
