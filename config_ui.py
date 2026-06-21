import sys
import os
import yaml
from functools import partial
from PySide6.QtWidgets import QApplication, QHBoxLayout, QFileDialog, QWidget, QVBoxLayout
from qfluentwidgets import (
    MessageBox, ScrollArea, SubtitleLabel,
    LineEdit, PushButton, PrimaryPushButton, BodyLabel
)

class ConfigUI(QWidget):
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 100

    def __init__(self, yml_path):
        super().__init__()
        self.yml_path = yml_path
        self.config_data = {}
        self.path_inputs = []
        
        self.init_ui()
        self.load_data()
        
    def init_ui(self):
        self.setWindowTitle("一键配置脚本路径")
        self.resize(700, 500)
        self.layout = QVBoxLayout(self)
        
        title = SubtitleLabel("配置脚本路径", self)
        self.layout.addWidget(title)
        
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_area.setWidget(self.scroll_widget)
        
        self.layout.addWidget(self.scroll_area)
        
        btn_layout = QHBoxLayout()
        self.save_btn = PrimaryPushButton("保存配置 (Save)", self)
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
            row_layout = QHBoxLayout()
            
            name = script.get('display_name', f'Script {idx}')
            label = BodyLabel(name, self)
            label.setFixedWidth(self.LABEL_WIDTH)
            
            path_input = LineEdit(self)
            path_input.setText(script.get('script_path', ''))
            
            browse_btn = PushButton("选择", self)
            browse_btn.clicked.connect(partial(self.browse_file, path_input))
            
            row_layout.addWidget(label)
            row_layout.addWidget(path_input)
            row_layout.addWidget(browse_btn)
            
            self.scroll_layout.addLayout(row_layout)
            self.path_inputs.append((idx, path_input))
            
        self.scroll_layout.addStretch()
            
    def browse_file(self, path_input):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择脚本文件", "", self.FILE_FILTER)
        if file_path:
            path_input.setText(os.path.normpath(file_path))
            
    def save_data(self):
        script_list = self.config_data.get('script_list', [])
        for idx, path_input in self.path_inputs:
            if idx < len(script_list):
                path_val = path_input.text().strip()
                if not path_val:
                    MessageBox("警告", f"脚本 {idx+1} 的路径为空，可能会导致运行问题！", self).exec()
                script_list[idx]['script_path'] = path_val
                
        try:
            with open(self.yml_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            MessageBox("保存错误", f"保存配置失败: {str(e)}", self).exec()
            return
            
        w = MessageBox("成功", "配置已保存！", self)
        w.yesButton.setText("确定")
        w.cancelButton.hide()
        w.exec()

def run_config_ui():
    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    yml_path = os.path.join(base_dir, "99.yml")
    window = ConfigUI(yml_path)
    window.show()
    app.exec()

if __name__ == "__main__":
    run_config_ui()
