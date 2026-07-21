import sys
import os
import copy
import shutil
import yaml
from functools import partial

from PySide6.QtWidgets import QApplication, QHBoxLayout, QFileDialog, QWidget, QVBoxLayout, QDialog
from PySide6.QtGui import QIntValidator
from qfluentwidgets import (
    MessageBox, ScrollArea, SubtitleLabel,
    LineEdit, PushButton, PrimaryPushButton, BodyLabel
)

from src.utils import (
    get_path_under_root,
    get_path_under_onedragon,
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
)
from src.config.bgi import copy_BGI_User


def copy_python_scripts():
    py_script_dir = get_path_under_root("src", "python_script")
    file_names = [f for f in os.listdir(py_script_dir) if f.endswith(".py")]
    for file_name in file_names:
        input_path = os.path.join(py_script_dir, file_name)
        output_path = get_path_under_onedragon("config", "script_chain", "scripts")
        if not os.path.exists(os.path.join(output_path, file_name)):
            shutil.copy(input_path, output_path)
            print(f"已复制Python脚本{file_name}到: {output_path}")
        else:
            print(f"[OneDragonHelper] Python脚本{file_name}已存在，跳过复制")


class ConfigUI(QWidget):
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 100

    def __init__(self):
        super().__init__()
        # 优先读 config.yml（运行时生成），不存在时读 example.yml（模板）
        self.save_path = get_config_yml_path_under_root()
        if os.path.exists(self.save_path):
            self.source_path = self.save_path
        else:
            self.source_path = os.path.join(os.path.dirname(self.save_path), "config.example.yml")
        self.config_data = {}
        self.path_inputs = []
        self.timeout_inputs = []

        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle("一键配置脚本路径与超时时间")
        self.resize(850, 600)
        self.layout = QVBoxLayout(self)

        title = SubtitleLabel("配置脚本路径与每周超时时间", self)
        self.layout.addWidget(title)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_area.setWidget(self.scroll_widget)

        self.layout.addWidget(self.scroll_area)

        btn_layout = QHBoxLayout()
        self.save_btn = PrimaryPushButton("保存并生成7份配置 (Save & Generate)", self)
        self.save_btn.clicked.connect(self.save_data)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        self.layout.addLayout(btn_layout)

    def load_data(self):
        if not os.path.exists(self.source_path):
            MessageBox("错误", f"找不到模板文件: {self.source_path}", self).exec()
            return

        with open(self.source_path, 'r', encoding='utf-8') as f:
            self.config_data = yaml.safe_load(f)

        # 从 weekly_timeouts.yml 读取每周超时配置
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        self.weekly_timeouts_map = weekly_timeouts_map

        script_list = self.config_data.get('script_list', [])
        for idx, script in enumerate(script_list):
            script_layout = QVBoxLayout()

            # Row 1: Name and Path
            row1 = QHBoxLayout()
            name = script.get('display_name', f'Script {idx}')
            label = BodyLabel(name, self)
            label.setFixedWidth(self.LABEL_WIDTH)

            path_input = LineEdit(self)
            path_input.setText(script.get('script_path', ''))

            browse_btn = PushButton("选择", self)
            browse_btn.clicked.connect(partial(self.browse_file, path_input))

            row1.addWidget(label)
            row1.addWidget(path_input)
            row1.addWidget(browse_btn)

            # Row 2: Weekly Timeouts
            row2 = QHBoxLayout()
            timeout_label = BodyLabel("超时(秒):", self)
            timeout_label.setFixedWidth(self.LABEL_WIDTH)
            row2.addWidget(timeout_label)

            weekly_timeouts = weekly_timeouts_map.get(name, [script.get('run_timeout_seconds', 0)] * 7)
            if len(weekly_timeouts) < 7:
                weekly_timeouts.extend([0] * (7 - len(weekly_timeouts)))

            day_names = ["一", "二", "三", "四", "五", "六", "日"]
            lineedits = []

            for day_idx in range(7):
                day_label = BodyLabel(f"周{day_names[day_idx]}", self)
                lineedit = LineEdit(self)
                lineedit.setValidator(QIntValidator(0, 86400, self))
                lineedit.setText(str(weekly_timeouts[day_idx]))
                lineedit.setFixedWidth(80)

                row2.addWidget(day_label)
                row2.addWidget(lineedit)
                lineedits.append(lineedit)

            row2.addStretch()

            script_layout.addLayout(row1)
            script_layout.addLayout(row2)

            # Add some spacing between scripts
            spacing_layout = QVBoxLayout()
            spacing_layout.addSpacing(10)
            script_layout.addLayout(spacing_layout)

            self.scroll_layout.addLayout(script_layout)

            self.path_inputs.append((idx, path_input))
            self.timeout_inputs.append((idx, lineedits))

        self.scroll_layout.addStretch()

    def browse_file(self, path_input):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择脚本文件", "", self.FILE_FILTER)
        if file_path:
            path_input.setText(os.path.normpath(file_path))

    def save_data(self):
        script_list = self.config_data.get('script_list', [])

        # 1. Collect path data from UI and update config
        for idx, path_input in self.path_inputs:
            if idx < len(script_list):
                path_val = path_input.text().strip()
                if not path_val:
                    MessageBox("警告", f"脚本 {idx+1} 的路径为空，可能会导致运行问题！", self).exec()
                script_list[idx]['script_path'] = path_val

        # 2. Collect timeout data from UI into weekly_timeouts_map
        for idx, lineedits in self.timeout_inputs:
            if idx < len(script_list):
                display_name = script_list[idx].get('display_name', f'Script {idx}')
                weekly_timeouts = []
                for le in lineedits:
                    val = int(le.text().strip())
                    weekly_timeouts.append(val)
                self.weekly_timeouts_map[display_name] = weekly_timeouts

        # 3. Save config.yml
        data_copy = copy.deepcopy(self.config_data)
        with open(self.save_path, 'w', encoding='utf-8') as f:
            yaml.dump(data_copy, f, allow_unicode=True, sort_keys=False)

        # 4. Save weekly_timeouts.yml (weekly timeout settings only)
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        with open(weekly_timeouts_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.weekly_timeouts_map, f, allow_unicode=True, sort_keys=False)

        w = MessageBox("成功", "配置已成功生成并保存！", self)
        w.yesButton.setText("确定")
        w.cancelButton.hide()
        w.exec()


