"""主窗口：脚本列表、增删/重排/持久化、生成 ScriptChainer 配置并运行。"""

import logging
import os
import time

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
        # MainWindow 构造耗时打点基准：__init__ 入口归零，阶段差值为真实耗时
        self._init_t0 = time.perf_counter()
        self.setWindowTitle("OneDragon 脚本启动器")
        self.setMinimumSize(530, 800)

        self.script_items = []
        self.all_config_data = None
        self.runner = None
        self.service = service or ChainService()
        self._script_service = script_service or ScriptService()
        self._ui_state = self.service.load_ui_state()
        self._log_init("load_ui_state")

        self._init_ui()
        self._log_init("_init_ui")
        self._load_scripts()
        self._log_init("_load_scripts")

    def _log_init(self, stage: str) -> None:
        """记录 MainWindow 构造阶段耗时：相对 __init__ 入口的毫秒数（供启动性能分析）。"""
        elapsed_ms = (time.perf_counter() - self._init_t0) * 1000
        logger.info("[startup]   MainWindow.%-24s %8.1f ms", stage, elapsed_ms)

    def _init_ui(self):
        central = QWidget()
        central.setStyleSheet("background-color: #eef1f6;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)
        self._central_layout = layout  # 供 _load_scripts 末尾挂载 scroll

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
        # 挂载延迟到 _load_scripts 末尾（卡片插满后再 setWidget+addWidget）：
        # widgetResizable=True 时，若先挂载再逐卡插入，每次插入都触发 viewport
        # 重算，show() 时一次性爆发，拖慢启动（实测 400ms→120ms，见 2026-08-08）。
        self._scroll = scroll

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
            display_name = data["display_name"]
            item_t0 = time.perf_counter()
            dungeon_cfg = self.dungeon_map.get(
                display_name
            )  # optional: 不是所有脚本都有副本配置
            _, seq_map, _ = parse_dungeon_config(dungeon_cfg)

            saved = self._ui_state.get(
                display_name
            )  # optional: 新脚本可能没有保存的状态
            if saved:
                saved = restore_sequence_type(saved, seq_map)
            item = self._create_script_item(data, saved)
            self.scroll_layout.insertWidget(len(self.script_items), item)
            self.script_items.append(item)
            item_ms = (time.perf_counter() - item_t0) * 1000
            logger.info(
                "[startup]     构造 ScriptItem %-8s %8.1f ms", display_name, item_ms
            )
        # 卡片插满后再统一挂载 scroll（见 _init_ui 说明）：避免逐卡插入触发
        # widgetResizable viewport 反复重算。布局顺序：scroll 需位于按钮区之前。
        self._scroll.setWidget(self.scroll_content)
        self._central_layout.insertWidget(0, self._scroll, stretch=1)

    def _create_script_item(self, data, saved_state):
        """构造 ScriptItem 并注入 UI 状态回调"""
        display_name = data["display_name"]
        dungeon_cfg = self.dungeon_map.get(
            display_name
        )  # optional: 不是所有脚本都有副本配置
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
        """收集所有脚本的 UI 状态并保存。

        同步更新内存态 self._ui_state：_generate_config 运行时读的是这个实例
        变量，若只写盘不更新内存，用户改了副本选择后直接运行会用到过期状态。
        """
        state = {}
        for item in self.script_items:
            state[item.display_name] = item.get_state()
        self._ui_state = state
        self.service.save_ui_state(state)

    def _on_script_config_saved(self, pending_changes):
        """配置弹窗保存成功后：委托 ChainService 落盘 → 同步内存与卡片。

        弹窗不再自行写 config.yml（写入权统一归 ChainService）。此方法
        将表单数据委托给 ChainService，再重新加载 all_config_data 并
        同步对应 ScriptItem 卡片的内存态。config + weekly 在 service 层
        原子完成。
        """
        self.service.update_script(
            pending_changes["old_display_name"],
            pending_changes["new_display_name"],
            pending_changes["config_patch"],
            pending_changes["weekly_timeouts"],
        )

        # 服务层写盘后重新吸收，保持内存与磁盘一致
        self.all_config_data = self.service.load_config()

        # 同步对应 ScriptItem 卡片的内存态
        new_display_name = pending_changes["new_display_name"]
        for item in self.script_items:
            if item.display_name == new_display_name:
                new_data = next(
                    (
                        s
                        for s in self.all_config_data["script_list"]
                        if s["display_name"] == new_display_name
                    ),
                    None,
                )
                assert new_data is not None, (
                    f"[main_window] 保存后找不到脚本: {new_display_name}"
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
        """删除指定脚本（弹窗已确认）：UI 列表 + 内存 config + 总 config(ChainService, 含 weekly 清理)。"""
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

        # config.yml + weekly_timeouts 都由 ChainService 内部处理
        self.service.remove_script(display_name)
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

        config.yml + weekly_timeouts 都由 ChainService 内部处理，GUI 只负责
        UI 列表与内存同步。
        """
        self.all_config_data["script_list"].append(script_data)
        item = self._create_script_item(script_data, None)
        self.script_items.append(item)

        self._relayout_script_widgets()
        self.service.add_script(script_data)
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
        enabled_scripts = []
        for script in self.all_config_data["script_list"]:
            assert "display_name" in script, (
                "[main_window] 脚本配置缺少 display_name 字段"
            )
            if script["display_name"] in enabled_names:
                enabled_scripts.append(script)
        invalid = self.service.collect_invalid_scripts(enabled_scripts)
        if not invalid:
            return True
        details = "\n".join(f"· {script_name}：{msg}" for script_name, msg in invalid)
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
