import os
from qgis.PyQt.QtWidgets import QDialog
from qgis.core import QgsSettings
from qgis.PyQt import uic

class RSpatialStatisticsSettingDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.ui = uic.loadUi(
            os.path.join(os.path.dirname(__file__), "r_runner_plugin_dialog.ui"), self
        )
        self.settings = QgsSettings()

         # 初期値を読み込んで設定
        self.ui.rscriptPath.setFilePath(self.settings.value("RRunner/RscriptPath", ""))
        self.ui.pushButton_run.clicked.connect(self.save_path)
        self.ui.pushButton_cancel.clicked.connect(self.close)
        
    def save_path(self):
        # QgsFileWidgetからパスを取得
        selected_path = self.ui.rscriptPath.filePath()
        if selected_path:
            self.settings.setValue("RRunner/RscriptPath", selected_path)
        self.accept()
