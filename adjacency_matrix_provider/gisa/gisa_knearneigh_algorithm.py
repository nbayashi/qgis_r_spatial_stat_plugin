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

import tempfile

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsSettings,
                       QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterEnum)


from qgis.PyQt.QtGui import QIcon
from ...utils.layer_tools import get_layer_path_or_temp

class GISAKnearneighAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    FIELD = 'FIELD'
    K_NUM = 'K'
    STATISTICS_TYPE = 'STATISTICS_TYPE'
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



       

    def processAlgorithm(self, parameters, context, feedback):
        rscript_path = QgsSettings().value("RRunner/RscriptPath", "")
        # Check if the Rscript path is set
        if not os.path.exists(rscript_path):
            raise QgsProcessingException("Rscriptのパスが無効です")
        

        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        # フィールド名を取得
        field_name = self.parameterAsString(parameters, self.FIELD, context)

        output = self.parameterAsFile(parameters, self.OUTPUT, context)



        k = self.parameterAsInt(parameters, self.K_NUM, context)
        
        use_distance_decay = self.parameterAsBool(parameters, 'USE_DISTANCE_DECAY', context)
        r_use_decay = "TRUE" if use_distance_decay else "FALSE"

        # 共通: 座標（重心）
        r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"
        r_nb_code += f'''
        knn <- knearneigh(coords, k = {k})
        nb <- knn2nb(knn)
        '''

        r_statistic__index = self.parameterAsEnum(parameters, self.STATISTICS_TYPE, context)
        r_statistic_type = ['Moran\'s I', 'Geary\'s C', 'Getis-Ord G', 'Getis-Ord G*'][r_statistic__index]
        


        # 入力レイヤを一時GPKGとして保存
        input_path, is_temp = get_layer_path_or_temp(input_layer)
        input_layer_path = input_path.replace("\\", "/")
       

        # Rコードを生成
        r_code = f"""
        # パッケージ確認＆読み込み
        # 必要なパッケージ
        packages <- c("sf", "spdep", "dplyr", "classInt")

        # ユーザーライブラリパスを取得（なければ作成）
        user_lib <- Sys.getenv("R_LIBS_USER")
        if (!dir.exists(user_lib)) {{
        dir.create(user_lib, recursive = TRUE)
        }}

        # libPaths をユーザー用に変更
        .libPaths(user_lib)

        # パッケージの読み込みとインストール
        for (pkg in packages) {{
        if (!requireNamespace(pkg, quietly = TRUE)) {{
            tryCatch({{
            install.packages(pkg, repos = "https://cloud.r-project.org", lib = user_lib)
            }}, error = function(e) {{
            message(sprintf("パッケージ '%s' のインストールに失敗しました: %s", pkg, e$message))
            }})
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
                glist <- nbdists(nb_self, centroids)
                glist <- lapply(glist, function(x) ifelse(x == 0, 1e-6, 1 / x))
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
        "Neighbor type: k-nearest neighbors (k= {k})"
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
        if result.returncode != 0:
            raise QgsProcessingException(f"R実行中にエラー:\n{result.stderr}")

        feedback.pushInfo("=== GISA Statistics Result ===\n" + result.stdout)
        feedback.pushInfo("=============================")

        os.remove(r_script_file)
        if is_temp and os.path.exists(input_path):
            os.remove(input_path)
        
        return {}

    def name(self):
        return 'gisaknearneigh'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon_gisa_knearneigh.png'))


    def displayName(self):
        return self.tr('GISA(K-nearest neighbors)')

    def group(self):
        return self.tr('Global Indicator of Spatial Association')

    def groupId(self):
        return 'rgisa'


    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GISAKnearneighAlgorithm()
