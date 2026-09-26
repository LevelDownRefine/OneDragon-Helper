# src/update — 手动更新

集中助手本体的更新协议、服务、运行锁、安装事务和独立更新器，无 Qt 依赖。
GUI 弹窗和控制器留在 `src/gui`，通过 `AppService` 薄委托调用 `UpdateService`。
包导入不创建工作目录，也不检查或下载更新。

| 模块 | 职责 |
|------|------|
| service.py | 本地状态、显式检查稳定 Release、下载校验与安装交接 |
| package.py | 构建和安装共用的程序清单、哈希与路径校验 |
| remote.py | 远端 ZIP 按需读取：范围请求取中央目录与变化条目 |
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

下载优先走增量（见下），只在远端不支持范围读取或结构异常时回退整包下载。
两条路径产出的都是同一份完整程序目录。

### 增量下载

发布侧无需额外产物：用 HTTP 范围请求读同一个发布 ZIP 的中央目录，取出其中的新版
`update-manifest.json`，与本地清单及实际文件 SHA-256 比对，只下载变化、缺失或损坏
条目的压缩数据，其余文件从当前安装复制补齐。因此整包 SHA-256 不再参与校验，
改由清单里的逐文件 SHA-256 覆盖；
新增与退役文件由安装事务按新旧清单处理。

远端随机读取、缓存及条目区间定位由 `remotezip` 负责，ZIP 格式与解压仍使用标准库
`zipfile`。依赖锁定为 `remotezip==0.12.6`，通过其 fetcher 扩展点接入分块下载，
校验 HTTP 状态、Content-Range 和实际长度。先探测大小与重定向地址，禁用 suffix Range，
避免部分 GitHub 发布附件拒绝后缀范围请求；网络库仅在显式更新时加载。

下载每 64 KiB 报告进度和检查取消，复制及准备完成后也检查取消；取消后清理本次工作目录。
进度总量按所选条目的 ZIP 区间大小计算，命中 remotezip 包尾缓存的条目直接计入完成。
请求复用同一连接，按条目读取，不合并相邻区间。

远端返回整包（不支持范围请求）、目录损坏、非 deflate 压缩或路径越界时抛
`RemoteUnavailable`，由 `prepare_update()` 回退全量；网络与校验失败不回退，避免重复下载。
HTTP 错误、范围响应位置不符、解压或哈希失败均直接报错，不误判为不支持范围请求。

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
