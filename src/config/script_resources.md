# 脚本资源声明

`config/script_resources.yml` 保存随助手发布的脚本资源位置。`script_resources.py`
只负责读取、校验和提供不可变数据；配置适配器、日志解析器与链接查询共用这份声明。
它不导入 GUI，也不实例化 `ScriptConfig`，可供 Python CLI 和后续 Rust 实现使用。

## 声明边界

- 脚本级资源：备份范围、游戏路径所在配置及键路径、默认背景图、初始化模板、日志目录、官网/B 站/GitHub 链接。
- 日常、周常和任务开关的文件路径继续由各自的 `daily_task_list.yml`、`weekly_task_list.yml`、`task_switch_list.yml` 持有，不另建一层路径别名。
- 用户机器上的安装路径仍保存在用户配置或脚本原生配置中；手填 `game_path` 仍优先。
- 文件读写、模板合并、游戏启动器搜索、日志解析规则仍由 Python 机制类实现。YAML 不包含可执行表达式。

## 格式与路径基准

顶层 `version: 1`，`scripts` 以全链路 `script_name` 为键。示例：

```yaml
version: 1
scripts:
  ok-ef:
    backup_paths:
      - data/apps/ok-ef/working/configs
    game:
      config: data/apps/ok-ef/working/configs/devices.json
      keys: [pc_full_path]
    logs:
      root: temp
      path: ok-ef/日常任务
    links:
      homepage: https://endfield.hypergryph.com/
      bilibili: https://space.bilibili.com/1265652806
      github: https://github.com/AliceJump/ok-end-field
```

| 字段 | 含义与基准 | 省略时 |
|---|---|---|
| `backup_paths` | 相对脚本根目录的文件或目录列表 | 必填，非空且不重复 |
| `game.config` / `game.keys` | 相对脚本根目录的配置文件，以及逐层读取游戏路径的键列表 | 省略整个 `game` 表示不反读游戏路径；声明时两项均必填 |
| `game.launcher` | 启动器相对路径；异环机制用它逐层向上查找 | 通用读取不需要；异环机制要求声明 |
| `background` | 相对脚本根目录的默认背景图 | 无脚本默认图，沿用界面回退规则 |
| `template` | 相对助手 `config/` 的初始化模板文件 | 不做通用模板对齐 |
| `logs.root` / `logs.path` | 根目录 `script`（脚本所在目录）或 `temp`（系统临时目录），加相对目录 | 无日志位置声明；有解析器的脚本必须声明 |
| `links` | 完整的 `homepage`、`bilibili`、`github` HTTP(S) URL | 三项均必填 |

路径统一用 `/` 分隔，不允许绝对路径、盘符、`..`、空段或变量插值。
不检查目标文件是否已安装；声明格式正确与本机资源存在是两件事。
链接必须完整，不能携带用户名或密码。未知字段、缺少必填项、重复 YAML 键和不支持的版本直接报错。

## 消费与扩展

`get_script_resources(script_name)` 返回不可变 `ScriptResources`；未声明脚本返回 `None`。
已注册的 `ScriptConfig` 必须有声明，注册时即校验并绑定 `resources`。
`get_game_exe_path`、`iter_backup_paths`、`get_background_rel_path`、`get_game_link`
和日志模块的公开接口保持不变；`ScriptConfig` 的构造与初始化时机也保持不变。

修改已支持脚本的目录布局或链接，只改声明并验证对应行为；新增脚本仍需注册适配器，
有特殊机制或日志格式时再添加对应 Python 实现。声明不能凭空提供新机制。

加载器按声明文件位置缓存，只读一次，修改后重启生效。它是版本管理的内置资源，
不提供用户覆盖文件或热加载；用户安装目录不写入此文件。
路径通过 `get_root_dir()` 定位，打包后从 EXE 同级的 `config/` 读取。
发布工具自动收集 Git 跟踪的 `config/` 文件，更新器按程序资源替换此文件；
因此新增声明必须提交到 Git。发布文件缺失或损坏时直接报错，不回退到 Python 硬编码。
