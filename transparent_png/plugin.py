# -*- coding: utf-8 -*-
"""Minimal transparent PNG exporter for TXT lists or selected PNG files."""
from pathlib import Path

from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QProgressDialog, QPushButton,
    QVBoxLayout, QWidget,
)

from .translator import load, tr
from .pngtools import (
    CancelledError, make_transparent_png, prepare_pairs,
    preserve_georeference, read_relative_png_list, read_selected_pngs,
)


class TransparentPngPlugin:
    def __init__(self, iface):
        load()
        self.iface = iface
        self.menu = tr('Transparent PNG Tool')
        self.action = None

    def initGui(self):
        self.action = QAction(
            QIcon(':/images/themes/default/mIconRaster.svg'),
            self.menu, self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToRasterMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginRasterMenu(self.menu, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def run(self):
        dialog = TransparentPngDialog(self.iface.mainWindow())
        execute = getattr(dialog, 'exec', None) or dialog.exec_
        execute()


class TransparentPngDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Transparent PNG Tool'))
        self.resize(620, 270)
        main = QVBoxLayout(self)
        note = QLabel(tr('Create fully transparent PNGs from a TXT list or selected PNG files. Original images are not modified.'))
        note.setWordWrap(True)
        main.addWidget(note)
        form = QFormLayout()
        self.mode = QComboBox(self)
        self.mode.addItems([tr('Relative-path TXT list'), tr('Select PNG files directly')])
        form.addRow(tr('Input method'), self.mode)
        self.txt = self._path_row(form, 'TXT file', self._choose_txt)
        self.txt_row = self.txt.parentWidget()
        self.txt_label = form.labelForField(self.txt_row)
        self.txt_example = QLabel(tr('TXT format: one relative PNG path per line. Example:') + '\n12/3627/1620.png\n12/3627/1621.png', self)
        self.txt_example.setWordWrap(True)
        form.addRow('', self.txt_example)
        self.file_panel = QWidget(self)
        file_layout = QVBoxLayout(self.file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.files = QListWidget(self.file_panel)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setMinimumHeight(100)
        file_layout.addWidget(self.files)
        file_buttons = QHBoxLayout()
        add = QPushButton(tr('Add PNG files…'))
        add.clicked.connect(self._add_pngs)
        remove = QPushButton(tr('Remove selected'))
        remove.clicked.connect(self._remove_pngs)
        file_buttons.addWidget(add)
        file_buttons.addWidget(remove)
        file_layout.addLayout(file_buttons)
        form.addRow(tr('PNG files'), self.file_panel)
        self.files_label = form.labelForField(self.file_panel)
        self.source = self._path_row(form, 'Source root folder', self._choose_folder)
        self.output = self._path_row(form, 'Output folder', self._choose_folder)
        main.addLayout(form)
        note = QLabel(tr('Original filenames and folder structure are preserved. Existing output files are skipped.'))
        note.setWordWrap(True)
        main.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.run_button = QPushButton(tr('Create fully transparent PNGs'))
        self.run_button.clicked.connect(self._export)
        self.run_button.setDefault(True)
        buttons.addWidget(self.run_button)
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        main.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self._update_mode()

    def _update_mode(self, *_args):
        direct = self.mode.currentIndex() == 1
        self.txt_row.setVisible(not direct)
        self.txt_label.setVisible(not direct)
        self.txt_example.setVisible(not direct)
        self.file_panel.setVisible(direct)
        self.files_label.setVisible(direct)
        self.source.setPlaceholderText(tr('Optional: infer from selected files') if direct else '')
        self.adjustSize()

    def _add_pngs(self):
        existing = {self.files.item(i).text() for i in range(self.files.count())}
        start = str(Path(self.files.item(self.files.count() - 1).text()).parent) if self.files.count() else self.source.text()
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Select PNG files'), start, tr('PNG files (*.png *.PNG)'))
        for path in paths:
            value = str(Path(path))
            if value not in existing:
                self.files.addItem(value)
                existing.add(value)

    def _remove_pngs(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))

    def _path_row(self, form, label, chooser):
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        button = QPushButton(tr('Browse'), row)
        button.clicked.connect(lambda: chooser(edit))
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        form.addRow(tr(label), row)
        return edit

    def _choose_txt(self, edit):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Select TXT file'), edit.text(), tr('Text files (*.txt);;All files (*)'))
        if path:
            edit.setText(path)

    def _choose_folder(self, edit):
        path = QFileDialog.getExistingDirectory(self, tr('Select folder'), edit.text())
        if path:
            edit.setText(path)

    def _export(self):
        txt, source, output = (edit.text().strip() for edit in (self.txt, self.source, self.output))
        direct = self.mode.currentIndex() == 1
        if not output or (direct and not self.files.count()):
            QMessageBox.warning(self, tr('Check settings'), tr('Select PNG files and an output folder.') if direct else tr('Specify the TXT file, source root and output folder.'))
            return
        if not direct and not (txt and source):
            QMessageBox.warning(self, tr('Check settings'), tr('Specify the TXT file, source root and output folder.'))
            return
        try:
            if direct:
                paths = [self.files.item(i).text() for i in range(self.files.count())]
                result = read_selected_pngs(paths, source)
            else:
                result = read_relative_png_list(txt, source)
            pairs = prepare_pairs(result['paths'], result['source_root'], output)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr('Check settings'), str(exc))
            return
        counts = tr('Found: {}\nMissing: {}\nInvalid: {}\nDuplicates: {}').format(
            len(pairs), len(result['missing']), len(result['invalid']), len(result['duplicates']))
        if not pairs:
            QMessageBox.warning(self, tr('No PNG files found'), counts)
            return
        if QMessageBox.question(self, tr('Confirm processing'),
                                counts + '\n\n' + tr('Create transparent PNGs for the found files?'),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.run_button.setEnabled(False)
        progress = QProgressDialog(tr('Processing PNG files…'), tr('Cancel'), 0, len(pairs), self)
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        created = skipped = 0
        errors = []
        cancelled = False
        try:
            for index, (src, dst) in enumerate(pairs):
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break
                progress.setLabelText('{} / {}: {}'.format(index + 1, len(pairs), src.name))
                try:
                    if dst.exists() or dst.is_symlink():
                        skipped += 1
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        def update(_row, _total):
                            QApplication.processEvents()
                            return not progress.wasCanceled()
                        make_transparent_png(src, dst, progress=update)
                        created += 1
                        preserve_georeference(src, dst)
                except CancelledError:
                    cancelled = True
                    break
                except FileExistsError:
                    skipped += 1
                except Exception as exc:
                    errors.append('{}: {}'.format(src, exc))
                progress.setValue(index + 1)
        finally:
            progress.close()
            self.run_button.setEnabled(True)
        summary = tr('Created: {}\nSkipped (already exists): {}\nErrors/warnings: {}').format(created, skipped, len(errors))
        summary += '\n\n' + counts
        if cancelled:
            summary += tr('\nCancelled. Files already created will remain.')
        if errors:
            summary += '\n\n' + '\n'.join(errors[:8])
            if len(errors) > 8:
                summary += tr('\n{} more').format(len(errors) - 8)
        (QMessageBox.warning if errors else QMessageBox.information)(self, tr('Processing results'), summary)
