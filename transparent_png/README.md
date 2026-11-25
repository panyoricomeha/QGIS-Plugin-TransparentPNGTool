# Transparent PNG Tool 1.3.1

Install the ZIP in QGIS 3.x. Open Raster > Transparent PNG Tool.

Choose one input method:
- Relative-path TXT list: specify the TXT file and source root folder.
- Select PNG files directly: add one or more PNG files, including multiple batches; remove unwanted entries. The source root is optional and defaults to the common parent of the selected files. Specify a root explicitly to retain more of the folder structure. Files on different drives need separate runs.

Select a separate existing output folder and click Create fully transparent PNGs. Source and output roots must not overlap. Source files are never overwritten; existing outputs are skipped. Original filenames, dimensions and subfolders are preserved. Existing georeference sidecars are copied when possible; no GDAL-based georeference extraction is performed. English is default; Japanese UI uses i18n/ja.json. QGIS GUI testing has not been performed.
