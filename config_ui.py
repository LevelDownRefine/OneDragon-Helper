import sys
import os
import shutil
import yaml
from functools import partial
from PySide6.QtWidgets import QApplication, QHBoxLayout, QFileDialog, QWidget, QVBoxLayout
from qfluentwidgets import (
    MessageBox, ScrollArea, SubtitleLabel,
    LineEdit, PushButton, PrimaryPushButton, BodyLabel, ComboBox, SpinBox
)

class ConfigUI(QWidget):
    FILE_FILTER = "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)"
    LABEL_WIDTH = 100

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.current_day_index = 1 # 1 for Monday to 7 for Sunday
        self.config_data = {}
        self.path_inputs = []
        self.timeout_inputs = []
        
        self.ensure_configs_exist()
        
        self.init_ui()
        self.load_data()
        
    def ensure_configs_exist(self):
        template_path = os.path.join(self.base_dir, "01.yml")
        for i in range(1, 8):
            target_path = os.path.join(self.base_dir, f"{i:02d}.yml")
            if not os.path.exists(target_path) and os.path.exists(template_path):
                shutil.copy(template_path, target_path)
                
    def get_yml_path(self, day_index=None):
        idx = day_index if day_index is not None else self.current_day_index
        return os.path.join(self.base_dir, f"{idx:02d}.yml")
        
    def init_ui(self):
        self.setWindowTitle("一键配置脚本路径与超时时间")
        self.resize(800, 600)
        self.layout = QVBoxLayout(self)
        
        title = SubtitleLabel("配置脚本路径与超时时间", self)
        self.layout.addWidget(title)
        
        # Add day selector
        day_layout = QHBoxLayout()
        day_label = BodyLabel("选择星期：", self)
        self.day_combo = ComboBox(self)
        self.day_combo.addItems(["星期一 (01)", "星期二 (02)", "星期三 (03)", "星期四 (04)", "星期五 (05)", "星期六 (06)", "星期日 (07)"])
        self.day_combo.currentIndexChanged.connect(self.on_day_changed)
        day_layout.addWidget(day_label)
        day_layout.addWidget(self.day_combo)
        day_layout.addStretch()
        self.layout.addLayout(day_layout)
        
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_area.setWidget(self.scroll_widget)
        
        self.layout.addWidget(self.scroll_area)
        
        btn_layout = QHBoxLayout()
        self.save_btn = PrimaryPushButton("保存配置 (Save)", self)
        self.save_btn.clicked.connect(self.save_data_with_msg)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        self.layout.addLayout(btn_layout)
        
    def on_day_changed(self, index):
        self.save_data_silent()
        self.current_day_index = index + 1
        self.load_data()
        
    def clear_scroll_layout(self):
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self.clear_layout(item.layout())
        self.path_inputs.clear()
        self.timeout_inputs.clear()
        
    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self.clear_layout(item.layout())
                layout.removeItem(item)

    def load_data(self):
        self.clear_scroll_layout()
        yml_path = self.get_yml_path()
        if not os.path.exists(yml_path):
            MessageBox("错误", f"找不到文件: {yml_path}", self).exec()
            return
            
        try:
            with open(yml_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            MessageBox("解析错误", f"解析 {yml_path} 失败: {str(e)}", self).exec()
            return
        except Exception as e:
            MessageBox("读取错误", f"读取 {yml_path} 失败: {str(e)}", self).exec()
            return
            
        script_list = self.config_data.get('script_list', [])
        
        # Header
        header_layout = QHBoxLayout()
        name_label = BodyLabel("脚本名称", self)
        name_label.setFixedWidth(self.LABEL_WIDTH)
        path_label = BodyLabel("脚本路径 (修改将同步至全周)", self)
        timeout_label = BodyLabel("超时(秒)", self)
        timeout_label.setFixedWidth(80)
        
        header_layout.addWidget(name_label)
        header_layout.addWidget(path_label)
        header_layout.addWidget(timeout_label)
        
        browse_placeholder = BodyLabel("", self)
        browse_placeholder.setFixedWidth(60)
        header_layout.addWidget(browse_placeholder)
        
        self.scroll_layout.addLayout(header_layout)
        
        for idx, script in enumerate(script_list):
            row_layout = QHBoxLayout()
            
            name = script.get('display_name', f'Script {idx}')
            label = BodyLabel(name, self)
            label.setFixedWidth(self.LABEL_WIDTH)
            
            path_input = LineEdit(self)
            path_input.setText(script.get('script_path', ''))
            
            timeout_input = SpinBox(self)
            timeout_input.setRange(0, 86400)
            timeout_input.setValue(script.get('run_timeout_seconds', 0))
            timeout_input.setFixedWidth(80)
            
            browse_btn = PushButton("选择", self)
            browse_btn.setFixedWidth(60)
            browse_btn.clicked.connect(partial(self.browse_file, path_input))
            
            row_layout.addWidget(label)
            row_layout.addWidget(path_input)
            row_layout.addWidget(timeout_input)
            row_layout.addWidget(browse_btn)
            
            self.scroll_layout.addLayout(row_layout)
            self.path_inputs.append((idx, path_input))
            self.timeout_inputs.append((idx, timeout_input))
            
        self.scroll_layout.addStretch()
            
    def browse_file(self, path_input):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择脚本文件", "", self.FILE_FILTER)
        if file_path:
            path_input.setText(os.path.normpath(file_path))
            
    def _apply_changes_to_config(self):
        """Update self.config_data from UI inputs and return updated paths."""
        script_list = self.config_data.get('script_list', [])
        paths = []
        for idx, path_input in self.path_inputs:
            path_val = path_input.text().strip()
            paths.append(path_val)
            if idx < len(script_list):
                script_list[idx]['script_path'] = path_val
                
        for idx, timeout_input in self.timeout_inputs:
            if idx < len(script_list):
                script_list[idx]['run_timeout_seconds'] = timeout_input.value()
                
        return paths
        
    def _sync_paths_to_other_configs(self, paths):
        """Sync the paths to all 7 configs."""
        for i in range(1, 8):
            if i == self.current_day_index:
                continue
            
            target_path = self.get_yml_path(i)
            if not os.path.exists(target_path):
                continue
                
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                
                script_list = data.get('script_list', [])
                for idx, path_val in enumerate(paths):
                    if idx < len(script_list):
                        script_list[idx]['script_path'] = path_val
                        
                with open(target_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            except Exception as e:
                print(f"Sync error for {target_path}: {e}")

    def save_data_silent(self):
        paths = self._apply_changes_to_config()
        
        yml_path = self.get_yml_path()
        try:
            with open(yml_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"Save error for {yml_path}: {e}")
            
        self._sync_paths_to_other_configs(paths)

    def save_data_with_msg(self):
        paths = self._apply_changes_to_config()
        
        # Check warnings
        script_list = self.config_data.get('script_list', [])
        for idx, path_val in enumerate(paths):
            if not path_val:
                MessageBox("警告", f"脚本 {idx+1} 的路径为空，可能会导致运行问题！", self).exec()
                
        yml_path = self.get_yml_path()
        try:
            with open(yml_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, allow_unicode=True, sort_keys=False)
                
            self._sync_paths_to_other_configs(paths)
        except Exception as e:
            MessageBox("保存错误", f"保存配置失败: {str(e)}", self).exec()
            return
            
        w = MessageBox("成功", f"配置已保存！脚本路径已同步至全周配置。", self)
        w.yesButton.setText("确定")
        w.cancelButton.hide()
        w.exec()

def run_config_ui(config_name=None):
    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    window = ConfigUI(base_dir)
    window.show()
    app.exec()

if __name__ == "__main__":
    run_config_ui()
