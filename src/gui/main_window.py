"""主窗口：脚本列表、增删/重排/持久化、生成 ScriptChainer 配置并运行。"""
import copy
import os

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.config.dungeon_config import (
    load_dungeon_map,
    parse_dungeon_config,
    restore_sequence_type,
)
from src.config.set_config import set_config
from src.gui.dialogs import AddScriptDialog
from src.gui.runner import ScriptChainRunner
from src.gui.state import (
    apply_weekly_timeout,
    load_ui_state,
    save_ui_state,
)
from src.gui.widgets import ScriptItem
from src.utils import (
    get_config_yml_path_under_root,
    get_path_under_onedragon,
    get_weekly_timeouts_yml_path_under_root,
    safe_path_join,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(520, 640)

        self.script_items = []
        self.all_config_data = None
        self.runner = None
        self._ui_state = load_ui_state()

        self._init_ui()
        self._load_scripts()

    def _init_ui(self):
        central = QWidget()
        central.setStyleSheet("background-color: #eef1f6;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)

        # 脚本列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(2, 2, 14, 2)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

        # 快捷操作按钮（全选 / 清空 / 添加）
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.select_all_btn = QPushButton("一键全选")
        self.select_all_btn.setFixedHeight(32)
        self.select_all_btn.setMinimumWidth(72)
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d8dee9;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #4b5563;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #3b82f6; color: #3b82f6; }
            QPushButton:pressed { background: #f0f4ff; }
        """)
        self.select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("清空选择")
        self.deselect_all_btn.setFixedHeight(32)
        self.deselect_all_btn.setMinimumWidth(72)
        self.deselect_all_btn.setCursor(Qt.PointingHandCursor)
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d8dee9;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #4b5563;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #ef4444; color: #ef4444; }
            QPushButton:pressed { background: #fef2f2; }
        """)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(self.deselect_all_btn)

        self.add_script_btn = QPushButton("添加脚本")
        self.add_script_btn.setFixedHeight(32)
        self.add_script_btn.setMinimumWidth(72)
        self.add_script_btn.setCursor(Qt.PointingHandCursor)
        self.add_script_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #d8dee9;
                border-radius: 8px;
                background: white;
                font-size: 11px;
                color: #4b5563;
                padding: 0 16px;
            }
            QPushButton:hover { border-color: #22c55e; color: #16a34a; }
            QPushButton:pressed { background: #f0fdf4; }
        """)
        self.add_script_btn.clicked.connect(self._add_script)
        action_layout.addWidget(self.add_script_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # 运行按钮
        self.run_btn = QPushButton("▶ 运行全部开启的脚本")
        self.run_btn.setFixedHeight(46)
        self.run_btn.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #4f8cff, stop:1 #3b82f6);
                color: white;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #5b96ff, stop:1 #2f6fed);
            }
            QPushButton:pressed { background: #2f6fed; }
            QPushButton:disabled { background: #cbd5e1; }
        """)
        self.run_btn.clicked.connect(self._run_selected)
        layout.addWidget(self.run_btn)

    def _load_scripts(self):
        with open(get_config_yml_path_under_root(), encoding='utf-8') as f:
            self.all_config_data = yaml.safe_load(f)

        self.dungeon_map = load_dungeon_map()

        assert 'script_list' in self.all_config_data, "[main_window] config.yml 缺少 script_list 字段"

        for item in self.script_items:
            item.deleteLater()
        self.script_items.clear()

        for data in self.all_config_data['script_list']:
            name = data['display_name']
            dungeon_cfg = self.dungeon_map.get(name)  # optional: 不是所有脚本都有副本配置
            options, seq_map, show_seq = parse_dungeon_config(dungeon_cfg)

            saved = self._ui_state.get(name)  # optional: 新脚本可能没有保存的状态
            if saved:
                saved = restore_sequence_type(saved, seq_map)
            item = self._create_script_item(data, saved)
            self.scroll_layout.insertWidget(len(self.script_items), item)
            self.script_items.append(item)

    def _create_script_item(self, data, saved_state):
        """构造 ScriptItem 并注入 UI 状态回调（_load_scripts 与 _append_script 共用）"""
        name = data['display_name']
        dungeon_cfg = self.dungeon_map.get(name)  # optional: 不是所有脚本都有副本配置
        options, seq_map, show_seq = parse_dungeon_config(dungeon_cfg)
        item = ScriptItem(data, dungeon_options=options if options else None,
                          sequence_options_map=seq_map if show_seq else None,
                          show_sequence=show_seq, saved_state=saved_state,
                          reorder_callback=self._reorder_scripts,
                          delete_callback=self._delete_script)
        item.set_state_callback(self._persist_ui_state)
        return item

    def _persist_ui_state(self):
        """收集所有脚本的 UI 状态并保存"""
        state = {}
        for item in self.script_items:
            state[item.display_name] = item.get_state()
        save_ui_state(state)

    def _reorder_scripts(self, src_name, dst_name):
        """把 src_name 对应的脚本移动到 dst_name 所在位置，并同步 UI 与 config.yml"""
        script_items = self.script_items
        src_idx = next((i for i, it in enumerate(script_items) if it.display_name == src_name), None)
        assert src_idx is not None, f"[main_window] 拖拽源脚本不存在: {src_name}"
        dst_idx = next((i for i, it in enumerate(script_items) if it.display_name == dst_name), None)
        assert dst_idx is not None, f"[main_window] 拖拽目标脚本不存在: {dst_name}"
        item = script_items.pop(src_idx)
        script_items.insert(dst_idx, item)

        # 同步 config.yml 中的顺序（以 UI 顺序为准）
        scripts = self.all_config_data['script_list']
        s_idx = next((i for i, s in enumerate(scripts) if s['display_name'] == src_name), None)
        assert s_idx is not None, f"[main_window] config 中找不到源脚本: {src_name}"
        script = scripts.pop(s_idx)
        scripts.insert(dst_idx, script)

        self._relayout_script_widgets()
        self._save_script_order()

    def _relayout_script_widgets(self):
        """按 self.script_items 当前顺序重排滚动区内的 widget（不销毁 widget）"""
        while self.scroll_layout.count():
            self.scroll_layout.takeAt(0)
        for item in self.script_items:
            self.scroll_layout.addWidget(item)
        self.scroll_layout.addStretch()

    def _delete_script(self, display_name):
        """删除指定脚本：弹确认框 → 从 UI 与 config.yml 移除并持久化"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除脚本「{display_name}」吗？\n将从启动器移除并保存到 config.yml。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._remove_script(display_name)

    def _remove_script(self, display_name):
        """实际移除逻辑（无确认），供 _delete_script 与测试复用"""
        idx = next((i for i, it in enumerate(self.script_items)
                    if it.display_name == display_name), None)
        if idx is None:
            return
        item = self.script_items.pop(idx)

        s_idx = next((i for i, s in enumerate(self.all_config_data['script_list'])
                      if s['display_name'] == display_name), None)
        if s_idx is not None:
            self.all_config_data['script_list'].pop(s_idx)

        self.scroll_layout.removeWidget(item)
        item.deleteLater()

        self._save_script_order()
        self._persist_ui_state()

    def _add_script(self):
        """弹出新增脚本对话框，确认后把脚本追加到列表底部并持久化"""
        existing = [it.display_name for it in self.script_items]
        dialog = AddScriptDialog(existing_names=existing, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._append_script(dialog.result_data)

    def _append_script(self, script_data):
        """把新脚本条目追加到 config 数据与 UI 列表底部并持久化（无对话框，供测试复用）"""
        self.all_config_data['script_list'].append(script_data)

        item = self._create_script_item(script_data, None)
        self.script_items.append(item)

        self._relayout_script_widgets()
        self._save_script_order()
        self._persist_ui_state()

    def _save_script_order(self):
        """把当前脚本顺序写回 config.yml"""
        config_path = get_config_yml_path_under_root()
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.all_config_data, f, allow_unicode=True, sort_keys=False)

    def _generate_config(self, chain_name="88"):
        """生成 ScriptChainer 配置文件（仅含启用的脚本）"""
        # 每周超时
        weekly_timeouts = {}
        weekly_path = get_weekly_timeouts_yml_path_under_root()
        if os.path.exists(weekly_path):
            with open(weekly_path, encoding='utf-8') as f:
                weekly_timeouts = yaml.safe_load(f) or {}

        # 收集每个启用脚本的副本选择、序列选择
        enabled_dungeons = {}
        enabled_sequences = {}
        for item in self.script_items:
            if item.enabled:
                dungeon = item.get_selected_dungeon()
                if dungeon:
                    enabled_dungeons[item.display_name] = dungeon
                seq = item.get_sequence()
                if seq is not None:
                    enabled_sequences[item.display_name] = seq

        enabled_names = {i.display_name for i in self.script_items if i.enabled}

        data = copy.deepcopy(self.all_config_data)
        filtered = []
        for script in data['script_list']:
            name = script['display_name']
            if name in enabled_names:
                apply_weekly_timeout(script, weekly_timeouts)

                # 外观模式：写入各脚本内部 config（副本、序列）
                dungeon = enabled_dungeons.get(name)
                seq = enabled_sequences.get(name)
                set_config(name, dungeon_name=dungeon, sequence=seq)

                filtered.append(script)

        data['script_list'] = filtered

        output_dir = get_path_under_onedragon("config", "script_chain")
        output_file = safe_path_join(output_dir, f"{chain_name}.yml")
        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

        return len(filtered)

    def _run_selected(self):
        enabled_count = sum(1 for i in self.script_items if i.enabled)
        if enabled_count == 0:
            QMessageBox.warning(self, "提示", "请至少开启一个脚本")
            return

        reply = QMessageBox.question(
            self, "确认运行",
            f"即将运行 {enabled_count} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._generate_config("88")

        self.run_btn.setEnabled(False)
        self.run_btn.setText("运行中...")

        self.runner = ScriptChainRunner("88")
        self.runner.finished_signal.connect(self._on_finished)
        self.runner.start()

    def _on_finished(self, return_code):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ 运行全部开启的脚本")

        if return_code == 0:
            QMessageBox.information(self, "完成", "所有脚本运行完成！")
        else:
            QMessageBox.warning(self, "提示", f"脚本运行结束，退出码: {return_code}")

    def _select_all(self):
        """全选所有脚本"""
        for item in self.script_items:
            if not item.enabled:
                item.enabled = True
                item._update_switch_style()

    def _deselect_all(self):
        """清空所有选择"""
        for item in self.script_items:
            if item.enabled:
                item.enabled = False
                item._update_switch_style()
