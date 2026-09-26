# src/update — 手动更新

集中助手本体的更新协议、服务、运行锁、安装事务和独立更新器，无 Qt 依赖。
GUI 弹窗和控制器留在 `src/gui`，通过 `AppService` 薄委托调用 `UpdateService`。
包导入不创建工作目录，也不检查或下载更新。

| 模块 | 职责 |
|------|------|
| service.py | 本地状态、显式检查稳定 Release、下载校验与安装交接 |
| package.py | 清单、哈希、路径校验及本地/远端 ZIP 共用的流式解包 |
| remote.py | remotezip 入口、HTTP 响应校验与分块取消 |
| runtime.py | 安装目录运行锁、更新闸门、同目录进程识别 |
| installer.py | 程序文件替换、持久化恢复记录及失败回滚 |
| __main__.py | 独立更新器入口；等待调用进程退出，执行安装/恢复并记录结果 |

`tools/release_package.py` 共用 `package.py`；`src/bootstrap.py` 在导入 Qt 前取得运行锁。
更新器由 `deploy/OneDragon-Helper-Updater.spec` 从 `__main__.py` 打成独立 onefile EXE。
源码调试入口为 `python -m src.update --help`，安装/恢复仅用于独立测试副本。
对应测试位于 `tests/update/`；GUI 和 Windows EXE 集成测试分别保留在原目录。

## 手动更新内核

`AppService.check_update()` 只在显式调用时请求当前仓库的最新稳定 Release；
`prepare_update()` 下载 ZIP 与 SHA-256，校验清单及每个文件后返回 `PreparedUpdate`。
构造服务和正常启动不联网。源码运行、开发构建、缺少清单的旧发布版不支持原位更新，
须先手动安装带清单和更新器的正式版本。

下载优先走增量（见下），只在远端不支持 HEAD/范围读取或 ZIP 目录损坏时回退整包下载。
两条路径产出的都是同一份完整程序目录。

### 增量下载

发布侧无需额外产物：用 HTTP 范围请求读同一个发布 ZIP 的中央目录，取出其中的新版
`update-manifest.json`，与本地实际文件 SHA-256 比对，只下载变化、缺失或损坏
条目的压缩数据，其余文件从当前安装复制补齐。因此整包 SHA-256 不再参与校验，
改由清单里的逐文件 SHA-256 覆盖；
新增与退役文件由安装事务按新旧清单处理。

`remotezip==0.12.6` 原生处理 HEAD、Range、重定向、随机读取和缓存；通过
`RemoteZip.open()` 逐文件流式读取，ZIP 格式与解压校验由标准库 `zipfile` 处理。
禁用 suffix Range 并开启 HEAD 重定向，兼容 GitHub 发布附件。网络库仅在显式更新时加载。
`remote.py` 只在 requests 响应钩子中校验状态与范围，使用标准库 `BufferedReader`
包装网络流，每次最多读取 64 KiB 并检查取消；不自写 fetcher、seek 或条目缓存。

本地 ZIP 与远端 `RemoteZip` 都交给 `unpack_package()`，共用条目边界、清单解析、
路径校验和写盘流程。远端模式传入当前安装目录，只复制哈希一致的文件，其余逐文件
分块写入新目录；不在内存里收集全部变化文件。最终复用 `load_manifest(verify=True)`
统一验证下载和复制结果，也覆盖复制期间源文件变化。安装目录在准备阶段保持原状。

增量进度按变化文件的解压字节统计，缓存命中同样推进，不再计算 ZIP 偏移或网络区间总量。
复制、解包和准备完成时检查取消；取消后清理本次工作目录。请求按条目读取，不合并相邻区间。

远端不支持 HEAD/范围请求或 ZIP 目录损坏时抛 `RemoteUnavailable`，由服务回退整包下载。
HTTP 错误、错误范围、传输中断、非法包路径、清单或文件校验失败直接报错，避免重复下载。

`start_update()` 从当前安装复制独立 onefile 更新器，等待它取得启动闸门后才返回。
调用方收到返回值应立即退出窗口；更新器等待父进程退出并取得独占运行锁，
再检查同目录 GUI / CLI / Runner 进程，不终止既有任务。冻结入口 `bootstrap.py`
在导入 Qt 和初始化配置前持有共享运行锁，覆盖 GUI、每日计划和其他 CLI 出口。

安装只替换新旧程序清单拥有的文件，删除退役程序文件，保留清单外文件。
新程序路径与未知已有文件冲突时拒绝更新。替换前将旧程序快照和事务记录写入
`.update/`；失败恢复旧版。异常退出留下的 `installing` 记录会阻止启动混合版本，
可用 `.update/download-*/worker-*/OneDragon-Helper-Updater.exe --root "安装目录" --recover`
恢复后重新启动。该路径须选取实际存在的工作进程副本；快照损坏会明确报错并保留现场。
工作包、日志和程序快照保留在 `.update/`，不触碰用户备份目录，不进入下一次发布包。

安装成功重启时带 `--after-update`，只跳过本次启动倒计时，不修改用户的启动设置。
结果写入 `start_update()` 返回的 JSON 路径，同时保存在 `.update/result.json`
（installed / failed / restart_failed / recovered）；`get_update_info()` 只读取本地版本、
支持状态和上次结果，不创建工作目录、不联网。
安装失败会恢复文件，但不会自动重启应用。更新器负责安装故障回滚，不判断新版业务功能是否正常。
GUI 经配置面板中的更新按钮显式调用这些接口，工作线程就绪后退出窗口。
