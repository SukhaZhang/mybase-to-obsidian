# mybase-to-obsidian

把 **myBase** 数据库迁移到 **Obsidian** 的两步脚本：插件导出 Markdown 中间格式 → Python 脚本生成 Vault。

- 🔌 **myBase 插件**（`mybase_export_plugin.js`）：读取 `.nyf`/`.leo` 数据库，导出为带 frontmatter 的 Markdown
- 🐍 **转换脚本**（`mybase2obsidian.py`）：HTML→Markdown、自动打标签、生成分类 MOC 索引
- 📦 **零第三方依赖**：只用 Python 标准库，任何有 Python 3 的机器都能跑

## 为什么需要它

myBase 是经典的个人知识库工具，但生态封闭、数据格式私有。Obsidian 用纯 Markdown + 本地文件夹，可迁移、可搜索、可同步。已有工具大多只能导出纯文本，**会丢掉：分类层级、源数据库信息、分类索引**。

这套脚本保留完整的知识结构：分类树变成文件夹树，每个分类自动生成 MOC（Map of Content）索引页，笔记带 tags 便于 Obsidian 检索。

## 快速开始

### 第一步：用 myBase 插件导出

1. 把 `mybase_export_plugin.js` 复制到 myBase 的插件目录（`myBase安装目录/plugins/`）
2. 在 myBase 中打开要导出的数据库
3. 菜单 **Share → Export database to Obsidian Markdown ...**
4. 选择导出目录（多个数据库可以导出到同一目录，每个数据库一个子目录）

导出结构：

```
mybase_export/
└── work/                      # 数据库名（自动取自 .nyf 文件名）
    ├── AI/
    │   ├── CUDA/
    │   │   └── index.md       # 笔记（frontmatter + HTML正文）
    │   └── _index.md          # 分类索引
    └── DevOps/
        └── index.md
```

### 第二步：转换成 Obsidian Vault

```bash
python mybase2obsidian.py <导出目录> <Vault目录>
```

示例（带目录重命名）：

```bash
python mybase2obsidian.py mybase_export MyVault --map work=工作 --map life=生活
```

完成后用 Obsidian 打开 `MyVault` 目录即可。

> 想先看效果？仓库自带示例数据，直接试跑：
> `python mybase2obsidian.py examples/sample_export demo_vault`

## 输出结构

```
MyVault/
├── _MOC_总索引.md              # 全部笔记的总入口
├── 工作/
│   ├── _MOC_工作.md            # 分类 MOC（按二级目录分组）
│   ├── AI/
│   │   ├── _index.md
│   │   └── CUDA/
│   │       └── CUDA 环境搭建.md
│   └── DevOps/
│       └── Docker 常用命令.md
└── 生活/
    └── _MOC_生活.md
```

笔记格式：

```markdown
---
title: "CUDA 环境搭建"
source: mybase
tags: [工作, 来源-工作, Linux, 编程]
database: "work2"
folder: "AI > CUDA"
---
# CUDA 环境搭建

...正文（HTML 已转为 Markdown）...
```

## 选项

| 选项 | 说明 |
|---|---|
| `--map OLD=NEW` | 顶层目录重命名，可重复。不指定的保持原名 |
| `--tag-prefix P` | 来源标签前缀（默认 `来源-`） |
| `--keyword-tags F` | 自定义关键词标签 JSON：`[["正则","标签"], ...]` |
| `--no-keyword-tags` | 关闭关键词自动打标 |
| `--dry-run` | 只打印将执行的操作，不写文件 |
| `--force` | 允许写入非空目录（默认拒绝，防止误覆盖） |

## 转换规则

1. 顶层的每个目录 = 一个数据库，映射为 Vault 顶层目录
2. 笔记目录 `index.md` → 同级 `标题.md`，正文 HTML 转 Markdown（加粗/斜体/链接/图片/列表/代码块/表格/分隔线）
3. frontmatter 保留 `title/source/database/folder`，`tags` 由顶层名 + 来源前缀 + 关键词规则生成
4. 子分类 `_index.md` 原样复制；顶层索引重新生成为 `_MOC_<分类>.md`
5. 根目录生成 `_MOC_总索引.md`

## 常见问题

**Q：中文乱码？**
脚本按 UTF-8 读写。Windows 下终端若显示乱码，用 `chcp 65001` 或直接看输出文件。

**Q：会覆盖我已有的 Vault 吗？**
默认拒绝写入非空目录，需显式 `--force`。转换会覆盖同名 `.md` 文件，建议先备份或先 `--dry-run` 预览。

**Q：图片去哪了？**
插件不导出图片文件本身，只保留 `<img>` 标签（转成 `![](路径)`）。若需要图片，从 myBase 数据目录手动拷贝到 Vault 对应位置，或在 Obsidian 中统一修复路径。

**Q：笔记标题重复怎么办？**
同目录下同名标题会互相覆盖——这是文件系统的限制。建议在 myBase 里事先去重，或改目录结构区分。

**Q：数据库很大（几千条）会很慢吗？**
纯 Python 单线程处理，万条以内通常几十秒。`--dry-run` 可以先估算规模。

## License

MIT。欢迎 Issue / PR。
