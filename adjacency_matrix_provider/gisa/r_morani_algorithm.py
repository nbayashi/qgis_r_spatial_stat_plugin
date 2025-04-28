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

import tempfile

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsSettings,
                       QgsProcessing,
                       QgsProcessingException,
                       QgsVectorLayer,
                       QgsVectorFileWriter,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFileDestination)


from qgis.PyQt.QtGui import QIcon

class MoranIAlgorithm(QgsProcessingAlgorithm):
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
    NB_METHOD_TYPE = 'NB_METHOD_TYPE'
    NEIGHBOR_TYPE = 'NEIGHBOR_TYPE'
    D_MIN = 'D_MIN'
    D_MAX = 'D_MAX'
    K_NUM = 'K'



    USE_DISTANCE_DECAY = 'USE_DISTANCE_DECAY'


    OUTPUT = 'OUTPUT'



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

        # 近接行列のタイプを選ぶ
        self.addParameter(
            QgsProcessingParameterEnum(
                name=self.NB_METHOD_TYPE,
                description='Neighborhood construction method',
                options=['Polygon contiguity (poly2nb)', 'Distance-based (dnearneigh)', 'K-nearest neighbors (knearneigh)'],
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

        # dnearneigh → 距離設定
        self.addParameter(
            QgsProcessingParameterNumber(
                name=self.D_MIN,
                description='Minimum distance (m)',
                defaultValue=0
                )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                name=self.D_MAX,
                description='Maximum distance (m)',
                defaultValue=5000
            )
        )


        # knearneigh → 近接数設定
        self.addParameter(
            QgsProcessingParameterNumber(
                self.K_NUM,
                'Number of nearest neighbors (for knearneigh)',
                defaultValue=4,
                minValue=1
                )
        )



        self.addParameter(
            QgsProcessingParameterBoolean(
                name=self.USE_DISTANCE_DECAY,
                description='Use distance-decay weights (1/d)',
                defaultValue=False
            )
        )


        # html
        self.addParameter(
            QgsProcessingParameterFileDestination(
                name=self.OUTPUT,
                description='Export result html',
                fileFilter='HTML (*.html)',
                optional=True,  # ← スキップ可
                createByDefault=False # ← デフォルトで作成しない
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        rscript_path = QgsSettings().value("RRunner/RscriptPath", "")
        # Check if the Rscript path is set
        if not os.path.exists(rscript_path):
            raise QgsProcessingException("Rscriptのパスが無効です")
        

        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        # フィールド名を取得
        field_name = self.parameterAsString(parameters, self.FIELD, context)

        

        queen = self.parameterAsEnum(parameters, 'NEIGHBOR_TYPE', context) == 0  # True if Queen
        nb_queen = str(queen).upper()  # R側に渡す用



        d_minimum = self.parameterAsDouble(parameters, self.D_MIN, context)
        d_maximum = self.parameterAsDouble(parameters, self.D_MAX, context)
        k_number = self.parameterAsInt(parameters, self.K_NUM, context)
        
        output = self.parameterAsFile(parameters, self.OUTPUT, context)

        


        use_distance_decay = self.parameterAsBool(parameters, 'USE_DISTANCE_DECAY', context)
        r_use_decay = "TRUE" if use_distance_decay else "FALSE"


        # 共通: 座標（重心）
        r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
        r_nb_code += f'nb <- poly2nb(as(polygons, "Spatial"), queen = {nb_queen})\n'

        r_statistic__index = self.parameterAsEnum(parameters, self.STATISTICS_TYPE, context)
        r_statistic_type = ['Moran\'s I', 'Geary\'s C', 'Getis-Ord G', 'Getis-Ord G*'][r_statistic__index]
        
        nb_method_index = self.parameterAsEnum(parameters, self.NB_METHOD_TYPE, context)
        nb_method = ['poly2nb', 'dnearneigh', 'knearneigh'][nb_method_index]

        if nb_method == 'poly2nb':
            r_nb_code = f'nb <- poly2nb(as(polygons, "Spatial"), queen = {nb_queen})\n'
        elif nb_method == 'dnearneigh':
            r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
            r_nb_code += f'nb <- dnearneigh(coords, d1 = {d_minimum}, d2 = {d_maximum})\n'
        elif nb_method == 'knearneigh':
            r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
            r_nb_code += f'knn <- knearneigh(coords, k = {k_number})\n'
            r_nb_code += 'nb <- knn2nb(knn)\n'



        # 入力レイヤを一時GPKGとして保存
        input_path = os.path.join(tempfile.gettempdir(), "input_polygons.gpkg")
        QgsVectorFileWriter.writeAsVectorFormat(input_layer, input_path, "utf-8", input_layer.crs(), "GPKG")


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
        # 投影座標系に変換（必ず最初に実施）
        if (grepl("longlat", st_crs(polygons)$proj4string)) {{
            polygons <- st_transform(polygons, 3857)
        }}
        id_field <- "{field_name}"

        # 近接構築
        {r_nb_code}

        # nb2listw に zero.policy=TRUE をつけた場合、listw$neighbours の長さは nb に合わせて出る
        # その代わり、重み・隣接が 0 のポリゴンも明示的に扱う必要あり
        # 行基準化ウェイト行列
        # 距離減衰を使うかどうか（Pythonから渡されたフラグ）
        if ({r_use_decay}) {{
            glist <- nbdists(nb,centroids)
            glist <- lapply(glist,function(x) 1/x)
            # 重み付き listw 作成
            listw <- nb2listw(nb, glist = glist, style = "W", zero.policy = TRUE)
        }} else {{
            listw <- nb2listw(nb, style = "W", zero.policy = TRUE)
        }}

        statistic_type <- "{r_statistic_type}"  # Pythonから渡す文字列
        result_html <- ""

        if (statistic_type == "Moran's I") {{
            test <- moran.test(polygons[[id_field]], listw)
            result_html <- capture.output(test)
        }} else if (statistic_type == "Geary's C") {{
            test <- geary.test(polygons[[id_field]], listw)
            result_html <- capture.output(test)
        }} else if (statistic_type == "Getis-Ord G") {{
            test <- globalG.test(polygons[[id_field]], listw)
            result_html <- capture.output(test)
        }} else if (statistic_type == "Getis-Ord G*") {{
            test <- globalG.test(polygons[[id_field]], listw, star=TRUE)
            result_html <- capture.output(test)
        }}
        
        cat("---- nb summary ----\n")
        print(summary(nb))
        cat("---- end of summary ----\n")

        # 書き出し（CSV形式）
        if ("{output_weights_path}" != "") {{
            write.csv(weight_mat, file = "{output_weights_path}", row.names = TRUE)
        }}
        """
                
                
        # Rスクリプトを一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=".R") as f:
            f.write(r_code.encode("utf-8"))
            r_script_file = f.name

        # Rスクリプトを実行
        result = subprocess.run([rscript_path, r_script_file], capture_output=True, text=True)
        if result.returncode != 0:
            raise QgsProcessingException(f"R実行中にエラー:\n{result.stderr}")

        feedback.pushInfo("Rの出力:\n" + result.stdout)

        # Rが出力したラインレイヤをQGISで読み込む
        output_layer = QgsVectorLayer(output_path, "NeighborLines", "ogr")
        if not output_layer.isValid():
            feedback.reportError("出力されたラインレイヤが無効です")
        else:
            sink, dest_id = self.parameterAsSink(
                parameters,
                self.OUTPUT_NODE,
                context,
                output_layer.fields(),
                output_layer.wkbType(),
                output_layer.crs()
            )

            if sink:
                for feat in output_layer.getFeatures():
                    sink.addFeature(feat, QgsFeatureSink.FastInsert)
            else:
                feedback.pushInfo("ラインレイヤの出力はスキップされました。")

            
        
        # ポリゴンレイヤをQGISで読み込む
        poly_layer = QgsVectorLayer(output_poly_path, "PolygonNeighbors", "ogr")
        if poly_layer.isValid():
            sink_poly, poly_id = self.parameterAsSink(
                parameters,
                self.OUTPUT_POLYGONS,
                context,
                poly_layer.fields(),
                poly_layer.wkbType(),
                poly_layer.crs()
            )

            if sink_poly:
                for feat in poly_layer.getFeatures():
                    sink_poly.addFeature(feat, QgsFeatureSink.FastInsert)
            else:
                feedback.pushInfo("出力ポリゴンはスキップされました。")
        else:
            feedback.reportError("出力ポリゴンレイヤの読み込みに失敗しました。")

        feedback.pushInfo(result.stdout)



        result_dict = {}
        if 'dest_id' in locals():
            result_dict[self.OUTPUT_NODE] = dest_id
        if 'poly_id' in locals():
            result_dict[self.OUTPUT_POLYGONS] = poly_id
        return result_dict

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'morani'
    
    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon_adjacency_matrix.png'))

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Moran I')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr('R GISA')

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'rgisa'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return MoranIAlgorithm()
