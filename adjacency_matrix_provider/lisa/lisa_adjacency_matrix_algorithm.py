# -*- coding: utf-8 -*-

"""
/***************************************************************************
R SpatialStatistics
                              -------------------
        begin                : 2025-04-13
        copyright            : (C) 2025 by nbayashi
        email                : naoya_nstyle@hotmail.co.jp
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
                       QgsVectorLayer,
                       QgsFeatureSink,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSink,
                       QgsWkbTypes)


from qgis.PyQt.QtGui import QIcon
from ...utils.layer_tools import get_layer_path_or_temp


class LISAAdjacencyMatrixAlgorithm(QgsProcessingAlgorithm):

    FIELD = 'FIELD'
    INPUT = 'INPUT'
    STATISTICS_TYPE = 'STATISTICS_TYPE'
    NEIGHBOR_TYPE = 'NEIGHBOR_TYPE'
    OUTPUT_POLYGONS = 'OUTPUT_POLYGONS'



    def initAlgorithm(self, config):
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
                options=['Local Moran\'s I','Local Getis-Ord G','Local Getis-Ord G*'],
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
            QgsProcessingParameterFeatureSink(
                name=self.OUTPUT_POLYGONS,
                description='Polygons with neighbor attributes',
                createByDefault=True 
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



        # 共通: 座標（重心）
        r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
        r_nb_code += f'nb <- poly2nb(as(polygons, "Spatial"), queen = {nb_queen})\n'
        
        r_statistic__index = self.parameterAsEnum(parameters, self.STATISTICS_TYPE, context)
        r_statistic_type = ['Local Moran\'s I', 'Local Getis-Ord G', 'Local Getis-Ord G*'][r_statistic__index]
        

        # 入力レイヤを一時GPKGとして保存
        input_path, is_temp = get_layer_path_or_temp(input_layer)
        
        # 出力先（Rが書き出す）
        output_poly_path = os.path.join(tempfile.gettempdir(), f"output_neighbors_{uuid.uuid4().hex}.gpkg")
        

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


        # 隣接行列の作成
        statistic_type <- "{r_statistic_type}"  # Pythonから渡す文字列
        if (statistic_type == "Local Getis-Ord G") {{
            listw <- nb2listw(nb, style="B", zero.policy=TRUE)
        }} else if (statistic_type == "Local Getis-Ord G*") {{
            nb_self <- include.self(nb)
            listw <- nb2listw(nb_self, style="B", zero.policy=TRUE)
        }} else {{
            listw <- nb2listw(nb, style="W", zero.policy=TRUE)
        }}
        




        if (statistic_type == "Local Moran's I") {{
            test <- localmoran(polygons[[id_field]], listw, zero.policy = TRUE)
            test_result <- capture.output(test)
            quadr <- attr(test, "quadr")

            # 結果を属性に追加
            attrs <- st_drop_geometry(polygons)
            attrs$Ii <- test[, "Ii"]
            attrs$E <- test[, "E.Ii"]
            attrs$Var <- test[, "Var.Ii"]
            attrs$Z <- test[, "Z.Ii"]
            attrs$Pr_z <- test[, "Pr(z != E(Ii))"]
            attrs$clus_mean <- quadr[,"mean"]
            attrs$clus_median <- quadr[,"median"]
            attrs$clus_pysal <- quadr[,"pysal"]

            # geometryと再結合
            polygons <- st_sf(attrs, geometry = st_geometry(polygons))
        }} else if (statistic_type == "Local Getis-Ord G") {{
            test <- localG(polygons[[id_field]], listw, zero.policy = TRUE)
            #test_result <- capture.output(test)
            internals <- attr(test, "internals")
            # 結果を属性に追加
            attrs <- st_drop_geometry(polygons)
            attrs$Gi <-  as.numeric(test)
            attrs$Pr_z <- internals[, "Pr(z != E(Gi))"]

            # geometryと再結合
            polygons <- st_sf(attrs, geometry = st_geometry(polygons))
        }} else if (statistic_type == "Local Getis-Ord G*") {{
            test <- localG(polygons[[id_field]], listw, zero.policy = TRUE)
            #test_result <- capture.output(test)
            internals <- attr(test, "internals")
            cluster <- attr(test,"cluster")
            # 結果を属性に追加
            attrs <- st_drop_geometry(polygons)
            attrs$Gi <-  as.numeric(test)
            attrs$Pr_z <- internals[, "Pr(z != E(G*i))"]
            attrs$cluster <- cluster

            # geometryと再結合
            polygons <- st_sf(attrs, geometry = st_geometry(polygons))

        }} 

        # 必ずsfオブジェクトに戻す
        polygons <- st_as_sf(polygons)
        # 結果を出力
        st_write(polygons, "{output_poly_path}", delete_dsn = TRUE)


        """
                
                
        # Rスクリプトを一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=".R") as f:
            f.write(r_code.encode("utf-8"))
            r_script_file = f.name

        # Rスクリプトを実行
        result = subprocess.run([rscript_path, r_script_file], capture_output=True, text=True)
        if result.returncode != 0 or 'Error' in result.stderr:
            raise QgsProcessingException(f"R実行中にエラー:\n{result.stderr}\n{result.stdout}")

        feedback.pushInfo("=== LISA Statistics Result ===\n" + result.stdout)
        feedback.pushInfo("=============================")

        # Rが書き出したポリゴンを読み込み
        poly_layer = QgsVectorLayer(output_poly_path, "LISA_Polygons", "ogr")
        if poly_layer.isValid():
            sink_poly, poly_id = self.parameterAsSink(
                parameters,
                self.OUTPUT_POLYGONS,
                context,
                poly_layer.fields(),
                QgsWkbTypes.MultiPolygon,  
                poly_layer.crs()
            )
            if sink_poly:
                for feat in poly_layer.getFeatures():
                    sink_poly.addFeature(feat, QgsFeatureSink.FastInsert)
        else:
            feedback.reportError("出力ポリゴンレイヤの読み込みに失敗しました。")


        # 一時ファイルを削除
        os.remove(r_script_file)
        if is_temp and os.path.exists(input_path):
            os.remove(input_path)


        result_dict = {}
        if 'poly_id' in locals():
            result_dict[self.OUTPUT_POLYGONS] = poly_id

        return result_dict

    def name(self):
        return 'lisaadjacencymatrix'
    
    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon_lisa_adjacency_matrix.png'))

    def displayName(self):
        return self.tr('LISA(Adjacency matrix)')

    def group(self):
        return self.tr('Local Indicator of Spatial Association')

    def groupId(self):
        return 'rlisa'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LISAAdjacencyMatrixAlgorithm()
