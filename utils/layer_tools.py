
import os
import tempfile
import uuid
from qgis.core import QgsVectorFileWriter

def get_layer_path_or_temp(layer):
    """
    入力レイヤがファイルベースならそのパスを返す。
    そうでなければ一時GPKGに書き出してそのパスを返す。
    戻り値:
        (パス: str, 一時ファイルフラグ: bool)
    """
    if layer.storageType().lower() in ["esri shapefile", "gpkg", "geojson", "geopackage"]:
        return layer.source(), False
    else:
        temp_path = os.path.join(tempfile.gettempdir(), f"input_polygons_{uuid.uuid4().hex}.gpkg")
        QgsVectorFileWriter.writeAsVectorFormat(layer, temp_path, "utf-8", layer.crs(), "GPKG")
        return temp_path, True