class SingleScriptConfigDialog(QDialog):
    """单个脚本的配置弹窗（路径选择 + 每周超时时间）"""
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 100

    def __init__(self, script_name, script_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"配置 {script_name}")
        self.resize(600, 300)

        self.script_name = script_name
        self.script_path = script_path
        self._result_path = script_path
        self._result_timeouts = []

        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = SubtitleLabel(f"配置 {self.script_name}", self)
        layout.addWidget(title)

        row1 = QHBoxLayout()
        label = BodyLabel("脚本路径:", self)
        label.setFixedWidth(self.LABEL_WIDTH)

        self.path_input = LineEdit(self)
        self.path_input.setText(self.script_path)

        self.browse_btn = PushButton("选择", self)
        self.browse_btn.clicked.connect(self.browse_file)

        row1.addWidget(label)
        row1.addWidget(self.path_input)
        row1.addWidget(self.browse_btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        timeout_label = BodyLabel("超时(秒):", self)
        timeout_label.setFixedWidth(self.LABEL_WIDTH)
        row2.addWidget(timeout_label)

        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        self.timeout_inputs = []

        for day_idx in range(7):
            day_label = BodyLabel(f"周{day_names[day_idx]}", self)
            lineedit = LineEdit(self)
            lineedit.setValidator(QIntValidator(0, 86400, self))
            lineedit.setFixedWidth(80)

            row2.addWidget(day_label)
            row2.addWidget(lineedit)
            self.timeout_inputs.append(lineedit)

        row2.addStretch()
        layout.addLayout(row2)

        btn_layout = QHBoxLayout()
        self.save_btn = PrimaryPushButton("保存", self)
        self.save_btn.clicked.connect(self.save_data)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def load_data(self):
        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}

        timeouts = weekly_timeouts_map.get(self.script_name, [0] * 7)
        if len(timeouts) < 7:
            timeouts.extend([0] * (7 - len(timeouts)))

        for idx, le in enumerate(self.timeout_inputs):
            le.setText(str(timeouts[idx]))

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择脚本文件", "", self.FILE_FILTER)
        if file_path:
            self.path_input.setText(os.path.normpath(file_path))

    def save_data(self):
        path_val = self.path_input.text().strip()
        if not path_val:
            MessageBox("警告", "脚本路径为空，可能会导致运行问题！", self).exec()
            return

        timeouts = []
        for le in self.timeout_inputs:
            val = int(le.text().strip())
            timeouts.append(val)

        config_path = get_config_yml_path_under_root()
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        for script in config_data.get('script_list', []):
            if script.get('display_name') == self.script_name:
                script['script_path'] = path_val
                break

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

        weekly_timeouts_path = get_weekly_timeouts_yml_path_under_root()
        weekly_timeouts_map = {}
        if os.path.exists(weekly_timeouts_path):
            with open(weekly_timeouts_path, 'r', encoding='utf-8') as f:
                weekly_timeouts_map = yaml.safe_load(f) or {}
        weekly_timeouts_map[self.script_name] = timeouts

        with open(weekly_timeouts_path, 'w', encoding='utf-8') as f:
            yaml.dump(weekly_timeouts_map, f, allow_unicode=True, sort_keys=False)

        w = MessageBox("成功", "配置已保存！", self)
        w.yesButton.setText("确定")
        w.cancelButton.hide()
        w.exec()

        self.accept()


def run_config_ui():
    """
    config 文件夹下生成 config.yml 及 weekly_timeouts.yml
    """
    app = QApplication(sys.argv)
    window = ConfigUI()
    window.show()
    app.exec()


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行 / 配置缺失时）"""
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        return True
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    script_list = data.get('script_list', [])
    # 脚本列表为空 或 存在空路径 → 需要配置
    if not script_list:
        return True
    for script in script_list:
        if not script.get('script_path', '').strip():
            return True
    return False


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 复制 src/python_scripts 到 OneDragon-ScriptChainer/config/script_chain/scripts
    copy_python_scripts()
    # 生成 config.yml 及 weekly_timeouts.yml
    run_config_ui()


if __name__ == "__main__":
    config_workflow()
