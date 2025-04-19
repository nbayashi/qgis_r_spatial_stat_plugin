import os
import subprocess
import tempfile
from qgis.core import (QgsProcessingAlgorithm, QgsProcessingParameterNumber,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingContext, QgsProcessingOutputVectorLayer,
                       QgsProcessingException, QgsSettings)

class RunRScriptAlgorithm(QgsProcessingAlgorithm):
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer("INPUT", "Input Layer"))
        self.addParameter(QgsProcessingParameterNumber("DIST", "Buffer Distance", defaultValue=100))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Buffered Output"))

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback):
        input_layer = self.parameterAsVectorLayer(parameters, "INPUT", context)
        distance = self.parameterAsDouble(parameters, "DIST", context)
        output_path = os.path.join(tempfile.gettempdir(), "buffered.gpkg")

        # エクスポート: 入力を一時GPKGに保存
        input_path = os.path.join(tempfile.gettempdir(), "input.gpkg")
        _ = QgsVectorFileWriter.writeAsVectorFormat(input_layer, input_path, "utf-8", input_layer.crs(), "GPKG")

        # Rscript パス取得
        rscript_path = QgsSettings().value("RRunner/RscriptPath", "")
        if not rscript_path or not os.path.exists(rscript_path):
            raise QgsProcessingException("Rscriptのパスが設定されていない、または存在しません。")

        # Rコード生成
        r_code = f"""
library(sf)
data <- st_read("{input_path}")
buffered <- st_buffer(data, dist = {distance})
st_write(buffered, "{output_path}", delete_layer = TRUE)
"""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".R") as f:
            f.write(r_code.encode("utf-8"))
            r_script_path = f.name

        result = subprocess.run([rscript_path, r_script_path], capture_output=True, text=True)
        if result.returncode != 0:
            raise QgsProcessingException(f"R script error: {result.stderr}")

        # 結果レイヤとして読み込み
        sink_id = self.parameterAsSink(parameters, "OUTPUT", context, input_layer.fields(), input_layer.wkbType(), input_layer.sourceCrs())[1]
        buffered_layer = QgsVectorLayer(output_path, "Buffered", "ogr")
        QgsProject.instance().addMapLayer(buffered_layer)
        return {"OUTPUT": sink_id}

    def name(self):
        return "run_r_buffer"

    def displayName(self):
        return "Run R Buffer"

    def group(self):
        return "R Runner"

    def groupId(self):
        return "r_runner"

    def createInstance(self):
        return RunRScriptAlgorithm()