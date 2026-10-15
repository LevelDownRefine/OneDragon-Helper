# 脚本资源声明

`config/script_resources.yml` 保存随助手发布的备份范围、游戏路径落点、背景和链接。`script_resources.py` 只读取、校验和缓存声明，不初始化或写入原生配置。

用户安装目录仍在用户配置或原生配置中，手填 `game_path` 优先；日常、周常、任务开关的落点留在各自声明。

## 格式

```yaml
version: 1
scripts:
  ok-ef:
    backup_paths:
      - data/apps/ok-ef/working/configs
    game:
      config: data/apps/ok-ef/working/configs/devices.json
      keys: [pc_full_path]
      launcher: Launcher.exe
    links:
      homepage: https://endfield.hypergryph.com/
      bilibili: https://space.bilibili.com/1265652806
      github: https://github.com/AliceJump/ok-end-field
```

| 字段 | 规则 |
| --- | --- |
| `scripts` 键 | 全链路 `script_name` |
| `backup_paths` | 必填、非空、不重复的相对文件或目录列表 |
| `game.config/keys` | 可省略整个 game；声明时须同时提供配置文件与键路径 |
| `game.launcher` | 相对安装目录的启动器路径；终末地/异环查注册表，异环保留从游戏目录向上查找的回退 |
| `background` | 可选默认背景相对路径 |
| `links` | 必含 homepage、bilibili、github 三个 HTTP(S) URL，不含凭据 |

除 `game.launcher` 外，路径相对脚本根目录，以 `/` 分隔，禁止绝对路径、盘符、`..`、空段和变量插值。校验格式，不检查目标是否安装；未知字段、重复 YAML 键、缺少必填项或不支持的版本直接报错。

## 使用

`get_script_resources(script_name)` 返回共享只读字典，未声明脚本返回 `None`；已注册适配器必须有声明。可选字段不补默认值，特殊机制仍由 Python 实现。

声明按文件位置缓存，修改后重启；不支持用户覆盖或热加载。源码经 `get_root_dir()` 定位，发布包从 EXE 同级 `config/` 读取。新增声明必须提交到 Git 才会被打包，缺失或损坏不回退硬编码。

日志位置另见 [日志声明](../log/README.md)。
