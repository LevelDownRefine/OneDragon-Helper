# python-backend/src/update — 手动更新

集中助手本体的更新协议、服务、运行锁、安装事务和独立更新器，无 Qt 依赖。
GUI 弹窗和控制器留在 `python-gui/src/gui`，通过 `AppService` 薄委托调用 `UpdateService`。
包导入不创建工作目录，也不检查或下载更新。

| 模块 | 职责 |
|------|------|
| service.py | 本地状态、显式检查稳定 Release、下载校验与安装交接；UpdateSession 保留 CLI 会话状态 |
| package.py | 清单、哈希、路径校验及本地/远端 ZIP 共用的流式解包 |
| remote.py | remotezip 入口、HTTP 响应校验、分块取消与按区间的断点缓存 |
| runtime.py | 安装目录运行锁、更新闸门、同目录进程识别 |
| installer.py | 程序文件替换、持久化恢复记录及失败回滚 |
| __main__.py | 独立更新器入口；等待调用进程退出，执行安装/恢复并记录结果 |

`tools/release_package.py` 共用 `package.py`；`python-gui/src/gui/bootstrap.py` 在导入 Qt 前取得运行锁。
更新器由 `deploy/OneDragon-Helper-Updater.spec` 从 `__main__.py` 打成独立 onefile EXE。
源码调试入口为 `uv run --directory python-backend python -m src.update --help`，安装/恢复仅用于独立测试副本。
对应测试位于 `python-backend/tests/update/`；GUI 和 Windows EXE 集成测试分别保留在原目录。

## 手动更新内核

`AppService.check_update()` 只在显式调用时请求当前仓库的最新稳定 Release；
`prepare_update()` 下载 ZIP 与 SHA-256，校验清单及每个文件后返回 `PreparedUpdate`。
构造服务和正常启动不联网。源码运行、开发构建、缺少清单的旧发布版不支持原位更新，
须先手动安装带清单和更新器的正式版本。

下载优先走增量（见下），只在远端不支持 HEAD/范围读取或 ZIP 目录损坏时回退整包下载。
两条路径产出的都是同一份完整程序目录。

Qt 与 Rust 使用不同发布附件：`OneDragon-Helper.zip` 与
`OneDragon-Helper-Rust.zip`，分别附带同名 `.sha256`。Rust 的清单和 `version.json`
须声明 `frontend: "rust"`；未声明的旧包按 Qt 处理。Rust 包要求独立的
`OneDragon-Helper-CLI.exe`，不要求 QML；两类包都沿用同一安装事务与更新器。
检查、下载、安装交接和事务入口均校验包类型，禁止在线跨类型替换。
原 Qt `AppService` 接口保持 Qt 类型，无 Qt 更新会话固定选择 Rust 类型。
`UpdateSession` 与更新内核同处 `service.py`，使用 `utils_job.JobExecutor` 执行耗时操作；
执行器只管理线程、进度与结果，不导入更新业务。`UpdateCancelled` 同时属于标准
`CancelledError`，让下载取消沿用更新异常处理并被执行器识别为取消状态。
发布附件名和清单校验先于 Rust 打包接入；缺少 Rust 附件时明确报错，不回退下载 Qt 包。

### 增量下载

发布侧无需额外产物：用 HTTP 范围请求读同一个发布 ZIP 的中央目录，取出其中的新版
`update-manifest.json`，与本地实际文件 SHA-256 比对，只下载变化、缺失或损坏
条目的压缩数据，其余文件从当前安装复制补齐。因此整包 SHA-256 不再参与校验，
改由清单里的逐文件 SHA-256 覆盖；
新增与退役文件由安装事务按新旧清单处理。

`remotezip==0.12.6` 原生处理 HEAD、Range、重定向、随机读取和 ZIP 缓存；通过
`RemoteZip.open()` 逐文件流式读取，ZIP 格式与解压校验由标准库 `zipfile` 处理。
禁用 suffix Range 并开启 HEAD 重定向，兼容 GitHub 发布附件。网络库仅在显式更新时加载。
`remote.py` 只在 requests 响应钩子中校验状态与范围，使用标准库 `BufferedReader`
包装网络流，每次最多读取 64 KiB 并检查取消；不自写 seek、解压或 ZIP 解析。
`ResumableFetcher` 接在 remotezip 的 `fetcher=` 扩展点上：范围请求由它自己发，
每次读到的字节按区间落盘，remotezip 再从磁盘补齐已收前缀。

