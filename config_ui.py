import sys
import os
import yaml
import copy
import shutil
from functools import partial
from PySide6.QtWidgets import QApplication, QHBoxLayout, QFileDialog, QWidget, QVBoxLayout
from PySide6.QtGui import QIntValidator
from qfluentwidgets import (
    MessageBox, ScrollArea, SubtitleLabel,
    LineEdit, PushButton, PrimaryPushButton, BodyLabel, SpinBox
)

class ConfigUI(QWidget):
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 100

    def __init__(self, yml_path):
        super().__init__()
        self.yml_path = yml_path
        self.base_dir = os.path.dirname(yml_path)
        self.config_data = {}
        self.path_inputs = []
        self.timeout_inputs = [] # List of tuples: (script_idx, [lineedit_mon, ..., lineedit_sun])
        
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
        if not os.path.exists(self.yml_path):
            MessageBox("错误", f"找不到文件: {self.yml_path}", self).exec()
            return
            
        try:
            with open(self.yml_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            MessageBox("解析错误", f"解析 {self.yml_path} 失败: {str(e)}", self).exec()
            return
        except Exception as e:
            MessageBox("读取错误", f"读取 {self.yml_path} 失败: {str(e)}", self).exec()
            return
            
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
            
            weekly_timeouts = script.get('weekly_timeouts', [script.get('run_timeout_seconds', 0)] * 7)
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
        
        # 1. Collect data from UI and update memory config
        for idx, path_input in self.path_inputs:
            if idx < len(script_list):
                path_val = path_input.text().strip()
                if not path_val:
                    MessageBox("警告", f"脚本 {idx+1} 的路径为空，可能会导致运行问题！", self).exec()
                script_list[idx]['script_path'] = path_val
                
        for idx, lineedits in self.timeout_inputs:
            if idx < len(script_list):
                weekly_timeouts = []
                for le in lineedits:
                    try:
                        val = int(le.text().strip())
                    except ValueError:
                        val = 0
                    weekly_timeouts.append(val)
                script_list[idx]['weekly_timeouts'] = weekly_timeouts
                
        # 2. Generate 01.yml to 07.yml
        try:
            for i in range(1, 8):
                # Day index: 1 = Monday, 7 = Sunday
                # Our weekly_timeouts array is 0-indexed (0 = Monday, 6 = Sunday)
                data_copy = copy.deepcopy(self.config_data)
                
                for script in data_copy.get('script_list', []):
                    # Set the run_timeout_seconds to the specific day's timeout
                    timeouts = script.get('weekly_timeouts', [])
                    if len(timeouts) == 7:
                        script['run_timeout_seconds'] = timeouts[i-1]
                        
                file_path = os.path.join(self.base_dir, f"{i:02d}.yml")
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data_copy, f, allow_unicode=True, sort_keys=False)
                    
            # Auto-copy to script_chain directory if possible
            try:
                sys.path.append(os.path.join(self.base_dir, "OneDragon-ScriptChainer", "src"))
                from one_dragon.utils.os_utils import get_path_under_work_dir
                output_dir = get_path_under_work_dir("config", "script_chain")
                os.makedirs(output_dir, exist_ok=True)
                for i in range(1, 8):
                    chain_name = f"{i:02d}.yml"
                    shutil.copy(os.path.join(self.base_dir, chain_name), os.path.join(output_dir, chain_name))
            except Exception as e:
                print("Warning: Could not auto-copy to script_chain", e)
                
        except Exception as e:
            MessageBox("保存错误", f"保存配置失败: {str(e)}", self).exec()
            return
            
        w = MessageBox("成功", "7份配置已成功生成并保存！", self)
        w.yesButton.setText("确定")
        w.cancelButton.hide()
        w.exec()

def run_config_ui(config_name="01.yml"):
    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    yml_path = os.path.join(base_dir, config_name)
    window = ConfigUI(yml_path)
    window.show()
    app.exec()

if __name__ == "__main__":
    run_config_ui()
