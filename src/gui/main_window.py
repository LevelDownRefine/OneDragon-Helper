"""主窗口：脚本列表、增删/重排/持久化、生成 ScriptChainer 配置并运行。"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
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
    parse_dungeon_config,
    restore_sequence_type,
)
from src.gui.runner import ScriptChainRunner
from src.gui.utils import make_pill_button, safe_startfile
from src.gui.widgets import ScriptItem
from src.service.chain_service import ChainService
from src.service.script_service import ScriptService
from src.utils import get_config_yml_path_under_root

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, service=None, script_service=None):
        super().__init__()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(600, 800)

        self.script_items = []
        self.all_config_data = None
        self.runner = None
        self.service = service or ChainService()
        self._script_service = script_service or ScriptService()
        self._ui_state = self.service.load_ui_state()

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

        self.select_all_btn = make_pill_button(
            "一键全选", accent="#3b82f6", pressed_bg="#f0f4ff"
        )
        self.select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = make_pill_button(
            "清空选择", accent="#ef4444", pressed_bg="#fef2f2"
        )
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(self.deselect_all_btn)

        self.add_script_btn = make_pill_button(
            "添加脚本", accent="#22c55e", hover_color="#16a34a", pressed_bg="#f0fdf4"
        )
        self.add_script_btn.clicked.connect(self._add_script)
        action_layout.addWidget(self.add_script_btn)

        # 打开配置：直接打开 config.yml（get_config_yml_path_under_root）
        self.open_config_btn = make_pill_button(
            "打开配置", accent="#8b5cf6", hover_color="#7c3aed", pressed_bg="#f1ecfb"
        )
        self.open_config_btn.clicked.connect(self._open_config_yml)
        action_layout.addWidget(self.open_config_btn)

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
        self.all_config_data = self.service.load_config()

        self.dungeon_map = self.service.dungeon_map()

        for item in self.script_items:
            item.deleteLater()
        self.script_items.clear()

        for data in self.all_config_data["script_list"]:
            name = data["display_name"]
            dungeon_cfg = self.dungeon_map.get(
                name
            )  # optional: 不是所有脚本都有副本配置
            _, seq_map, _ = parse_dungeon_config(dungeon_cfg)

            saved = self._ui_state.get(name)  # optional: 新脚本可能没有保存的状态
            if saved:
                saved = restore_sequence_type(saved, seq_map)
            item = self._create_script_item(data, saved)
            self.scroll_layout.insertWidget(len(self.script_items), item)
            self.script_items.append(item)

    def _create_script_item(self, data, saved_state):
        """构造 ScriptItem 并注入 UI 状态回调"""
        name = data["display_name"]
        dungeon_cfg = self.dungeon_map.get(name)  # optional: 不是所有脚本都有副本配置
        options, seq_map, show_seq = parse_dungeon_config(dungeon_cfg)
        item = ScriptItem(
            data,
            dungeon_options=options if options else None,
            sequence_options_map=seq_map if show_seq else None,
            show_sequence=show_seq,
            saved_state=saved_state,
            reorder_callback=self._reorder_scripts,
            delete_callback=self._delete_script,
            config_saved_callback=self._on_script_config_saved,
            script_service=self._script_service,
        )
        item.set_state_callback(self._persist_ui_state)
        return item

    def _persist_ui_state(self):
        """收集所有脚本的 UI 状态并保存"""
        state = {}
        for item in self.script_items:
            state[item.display_name] = item.get_state()
        self.service.save_ui_state(state)

    def _on_script_config_saved(self, display_name):
        """配置弹窗保存成功后：重新从磁盘加载 all_config_data 并同步对应卡片的内存路径。

        原因：配置弹窗直接改写磁盘上的 config.yml，但 MainWindow 的 all_config_data
        是内存副本。若不重新吸收，后续 _generate_config（运行）或 _save_script_order
        （重排/增删）会基于旧的 in-memory 副本把刚保存的路径覆盖掉，表现为「保存失效」。
        """
        self.all_config_data = self.service.load_config()
        for item in self.script_items:
            if item.display_name == display_name:
                new_data = next(
                    (
                        s
                        for s in self.all_config_data["script_list"]
                        if s["display_name"] == display_name
                    ),
                    None,
                )
                assert new_data is not None, (
                    f"[main_window] 保存后找不到脚本: {display_name}"
                )
                item.sync_from_script_data(new_data)
                break

    def _reorder_scripts(self, src_name, dst_name):
        """把 src_name 对应的脚本移动到 dst_name 所在位置，并同步 UI 与 config.yml"""
        script_items = self.script_items
        src_idx = next(
            (i for i, it in enumerate(script_items) if it.display_name == src_name),
            None,
        )
        assert src_idx is not None, f"[main_window] 拖拽源脚本不存在: {src_name}"
        dst_idx = next(
            (i for i, it in enumerate(script_items) if it.display_name == dst_name),
            None,
        )
        assert dst_idx is not None, f"[main_window] 拖拽目标脚本不存在: {dst_name}"
        item = script_items.pop(src_idx)
        script_items.insert(dst_idx, item)

        # 同步 config.yml 中的顺序（以 UI 顺序为准）
        scripts = self.all_config_data["script_list"]
        s_idx = next(
            (i for i, s in enumerate(scripts) if s["display_name"] == src_name), None
        )
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
            self,
            "确认删除",
            f"确定要删除脚本「{display_name}」吗？\n将从启动器移除并保存到 config.yml。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._remove_script(display_name)

    def _remove_script(self, display_name):
        """实际移除逻辑（无确认）"""
        idx = next(
            (
                i
                for i, it in enumerate(self.script_items)
                if it.display_name == display_name
            ),
            None,
        )
        if idx is None:
            return
        item = self.script_items.pop(idx)

        s_idx = next(
            (
                i
                for i, s in enumerate(self.all_config_data["script_list"])
                if s["display_name"] == display_name
            ),
            None,
        )
        if s_idx is not None:
            self.all_config_data["script_list"].pop(s_idx)

        self.scroll_layout.removeWidget(item)
        item.deleteLater()

        self._save_script_order()
        self._persist_ui_state()

    def _add_script(self):
        """弹出文件选择框，选完后自动以文件名作为显示名称追加到列表底部并持久化。

        无需额外弹窗填写字段，默认字段（check_done / kill_game_after_done 等）
        已对齐 ScriptChainer 校验规则；用户后续可点击「配置」按钮自行调整。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择脚本文件",
            "",
            "可执行文件 Executable files (*.exe *.bat *.py);;所有文件 All files (*.*)",
        )
        if not file_path:
            return

        file_path = os.path.normpath(file_path)
        existing = {it.display_name for it in self.script_items}
        script_data = self._script_service.build_script_entry(file_path, existing)
        self._append_script(script_data)

    def _append_script(self, script_data):
        """把新脚本条目追加到 config 数据与 UI 列表底部并持久化。

        同时自动在 weekly_timeouts.yml 里为该脚本创建 7 格默认超时条目，
        使首次运行即可使用统一的 DEFAULT_RUN_TIMEOUT，无需用户手动配置。
        """
        self.all_config_data["script_list"].append(script_data)

        # 自动创建 weekly_timeouts 默认条目
        self._script_service.ensure_weekly_entry(script_data["display_name"])

        item = self._create_script_item(script_data, None)
        self.script_items.append(item)

        self._relayout_script_widgets()
        self._save_script_order()
        self._persist_ui_state()

    def _open_config_yml(self):
        """打开 config.yml（用系统默认程序打开文本文件）；缺失/异常时给出清晰提示。"""
        safe_startfile(self, get_config_yml_path_under_root(), "无法打开配置文件")

    def _save_script_order(self):
        """把当前脚本顺序写回 config.yml"""
        self.service.save_config(self.all_config_data)

    def _generate_config(self, chain_name="88"):
        """生成 ScriptChainer 配置文件（仅含启用的脚本）"""
        enabled_names = {i.display_name for i in self.script_items if i.enabled}
        return self.service.generate_chain(
            self.all_config_data, enabled_names, chain_name, self._ui_state
        )

    def _warn_if_invalid_scripts(self) -> bool:
        """运行前校验启用脚本配置合法性；有非法项时弹窗询问是否仍运行。

        返回 True 表示继续运行，False 表示用户取消。
        提前暴露「脚本配置不合法 跳过运行」类问题，避免脚本链跑完才发现
        某脚本被 runner 静默跳过（如自动关机未执行）。
        校验规则对齐 runner ``ScriptConfig.invalid_message``（见 src.utils_runner）。
        """
        enabled_names = {i.display_name for i in self.script_items if i.enabled}
        enabled_scripts = [
            s
            for s in self.all_config_data["script_list"]
            if s.get("display_name") in enabled_names
        ]
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if not invalid:
            return True
        details = "\n".join(f"· {name}：{msg}" for name, msg in invalid)
        reply = QMessageBox.warning(
            self,
            "脚本配置不合法",
            f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _run_selected(self):
        enabled_count = sum(1 for i in self.script_items if i.enabled)
        if enabled_count == 0:
            QMessageBox.warning(self, "提示", "请至少开启一个脚本")
            return

        if not self._warn_if_invalid_scripts():
            return

        reply = QMessageBox.question(
            self,
            "确认运行",
            f"即将运行 {enabled_count} 个脚本，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        chain_path = self._generate_config("88")

        self.run_btn.setEnabled(False)
        self.run_btn.setText("运行中...")

        self.runner = ScriptChainRunner(chain_path)
        self.runner.finished_signal.connect(self._on_finished)
        self.runner.start()

    def _on_finished(self, return_code):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ 运行全部开启的脚本")

        # 后台运行的脚本仍在后台执行，故只用「已处理」措辞，不强调「完成」。
        # 运行结果仅写日志，不再弹模态窗（避免阻塞 GUI）。
        if return_code == 0:
            logger.info("脚本链运行结束：已处理全部脚本（后台运行的脚本仍在后台执行）")
        else:
            logger.warning("脚本链运行结束，退出码: %s", return_code)

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