本地 ZIP 与远端 `RemoteZip` 都交给 `unpack_package()`，共用条目边界、清单解析、
路径校验和写盘流程。远端模式传入当前安装目录，只复制哈希一致的文件，其余逐文件
分块写入新目录；不在内存里收集全部变化文件。目标目录允许已存在：哈希一致的条目视为
上次已下完，只补齐其余条目。最终复用 `load_manifest(verify=True)`
统一验证下载和复制结果，也覆盖复制期间源文件变化。安装目录在准备阶段保持原状。

增量进度按变化文件的解压字节统计，缓存命中同样推进，续传跳过的字节先计入已完成，
不再计算 ZIP 偏移或网络区间总量。复制、解包和准备完成时检查取消；取消后保留工作目录。

远端不支持 HEAD/范围请求或 ZIP 目录损坏时抛 `RemoteUnavailable`，由服务回退整包下载。
HTTP 错误、错误范围、非法包路径、清单或文件校验失败直接报错，避免重复下载；
网络错误与读取中断属于可重试失败，保留断点。请求按条目读取，不合并相邻区间。

### 断点续传

工作目录固定为 `.update/download-v<版本>/`，下载期间持有 `.update/download.lock`，
进入时清掉其他版本的残留目录。可重试的失败（网络错误、取消、读流提前结束）保留
工作目录，只有确定性失败（清单非法、路径越界、校验不符）才清掉，因此下一次
`prepare_update()` 只补缺口。界面上的「暂停下载」即取消，断点留在磁盘上。

增量路径的续传粒度就是一个区间：remotezip 用 `RemoteIO._get_position_to_size` 把每个
成员切成互不重叠的 `[header_offset, 下一个 header_offset)`，每个区间只发一次流式请求。
`ResumableFetcher` 把这些字节按 `<起>-<止>.bin` 落盘，文件长度就是进度，不需要额外账本；
重跑时先回放已收前缀，再从缺口处续请求。远端大小或 ETag/Last-Modified 变化时清空缓存，
远端不提供标识时一律重来，避免混用两次发布的字节。

全量回退路径按整包已有长度发 `Range`，服务器不支持续传时自动从头重下，收满后仍由整包
SHA-256 决定复用还是丢弃。两条路径的完整性都落在最后一步的逐文件校验上，所以续传错位
只会变成校验失败并重下，不会装出混合版本。

`start_update()` 从当前安装复制独立 onefile 更新器，等待它取得启动闸门后才返回。
调用方收到返回值应立即退出窗口；更新器等待父进程退出并取得独占运行锁，
再检查同目录 GUI / CLI / Runner 进程，不终止既有任务。冻结入口 `bootstrap.py`
在导入 Qt 和初始化配置前持有共享运行锁，覆盖 GUI、每日计划和其他 CLI 出口。

Rust 从独立 CLI 会话交接：服务检查当前 CLI 和直接父进程的安装路径，
只将这两个进程排除在“其他任务”检查外。更新器接收双方 PID/创建时间，再次核对
可执行路径及父子关系；写出 ready 后在同一个 30 秒期限内等待双方退出，
取得独占运行锁后重新扫描同目录进程才安装。身份变化或仍未退出会记录失败，
不终止窗口或运行任务。安装交接不可取消；RPC 只引用服务内部已校验的包，
不接受客户端指定 PID、可执行文件或包路径。GUI 仅在匹配版本的 ready 回执后退出。

安装只替换新旧程序清单拥有的文件，删除退役程序文件，保留清单外文件。
新程序路径与未知已有文件冲突时拒绝更新。替换前将旧程序快照和事务记录写入
`.update/`；失败恢复旧版。异常退出留下的 `installing` 记录会阻止启动混合版本，
可用 `.update/download-v*/worker-*/OneDragon-Helper-Updater.exe --root "安装目录" --recover`
恢复后重新启动。该路径须选取实际存在的工作进程副本；快照损坏会明确报错并保留现场。
工作包、日志和程序快照保留在 `.update/`，不触碰用户备份目录，不进入下一次发布包。

安装成功重启时带 `--after-update`，只跳过本次启动倒计时，不修改用户的启动设置。
结果写入 `start_update()` 返回的 JSON 路径，同时保存在 `.update/result.json`
（installed / failed / restart_failed / recovered）；`get_update_info()` 只读取本地版本、
支持状态和上次结果，不创建工作目录、不联网。
安装失败会恢复文件，但不会自动重启应用。更新器负责安装故障回滚，不判断新版业务功能是否正常。
GUI 经配置面板中的更新按钮显式调用这些接口，工作线程就绪后退出窗口。
