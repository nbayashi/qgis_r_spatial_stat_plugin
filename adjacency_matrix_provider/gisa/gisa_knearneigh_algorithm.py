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
                       QgsVectorLayer,
                       QgsVectorFileWriter,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFileDestination)


from qgis.PyQt.QtGui import QIcon

class GISAKnearneighAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    FIELD = 'FIELD'
    K_NUM = 'K'
    REMOVE_DUPLICATE_LINES = 'REMOVE_DUPLICATE_LINES'
    USE_DISTANCE_DECAY = 'USE_DISTANCE_DECAY'
    OUTPUT_NODE = 'OUTPUT_NODE'
    OUTPUT_POLYGONS = 'OUTPUT_POLYGONS'
    OUTPUT_WEIGHTS_CSV = 'OUTPUT_WEIGHTS_CSV'


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
        



        # knearneigh → 近接数設定
        self.addParameter(
            QgsProcessingParameterNumber(
                self.K_NUM,
                'Number of nearest neighbors (for knearneigh)',
                defaultValue=4,
                minValue=1
                )
        )

        # 重複行の削除
        self.addParameter(
            QgsProcessingParameterBoolean(
                name=self.REMOVE_DUPLICATE_LINES,
                description='Remove duplicated lines (A→B and B→A)',
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                name=self.USE_DISTANCE_DECAY,
                description='Use distance-decay weights (1/d)',
                defaultValue=False
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_NODE,
                self.tr('Output layer'),
                optional=True,  
                createByDefault=True 
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                name=self.OUTPUT_POLYGONS,
                description='Polygons with neighbor attributes',
                optional=True,  
                createByDefault=True 
            )
        )
        # CSV path
        self.addParameter(
            QgsProcessingParameterFileDestination(
                name=self.OUTPUT_WEIGHTS_CSV,
                description='Row-standardized weights matrix (CSV)',
                fileFilter='CSV files (*.csv)',
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

        output_weights_path = self.parameterAsFile(parameters, self.OUTPUT_WEIGHTS_CSV, context)



        k = self.parameterAsInt(parameters, self.K_NUM, context)
        remove_duplicates = self.parameterAsBool(parameters, self.REMOVE_DUPLICATE_LINES, context)
        r_remove_flag = "TRUE" if remove_duplicates else "FALSE"

        use_distance_decay = self.parameterAsBool(parameters, 'USE_DISTANCE_DECAY', context)
        r_use_decay = "TRUE" if use_distance_decay else "FALSE"

        # 共通: 座標（重心）
        r_nb_code = "coords <- st_coordinates(st_centroid(polygons))\n"

        r_nb_code += f'''
        knn <- knearneigh(coords, k = {k})
        nb <- knn2nb(knn)
        '''


        # 入力レイヤを一時GPKGとして保存
        input_path = os.path.join(tempfile.gettempdir(), "input_polygons.gpkg")
        QgsVectorFileWriter.writeAsVectorFormat(input_layer, input_path, "utf-8", input_layer.crs(), "GPKG")

        # 出力先（Rが書き出す）
        output_path = os.path.join(tempfile.gettempdir(), "output_neighbors.gpkg")
        output_poly_path = os.path.join(tempfile.gettempdir(), "nb_polygons.gpkg")
        

        # Rコードを生成
        r_code = f"""
        # パッケージ確認＆読み込み
        packages <- c("sf", "spdep", "dplyr")
        for (pkg in packages) {{
            if (!requireNamespace(pkg, quietly = TRUE)) {{
                install.packages(pkg, repos = "https://cloud.r-project.org")
            }}
            library(pkg, character.only = TRUE)
        }}

        # 入力読み込み
        polygons <- st_read("{input_path}")
        id_field <- "{field_name}"

        # 近接構築
        {r_nb_code}

        # ID & centroid
        id_values <- polygons[[id_field]]
        centroids <- st_centroid(polygons)

        # edge list
        edge_list <- do.call(rbind, lapply(seq_along(nb), function(i) {{
            data.frame(from = i, to = nb[[i]])
        }}))

        # 重複行削除
        if ({r_remove_flag}) {{
        edge_list <- edge_list %>%
            mutate(pair = paste(pmin(from, to), pmax(from, to), sep = "_")) %>%
            distinct(pair, .keep_all = TRUE)
            }}

        edge_list$from_id <- id_values[edge_list$from]
        edge_list$to_id   <- id_values[edge_list$to]

        # ライン生成 + 距離付加
        lines <- lapply(1:nrow(edge_list), function(i) {{
            from_geom <- centroids[edge_list$from[i], ]
            to_geom   <- centroids[edge_list$to[i], ]
            line <- st_linestring(rbind(st_coordinates(from_geom), st_coordinates(to_geom)))
            dist <- st_distance(from_geom, to_geom, by_element = TRUE)
            list(geom = line, dist = as.numeric(dist))
        }})

        # ラインレイヤ生成
        line_sf <- st_sf(
            from = edge_list$from_id,
            to = edge_list$to_id,
            distance = sapply(lines, function(x) x$dist),
            geometry = st_sfc(lapply(lines, function(x) x$geom)),
            crs = st_crs(polygons)
        )
        st_write(line_sf, "{output_path}", delete_dsn = TRUE)


        # ポリゴンに近接行列を付与
        neighbor_ids <- sapply(nb, function(neigh) paste(id_values[neigh], collapse = ","))
        neighbor_count <- sapply(nb, length)

        polygons$neighbor_ids <- neighbor_ids
        polygons$neighbor_count <- neighbor_count

        # ポリゴンとして保存
        st_write(polygons, "{output_poly_path}", delete_dsn = TRUE)


        # nb2listw に zero.policy=TRUE をつけた場合、listw$neighbours の長さは nb に合わせて出る
        # その代わり、重み・隣接が 0 のポリゴンも明示的に扱う必要あり
        # 行基準化ウェイト行列
        if ({r_use_decay}) {{
            glist <- nbdists(nb,centroids)
            glist <- lapply(glist,function(x) 1/x)
            # 重み付き listw 作成
            listw <- nb2listw(nb, glist = glist, style = "W", zero.policy = TRUE)
        }} else {{
            listw <- nb2listw(nb, style = "W", zero.policy = TRUE)
        }}

        # IDリスト（行と列の順番を固定）
        all_ids <- id_values

        # 初期化：全ゼロ行列
        weight_mat <- matrix(0, nrow = length(all_ids), ncol = length(all_ids))
        rownames(weight_mat) <- all_ids
        colnames(weight_mat) <- all_ids

        # ウェイト代入
        for (i in seq_along(listw$neighbours)) {{
        from_id <- id_values[i]
        neigh_ids <- listw$neighbours[[i]]
        weights <- listw$weights[[i]]
        
        if (length(neigh_ids) > 0) {{
            to_ids <- id_values[neigh_ids]
            weight_mat[as.character(from_id), as.character(to_ids)] <- weights
        }}
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
        return 'gisaknearneigh'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon_knearneigh.png'))


    def displayName(self):
        return self.tr('K-nearest neighbors')

    def group(self):
        return self.tr('Global Indicator of Spatial Association')

    def groupId(self):
        return 'rgisa'


    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GISAKnearneighAlgorithm()
