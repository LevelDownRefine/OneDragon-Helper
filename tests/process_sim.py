"""清理类测试共用的进程表模拟：按脚本配置生成「启动器真身 + 各自的游戏 + 无关进程」。

真机残留形态（对照 config.yml 的 ok 系列条目）——一次链运行结束后留在系统里的进程：
- 启动器本体（脚本 exe）通常已退出；
- 启动器拉起的**真身**仍在：进程名是通用解释器（多个脚本共用 pythonw.exe），
  只能靠命令行里的安装根目录认出；
- **游戏**仍在：进程名各游戏不同（也有两个脚本共用同一游戏的，如 ok-ef 与 MAS
  同为 Endfield.exe），由脚本拉起，脚本先退出时则成为孤儿；
- 还有大量无关进程：没纳入 config 的脚本（进程名同样是 pythonw.exe）、系统进程等，
  清理时不得误伤。

本模块按此形态造一张进程表并挂到 ``src.utils_runner.psutil`` 上，让
``close_running_scripts`` 这类「按配置扫进程再杀」的逻辑跑在贴近真机的输入上：
进程名 / 命令行 / 父子关系全部由脚本配置推导，而非各测试各自手写。

路径一律用 Windows 形态（``D:\\...``）：``collect_process_targets`` 内部按
``PureWindowsPath`` 解析，与测试所在平台无关，写成 Windows 形态才对得上真机配置。
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest import mock


class SimProcess:
    """模拟 psutil.Process：pid/ppid/name()/cmdline() 可预设，记录 terminate/kill。

    pid 取高位段，避免与真实的「本进程及祖先」PID 集合撞上导致误排除。
    ppid 经 ``info`` 暴露，对齐 psutil ``process_iter(attrs)`` 的取值方式——
    子进程树据此一次建表得出，不再逐个调 ``children()``（那是每进程一遍全量遍历）。
    """

    _next_pid = 900000

    def __init__(self, name: str, cmdline: list[str] | None = None, parent=None):
        SimProcess._next_pid += 1
        self.pid = SimProcess._next_pid
        self._name = name
        self._cmdline = cmdline or []
        self.ppid = parent.pid if parent is not None else None
        self.info = {"pid": self.pid, "ppid": self.ppid}
        self.terminated = False
        self.killed = False
        self.cmdline_calls = 0

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        self.cmdline_calls += 1
        return self._cmdline

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class ProcessSim:
    """一次链运行结束后的进程表：每个脚本一个真身 + 一个由它启动的游戏。

    Attributes:
        scripts: 由 add_script 推导出的 config.yml 形态脚本条目列表。
        bodies: 脚本标识 -> 启动器真身进程（多脚本共用 ``body_name``）。
        games: 脚本标识 -> 该脚本启动的游戏进程。
        processes: 完整进程表（含无关进程），供 install 后扫描。
    """

    def __init__(
        self,
        *,
        install_root: str = r"D:\game_helper",
        body_name: str = "pythonw.exe",
    ) -> None:
        self.install_root = install_root
        self.body_name = body_name
        self.scripts: list[dict] = []
        self.bodies: dict[str, SimProcess] = {}
        self.games: dict[str, SimProcess] = {}
        self.processes: list[SimProcess] = []
        # 按游戏进程名索引：同一时刻一个游戏只有一个进程，故两个脚本配了同一
        # 游戏（真机上的 ok-ef 与 MAS 同为 Endfield.exe）时共用同一个进程。
        self._game_procs: dict[str, SimProcess] = {}

    def add_script(
        self,
        key: str,
        *,
        game_name: str | None = None,
        launcher: str | None = None,
        orphan_game: bool = False,
    ) -> None:
        """登记一个脚本：生成其 config 条目、启动器真身进程与它启动的游戏进程。

        Args:
            key: 脚本唯一标识，同时作为安装目录名。
            game_name: 游戏进程名；缺省 ``<key>Game.exe``。两个脚本传同一个名字即
                模拟「共用同一游戏」（真机上的 ok-ef 与 MAS 同为 Endfield.exe）。
            launcher: 启动器本体文件名（``script_path`` 末段）；缺省 ``<key>.exe``。
            orphan_game: True 表示脚本已退出、游戏成为孤儿（非真身子进程）。
        """
        root = f"{self.install_root}\\{key}"
        game = game_name or f"{key}Game.exe"
        body = SimProcess(
            self.body_name,
            cmdline=[f"{root}\\python\\pythonw.exe", f"{root}\\working\\main.py"],
        )
        self.processes.append(body)
        self.bodies[key] = body
        # 游戏命令行刻意不含脚本安装根目录：它只能靠进程名认出，
        # 否则真身的 cmdline 条件会顺带命中游戏，掩盖「按名匹配」是否真的生效。
        if game not in self._game_procs:
            self._game_procs[game] = SimProcess(
                game,
                cmdline=[f"C:\\Games\\{key}\\{game}"],
                parent=None if orphan_game else body,
            )
            self.processes.append(self._game_procs[game])
        self.games[key] = self._game_procs[game]
        self.scripts.append(
            {
                "display_name": key,
                "script_path": f"{root}\\{launcher or key + '.exe'}",
                "script_process_name": [],
                "game_process_name": game,
            }
        )

    def add_other(
        self,
        name: str,
        cmdline: list[str] | None = None,
        parent: SimProcess | None = None,
    ) -> SimProcess:
        """登记一个不被任何脚本配置匹配的进程（无关脚本 / 系统进程）。

        Args:
            name: 进程名。
            cmdline: 命令行；缺省为空（不匹配任何 cmdline 条件）。
            parent: 非空时挂在该进程树下——用于验证「虽不匹配，但被树杀连带」。

        Returns:
            新建的模拟进程，供调用方断言其是否被误杀。
        """
        proc = SimProcess(name, cmdline, parent=parent)
        self.processes.append(proc)
        return proc

    @contextmanager
    def install(self) -> Iterator["ProcessSim"]:
        """把模拟进程表挂到 ``src.utils_runner.psutil`` 上（process_iter / wait_procs）。"""
        with ExitStack() as stack:
            # side_effect 而非 return_value：匹配与建树各遍历一次，需每次返回新迭代器。
            stack.enter_context(
                mock.patch(
                    "src.utils_runner.psutil.process_iter",
                    side_effect=lambda *a, **k: iter(list(self.processes)),
                )
            )
            stack.enter_context(
                mock.patch(
                    "src.utils_runner.psutil.wait_procs", side_effect=self._wait_procs
                )
            )
            yield self

    @staticmethod
    def _wait_procs(procs, timeout: float | None = None) -> tuple[list, list]:
        """已 terminate/kill 的视为已退出，其余仍存活（供强制 kill 分支判定）。"""
        gone = [p for p in procs if p.terminated or p.killed]
        return gone, [p for p in procs if p not in gone]
