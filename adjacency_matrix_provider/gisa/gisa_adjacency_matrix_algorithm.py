# -*- coding: utf-8 -*-

"""
/***************************************************************************
R SpatialStatistics
                              -------------------
        begin                : 2025-04-13
        copyright            : (C) 2025 by nbayashi
        email                : naoya_nstyle@hotmail.co.jp
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = 'nbayashi'
__date__ = '2025-04-13'
__copyright__ = '(C) 2025 by nbayashi'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'
import subprocess
import os
import uuid

import tempfile

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsSettings,
                       QgsProcessing,
                       QgsProcessingException,
                       QgsVectorFileWriter,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterFileDestination)


from qgis.PyQt.QtGui import QIcon
from ...utils.layer_tools import get_layer_path_or_temp


class GISAAdjacencyMatrixAlgorithm(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    FIELD = 'FIELD'
    INPUT = 'INPUT'
    STATISTICS_TYPE = 'STATISTICS_TYPE'
    NEIGHBOR_TYPE = 'NEIGHBOR_TYPE'
    USE_DISTANCE_DECAY = 'USE_DISTANCE_DECAY'
    OUTPUT = 'OUTPUT_'



    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        # We add the input vector features source. It can have any kind of
        # geometry.
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr('Input layer'),
                [QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        # 属性の設定
        self.addParameter(
                    QgsProcessingParameterField(
                        self.FIELD,
                        self.tr('Field'),
                                        # 親レイヤのパラメータの名称を指定
                        parentLayerParameterName= self.INPUT,
                        optional=False
                    )
                )
        
        self.addParameter(
            QgsProcessingParameterEnum(
                name=self.STATISTICS_TYPE,
                description='Statistics type',
                options=['Global Moran\'s I', 'Global Geary\'s C','Global Getis-Ord G','Global Getis-Ord G*'],
                defaultValue=0
            )
        )
        # select queen or rook
        self.addParameter(
            QgsProcessingParameterEnum(
                name='NEIGHBOR_TYPE',
                description='Queen or Rook',
                options=['Queen', 'Rook'],
                defaultValue=0
            )
        )


        self.addParameter(
            QgsProcessingParameterBoolean(
                name=self.USE_DISTANCE_DECAY,
                description='Use distance-decay weights (1/d)',
                defaultValue=False
            )
        )


        
        # txt
        self.addParameter(
            QgsProcessingParameterFileDestination(
                name=self.OUTPUT,
                description='Export result txt',
                fileFilter='TXT (*.txt)',
                optional=True,  # ← スキップ可
                createByDefault=False # ← デフォルトで作成しない
            )
        )

    def get_layer_path_or_temp(self, layer):
        # ファイルベースなら直接返す
        if layer.storageType().lower() in ["esri shapefile", "gpkg", "geojson", "geopackage"]:
            return layer.source(), False
        else:
            # それ以外なら一時GPKGにエクスポート
            temp_path = os.path.join(tempfile.gettempdir(), f"input_polygons_{uuid.uuid4().hex}.gpkg")
            QgsVectorFileWriter.writeAsVectorFormat(layer, temp_path, "utf-8", layer.crs(), "GPKG")
            return temp_path, True
       
       
    def processAlgorithm(self, parameters, context, feedback):
        rscript_path = QgsSettings().value("RRunner/RscriptPath", "")
        # Check if the Rscript path is set
        if not os.path.exists(rscript_path):
            raise QgsProcessingException("Rscriptのパスが無効です")
        

        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        # フィールド名を取得
        field_name = self.parameterAsString(parameters, self.FIELD, context)

        output = self.parameterAsFile(parameters, self.OUTPUT, context)

        

        queen = self.parameterAsEnum(parameters, 'NEIGHBOR_TYPE', context) == 0  # True if Queen
        nb_queen = str(queen).upper()  # R側に渡す用
        if queen:
            nb_type = "Queen"
        else:
            nb_type = "Rook"

        use_distance_decay = self.parameterAsBool(parameters, 'USE_DISTANCE_DECAY', context)
        r_use_decay = "TRUE" if use_distance_decay else "FALSE"


        # 共通: 座標（重心）
        r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
        r_nb_code += f'nb <- poly2nb(as(polygons, "Spatial"), queen = {nb_queen})\n'
        
        r_statistic__index = self.parameterAsEnum(parameters, self.STATISTICS_TYPE, context)
        r_statistic_type = ['Moran\'s I', 'Geary\'s C', 'Getis-Ord G', 'Getis-Ord G*'][r_statistic__index]
        

        # 入力レイヤを一時GPKGとして保存
        input_path, is_temp = get_layer_path_or_temp(input_layer)
        input_layer_path = input_path.replace("\\", "/")
       

        # Rコードを生成
        r_code = f"""
        # パッケージ確認＆読み込み
        packages <- c("sf", "spdep", "dplyr", "classInt")
        for (pkg in packages) {{
            if (!requireNamespace(pkg, quietly = TRUE)) {{
                install.packages(pkg, repos = "https://cloud.r-project.org")
            }}
            library(pkg, character.only = TRUE)
        }}

        # 入力読み込み
        polygons <- st_read("{input_path}")
        id_field <- "{field_name}"
        
        # 地理座標系なら EPSG:3857 に変換（単位：メートル）
        if (grepl("longlat", st_crs(polygons)$proj4string)) {{
            message("入力データが地理座標系です。EPSG:3857 に投影変換します。")
            polygons <- st_transform(polygons, 3857)
        }}

        # 近接構築
        {r_nb_code}


        # nb2listw に zero.policy=TRUE をつけた場合、listw$neighbours の長さは nb に合わせて出る
        # その代わり、重み・隣接が 0 のポリゴンも明示的に扱う必要あり
        # 行基準化ウェイト行列
        # 距離減衰を使うかどうか（Pythonから渡されたフラグ）
        statistic_type <- "{r_statistic_type}"  # Pythonから渡す文字列

        # 距離減衰ありの場合
        if ({r_use_decay}) {{
            centroids <- st_centroid(polygons)
            glist <- nbdists(nb, centroids)
            glist <- lapply(glist, function(x) 1/x)

            if (statistic_type == "Getis-Ord G*") {{
                nb_self <- include.self(nb)
                listw <- nb2listw(nb_self, glist=glist, style="W", zero.policy=TRUE)
            }} else {{
                listw <- nb2listw(nb, glist=glist, style="W", zero.policy=TRUE)
            }}
        }} else {{
            # 距離減衰なしの場合
            if (statistic_type == "Getis-Ord G") {{
                listw <- nb2listw(nb, style="B", zero.policy=TRUE)
            }} else if (statistic_type == "Getis-Ord G*") {{
                nb_self <- include.self(nb)
                listw <- nb2listw(nb_self, style="B", zero.policy=TRUE)
            }} else {{
                listw <- nb2listw(nb, style="W", zero.policy=TRUE)
            }}
        }}



        result_txt <- c(
        "Input layer: {input_layer_path}\\n",
        "Field: {field_name}",
        "Neighbor type: Adjacency matrix  ({nb_type})"
        )


        if (statistic_type == "Moran's I") {{
            test <- moran.test(polygons[[id_field]], listw)
            test_result<- capture.output(test)
        }} else if (statistic_type == "Geary's C") {{
            test <- geary.test(polygons[[id_field]], listw)
            test_result <- capture.output(test)
        }} else if (statistic_type == "Getis-Ord G" || statistic_type == "Getis-Ord G*") {{
            test <- globalG.test(polygons[[id_field]], listw)
            test_result <- capture.output(test)
        }} 

        # 結果を出力
        # ヘッダーに結果を追加
        result_txt <- c(result_txt, "", test_result)

        cat(result_txt, sep="\n")

        # 書き出し
        if ("{output}" != "") {{
            writeLines(result_txt, "{output}")
            }}
        """
                
                
        # Rスクリプトを一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=".R") as f:
            f.write(r_code.encode("utf-8"))
            r_script_file = f.name

        # Rスクリプトを実行
        result = subprocess.run([rscript_path, r_script_file], capture_output=True, text=True)
        if result.returncode != 0 or 'Error' in result.stderr:
            raise QgsProcessingException(f"R実行中にエラー:\n{result.stderr}\n{result.stdout}")

        feedback.pushInfo("=== GISA Statistics Result ===\n" + result.stdout)
        feedback.pushInfo("=============================")

        os.remove(r_script_file)
        if is_temp and os.path.exists(input_path):
            os.remove(input_path)
        
        return {}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'gisaadjacencymatrix'
    
    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon_adjacency_matrix.png'))

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('GISA(Adjacency matrix)')

    def group(self):
        return self.tr('Global Indicator of Spatial Association')

    def groupId(self):
        return 'rgisa'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GISAAdjacencyMatrixAlgorithm()
