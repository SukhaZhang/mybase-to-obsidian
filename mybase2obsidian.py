#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mybase2obsidian —— 把 myBase 导出的中间目录转换成 Obsidian Vault。

第一步：在 myBase 里运行插件 mybase_export_plugin.js，导出为中间格式：
    <导出目录>/<数据库别名>/<分类层级>/index.md      （笔记）
    <导出目录>/<数据库别名>/<分类层级>/_index.md     （分类索引）

第二步：运行本脚本把中间格式转成 Obsidian Vault：
    python mybase2obsidian.py <导出目录> <Vault目录>

常用选项：
    --map old=new        顶层目录重命名（可重复），如 --map work=工作 --map life=生活
                         未指定的顶层目录保持原名
    --tag-prefix P       来源标签前缀，默认「来源-」（标签形如 来源-工作）
    --keyword-tags F     关键词标签配置 JSON（[[正则, 标签], ...]），默认内置通用规则
    --no-keyword-tags    关闭关键词自动打标
    --dry-run            只打印将执行的操作，不写文件
    --force              允许写入非空目录（默认拒绝，防止覆盖已有 Vault）

设计目标：零第三方依赖、任何 myBase 数据库都能用、默认不覆盖。
"""

import argparse
import json
import os
import re
import sys
from html import unescape
from html.parser import HTMLParser

# ---------------------------------------------------------------- 默认配置

# 内置的通用关键词标签规则（可用 --keyword-tags 覆盖）
DEFAULT_KEYWORD_TAGS = [
    [r"数据库|SQL|MySQL|PostgreSQL|SQLite|Oracle", "数据库"],
    [r"Docker|Kubernetes|K8s|容器", "DevOps"],
    [r"安全|漏洞|渗透|加密", "安全"],
    [r"Linux|Ubuntu|CentOS|Debian", "Linux"],
    [r"嵌入式|单片机|STM32|ESP32|ARM", "嵌入式"],
    [r"\bAI\b|人工智能|机器学习|深度学习|LLM", "AI"],
    [r"Python|Golang|Go语言|Rust|JavaScript", "编程"],
]

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


# ---------------------------------------------------------------- 工具函数

def clean_name(s: str) -> str:
    """清理为合法文件名：替换 Windows 非法字符、压缩空白、限长。"""
    s = ILLEGAL_CHARS.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        s = "Untitled"
    return s[:128]


def parse_frontmatter(text: str):
    """解析 index.md 的 frontmatter（--- 包裹的简单 YAML 键值对）。

    返回 (fields_dict, body)。兼容 BOM 与 CRLF。
    """
    text = text.lstrip("\ufeff")
    m = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fields = {}
    for line in fm_text.splitlines():
        mm = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not mm:
            continue
        key, val = mm.group(1), mm.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        fields[key] = val
    return fields, body


def build_frontmatter(fields: dict) -> str:
    """序列化 frontmatter（固定字段顺序，输出稳定便于 diff）。"""
    order = ["title", "source", "tags", "database", "folder"]
    lines = ["---"]
    for k in order:
        if k not in fields:
            continue
        v = fields[k]
        if k == "tags":
            lines.append("tags: [%s]" % ", ".join(v) if isinstance(v, list) else "tags: %s" % v)
        elif k in ("title", "database", "folder"):
            lines.append('%s: "%s"' % (k, str(v).replace('"', '\\"')))
        else:
            lines.append("%s: %s" % (k, v))
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- HTML → Markdown

class HtmlToMarkdown(HTMLParser):
    """把 myBase 正文 HTML 转成 Markdown。

    支持：加粗、斜体、链接、图片、列表、代码块、标题、分隔线、表格（尽力而为）。
    设计取舍：宁可保守（少转换）也不生成破坏 Obsidian 渲染的语法。
    """

    BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                  "table", "ul", "ol", "section", "article", "blockquote", "pre"}
    SKIP_TAGS = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._link_href = None
        self._link_text = []
        self._skip = 0
        self._in_pre = 0
        self._in_td = False
        self._row_cells = []
        self._in_table_row = False

    # -- 起步/收尾

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        a = dict(attrs)
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self._in_pre:
            self.out.append("`")
        elif tag == "pre":
            self._in_pre += 1
            self._nl()
            self.out.append("```\n")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "hr":
            self.out.append("\n---\n")
        elif tag == "a":
            self._link_href = a.get("href", "")
            self._link_text = []
        elif tag == "img":
            src = a.get("src", "")
            alt = a.get("alt", "")
            if src:
                self.out.append("![%s](%s)" % (alt, src))
        elif tag == "li":
            self._nl()
            self.out.append("- ")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._nl()
            level = int(tag[1])
            self.out.append("#" * min(level + 1, 6) + " ")  # myBase 标题层级降一级，避免与笔记标题冲突
        elif tag == "tr":
            self._in_table_row = True
            self._row_cells = []
            self._nl()
            self.out.append("| ")
        elif tag in ("td", "th"):
            self._in_td = True
            if self._row_cells:
                self.out.append(" | ")
            self._row_cells.append(tag)
        elif tag in self.BLOCK_TAGS:
            self._nl()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self._in_pre:
            self.out.append("`")
        elif tag == "pre":
            self._in_pre = max(0, self._in_pre - 1)
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
            self.out.append("```\n")
        elif tag == "a" and self._link_href is not None:
            text = "".join(self._link_text).strip() or self._link_href
            self.out.append("[%s](%s)" % (text, self._link_href))
            self._link_href, self._link_text = None, []
        elif tag in ("td", "th"):
            self._in_td = False
        elif tag == "tr":
            self.out.append(" |\n")
            if not getattr(self, "_table_header_done", False):
                self.out.append("| " + " | ".join(["---"] * max(1, len(self._row_cells))) + " |\n")
                self._table_header_done = True
            self._in_table_row = False
        elif tag == "table":
            self._table_header_done = False
            self._nl()
        elif tag in self.BLOCK_TAGS:
            self._nl()

    def handle_data(self, data):
        if self._skip:
            return
        if self._link_href is not None:
            self._link_text.append(data)
            return
        self.out.append(data)

    # -- 小工具

    def _nl(self):
        if self.out and not self.out[-1].endswith("\n"):
            self.out.append("\n")

    def get_text(self) -> str:
        s = "".join(self.out)
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"\n{3,}", "\n\n", s)
        s = re.sub(r"[ \t]+\n", "\n", s)
        return s.strip() + "\n"


def html_to_markdown(html_text: str) -> str:
    if not html_text:
        return ""
    if "<" not in html_text:
        return html_text.strip() + "\n"
    parser = HtmlToMarkdown()
    try:
        parser.feed(html_text)
        parser.close()
        return parser.get_text()
    except Exception:
        return unescape(re.sub(r"<[^>]+>", "", html_text)).strip() + "\n"


# ---------------------------------------------------------------- 转换逻辑

def keyword_tags(text: str, rules):
    """按规则给正文打标签，返回命中标签列表（去重、保持顺序）。"""
    found = []
    for pat, tag in rules:
        if tag in found:
            continue
        try:
            if re.search(pat, text, re.IGNORECASE):
                found.append(tag)
        except re.error:
            continue
    return found


def convert_note(src_path, vault, top_name, source_name, tag_prefix, rules, stats, dry):
    """单个笔记：index.md -> 标题.md。返回 (rel_path, title) 或 None。"""
    with open(src_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    fields, body = parse_frontmatter(raw)

    title = (fields.get("title") or "").strip()
    if not title:
        title = clean_name(os.path.basename(os.path.dirname(src_path)))

    # 去掉正文开头的重复标题行（"# xxx"）
    body = re.sub(r"^#\s+.*\r?\n\r?\n?", "", body, count=1)
    body_md = html_to_markdown(body)

    tags = [top_name, tag_prefix + top_name]
    tags += keyword_tags(title + "\n" + body_md, rules)

    out_fields = dict(fields)
    out_fields["source"] = source_name
    out_fields["tags"] = tags
    if "database" not in out_fields and source_name:
        pass  # 保留插件写入的 database；没有就不补

    # 相对路径：<vault>/<顶层名>/<中间分类...>/<标题>.md
    rel_dir = os.path.relpath(os.path.dirname(src_path), SRC_ROOT)
    parts = rel_dir.split(os.sep)
    parts[0] = top_name
    dst_rel = os.path.join(*parts, clean_name(title) + ".md")
    dst_path = os.path.join(vault, dst_rel)

    if dry:
        print("[note] %s -> %s" % (os.path.relpath(src_path, SRC_ROOT), dst_rel))
    else:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        content = build_frontmatter(out_fields) + "# " + title + "\n\n" + body_md
        with open(dst_path, "w", encoding="utf-8") as f:
            f.write(content)
    stats["notes"] += 1
    return dst_rel.replace(os.sep, "/"), title


def convert_index(src_path, vault, top_name, top_src, dry, stats):
    """分类索引 _index.md：子分类原样复制；顶层索引交给 MOC 生成。"""
    rel_dir = os.path.relpath(os.path.dirname(src_path), top_src)
    if rel_dir == ".":
        return  # 顶层索引由 MOC 接管
    parts = rel_dir.split(os.sep)
    dst_rel = os.path.join(top_name, *parts, "_index.md")
    dst_path = os.path.join(vault, dst_rel)
    if dry:
        print("[index] %s -> %s" % (os.path.relpath(src_path, SRC_ROOT), dst_rel))
    else:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(src_path, "r", encoding="utf-8-sig") as f:
            content = f.read().lstrip("\ufeff")
        with open(dst_path, "w", encoding="utf-8") as f:
            f.write(content)
    stats["indexes"] += 1


def build_moc(vault, top_name, notes, dry, stats):
    """为顶层分类生成 _MOC_<分类>.md（按二级目录分组列链接）。"""
    groups = {}
    for rel_path, title in notes:
        parts = rel_path.split("/")
        second = parts[1] if len(parts) > 2 else "(根)"
        groups.setdefault(second, []).append((rel_path, title))

    lines = ["# %s - 索引" % top_name, "", "共 %d 条笔记" % len(notes), ""]
    for second in sorted(groups):
        lines += ["## " + second, ""]
        for rel_path, title in sorted(groups[second], key=lambda x: x[1].lower()):
            link = rel_path[:-3]
            lines.append("- [[%s|%s]]" % (link, title))
        lines.append("")

    rel = os.path.join(top_name, "_MOC_%s.md" % clean_name(top_name))
    if dry:
        print("[moc] %s (%d notes)" % (rel, len(notes)))
        return rel.replace(os.sep, "/")
    dst_path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    stats["mocs"] += 1
    return rel.replace(os.sep, "/")


def load_keyword_rules(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rules = []
    for item in data:
        if isinstance(item, list) and len(item) == 2:
            rules.append((item[0], item[1]))
    return rules


def main():
    global SRC_ROOT
    ap = argparse.ArgumentParser(
        description="把 myBase 导出的中间目录转换为 Obsidian Vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例: python mybase2obsidian.py mybase_export MyVault --map work=工作 --map life=生活",
    )
    ap.add_argument("src", help="myBase 插件导出的中间目录")
    ap.add_argument("vault", help="Obsidian Vault 输出目录")
    ap.add_argument("--map", action="append", default=[], metavar="OLD=NEW",
                    help="顶层目录重命名（可重复）")
    ap.add_argument("--tag-prefix", default="来源-", help="来源标签前缀（默认 来源-）")
    ap.add_argument("--keyword-tags", default=None, metavar="JSON",
                    help="关键词标签配置文件（[[正则,标签],...]）")
    ap.add_argument("--no-keyword-tags", action="store_true", help="关闭关键词自动打标")
    ap.add_argument("--dry-run", action="store_true", help="只打印操作不写文件")
    ap.add_argument("--force", action="store_true", help="允许写入非空目录")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        sys.exit("错误：源目录不存在：%s" % args.src)

    SRC_ROOT = os.path.abspath(args.src)
    if os.path.exists(args.vault) and os.listdir(args.vault) and not args.force:
        sys.exit("错误：目标目录非空：%s\n（确认要写入请加 --force）" % args.vault)

    renames = {}
    for m in args.map:
        if "=" not in m:
            sys.exit("--map 格式应为 OLD=NEW，例如 work=工作")
        old, new = m.split("=", 1)
        renames[old.strip()] = new.strip()

    rules = DEFAULT_KEYWORD_TAGS
    if args.no_keyword_tags:
        rules = []
    elif args.keyword_tags:
        rules = load_keyword_rules(args.keyword_tags)

    # 自动发现顶层目录：源目录下包含 _index.md 或子目录的一级目录
    tops = []
    for name in sorted(os.listdir(SRC_ROOT)):
        full = os.path.join(SRC_ROOT, name)
        if os.path.isdir(full):
            tops.append(name)
    if not tops:
        sys.exit("错误：%s 下没有找到任何数据库子目录（应为插件导出的顶层目录）" % args.src)

    stats = {"notes": 0, "indexes": 0, "mocs": 0}
    total_lines = ["# 总索引", ""]

    top_notes_all = {}
    for top_key in tops:
        top_src = os.path.join(SRC_ROOT, top_key)
        top_name = clean_name(renames.get(top_key, top_key))
        print("== 处理顶层目录: %s -> %s" % (top_key, top_name))

        notes = []
        for dirpath, _dirnames, filenames in os.walk(top_src):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if fn == "index.md":
                    r = convert_note(full, args.vault, top_name, "mybase",
                                     args.tag_prefix, rules, stats, args.dry_run)
                    if r:
                        notes.append(r)
                elif fn == "_index.md":
                    convert_index(full, args.vault, top_name, top_src, args.dry_run, stats)

        if notes:
            moc = build_moc(args.vault, top_name, notes, args.dry_run, stats)
            top_notes_all[top_name] = (notes, moc)

    # 总索引
    total = sum(len(n) for n, _ in top_notes_all.values())
    total_lines.append("共 %d 条笔记" % total)
    total_lines.append("")
    for name, (notes, moc) in top_notes_all.items():
        total_lines.append("- [[%s|%s]] (%d 条)" % (moc[:-3], name, len(notes)))
    if not args.dry_run:
        with open(os.path.join(args.vault, "_MOC_总索引.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(total_lines) + "\n")
    else:
        print("[moc] _MOC_总索引.md")

    print()
    print("完成：%d 条笔记，%d 个分类索引，%d 个 MOC" % (stats["notes"], stats["indexes"], stats["mocs"]))
    print("输出：%s" % args.vault)


if __name__ == "__main__":
    main()
