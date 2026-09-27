"""开发者工具箱：给 Agent 配上真正干活的开发工具（读写文件 + 执行命令）。

工具清单：
- list_files(path)                        看目录结构                     风险 none
- read_file(path, max_chars=8000)         读文本文件                     风险 none
- write_file(path, content, backup=True)  写文本文件，默认自动备份 .bak   风险 medium
- run_cmd(command, timeout=60)            执行命令并返回输出              风险 high（每次需用户确认）

安全护栏（写死在代码里，不受参数影响）：
- run_cmd 硬拦截破坏性命令（格式化/删盘/关机/改引导/改注册表/taskkill 等），
  命中即拒，确认了也不执行；命令在独立进程里跑，超时强制结束
- write_file 拒绝写系统目录（Windows / Program Files 等）和 exe/dll/sys 文件
- read_file 单次最多读 64KB，防止把超大文件灌给模型
- 所有输出截断到 2000 字，命令默认 60 秒超时、上限 120 秒
"""
import shutil
import subprocess
from pathlib import Path

NAME = "开发者工具箱"
VERSION = "1.0.0"
DESCRIPTION = "让 Agent 直接读写文件和执行命令，开发软件的核心工具"

MAX_READ_BYTES = 64 * 1024
CMD_TIMEOUT_MAX = 120
OUTPUT_CLIP = 2000

# 命中即硬拦截的命令形态（归一化后子串匹配；宁可错杀不可放过）
_DENY_TOKENS = (
    "format ", "format/", "diskpart", "shutdown", "restart-computer",
    "rd /s", "rmdir /s", "del /f", "del /q", "del /s", "del *",
    "rm -rf", "rm -r ", "mkfs", "dd if=", "cipher /w",
    "vssadmin", "bcdedit", "reg delete", "reg add", "regedit",
    "schtasks /create", "schtasks /change", "taskkill",
    "attrib -s", "takeown", "icacls", "net user", "net localgroup",
)

# 系统目录前缀（写文件硬拦截）
_SYSTEM_PREFIXES = ("c:\\windows", "c:\\program files", "c:\\program files (x86)",
                    "c:\\programdata\\microsoft", "c:\\users\\default")


def _clean(path_text):
    return str(path_text or "").strip().strip('"').strip("'")


def _decode(b):
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _clip(text):
    text = text.strip()
    if len(text) <= OUTPUT_CLIP:
        return text
    return text[:OUTPUT_CLIP] + f"\n…（输出过长已截断，共 {len(text)} 字，可缩小范围再看）"


def _list_files(args):
    path = _clean(args.get("path")) or "."
    p = Path(path)
    if not p.is_dir():
        return f"错误: 目录不存在：{p}"
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = []
        for e in entries[:200]:
            if e.is_dir():
                lines.append(f"[目录] {e.name}/")
            else:
                try:
                    size = e.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"       {e.name}  ({size} 字节)")
        if len(entries) > 200:
            lines.append(f"…（共 {len(entries)} 项，只显示前 200）")
        return f"{p.resolve()}：\n" + ("\n".join(lines) if lines else "（空目录）")
    except Exception as e:
        return f"错误: 读取目录失败 - {type(e).__name__}: {e}"


def _read_file(args):
    path = _clean(args.get("path"))
    try:
        max_chars = max(500, min(int(args.get("max_chars", 8000) or 8000), 20000))
    except (TypeError, ValueError):
        max_chars = 8000
    if not path:
        return "错误: 缺少 path 参数"
    p = Path(path)
    if not p.is_file():
        return f"错误: 文件不存在：{p}"
    try:
        total = p.stat().st_size
        data = p.read_bytes()[:MAX_READ_BYTES]
        text = _decode(data)
        head = text[:max_chars]
        more = ""
        if len(text) > max_chars or total > MAX_READ_BYTES:
            more = f"\n…（文件共 {total} 字节，本次显示前 {len(head)} 字；大文件可用 max_chars 分段读）"
        return f"{p}（{total} 字节）：\n{head}{more}"
    except Exception as e:
        return f"错误: 读取失败 - {type(e).__name__}: {e}"


def _write_file(args):
    path = _clean(args.get("path"))
    content = args.get("content", "")
    backup = args.get("backup", True)
    if not path:
        return "错误: 缺少 path 参数"
    p = Path(path).resolve()
    low = str(p).lower()
    for prefix in _SYSTEM_PREFIXES:
        if low.startswith(prefix):
            return f"已拦截：{p} 在系统目录里，不允许写"
    if p.suffix.lower() in (".exe", ".dll", ".sys"):
        return f"已拦截：不允许写 {p.suffix} 类型的系统文件"
    if not isinstance(content, str):
        content = str(content)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        note = ""
        if backup and p.exists():
            bak = p.with_name(p.name + ".bak")
            shutil.copy2(p, bak)
            note = f"（原文件已备份为 {bak.name}）"
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p}（{len(content)} 字）{note}"
    except Exception as e:
        return f"错误: 写入失败 - {type(e).__name__}: {e}"


def _run_cmd(args):
    command = _clean(args.get("command"))
    try:
        timeout = max(5, min(int(args.get("timeout", 60) or 60), CMD_TIMEOUT_MAX))
    except (TypeError, ValueError):
        timeout = 60
    if not command:
        return "错误: 缺少 command 参数"
    norm = " ".join(command.lower().split())
    for token in _DENY_TOKENS:
        if token in norm:
            return (f"已拦截：命令命中破坏性特征「{token.strip()}」，不会执行。"
                    f"也不要换说法绕过——这类操作需要用户手动处理")
    try:
        done = subprocess.run(command, shell=True, capture_output=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return (f"错误: 命令超过 {timeout} 秒没跑完，已强制结束。"
                f"先想想它是不是在等输入，或换更小的步骤")
    except Exception as e:
        return f"错误: 执行失败 - {type(e).__name__}: {e}"
    out, err = _clip(_decode(done.stdout)), _clip(_decode(done.stderr))
    parts = [f"退出码: {done.returncode}（0 = 成功）"]
    if out:
        parts.append(f"输出:\n{out}")
    if err:
        parts.append(f"报错输出:\n{err}")
    if not out and not err:
        parts.append("（命令没有输出）")
    return "\n".join(parts)


def get_tools():
    return [
        {
            "name": "list_files",
            "description": "列出目录下的文件和子目录（看项目结构用）",
            "parameters": {
                "path": {"type": "string", "description": "目录路径，缺省为当前目录"},
            },
            "run": _list_files,
            "prompt_hint": "list_files(path): 列出目录内容，看项目结构用",
            "default_risk": "none",
        },
        {
            "name": "read_file",
            "description": "读取文本文件内容（代码、配置、日志），单次上限 64KB",
            "parameters": {
                "path": {"type": "string", "description": "文件路径"},
                "max_chars": {"type": "integer", "description": "最多返回多少字，默认 8000"},
            },
            "run": _read_file,
            "prompt_hint": "read_file(path, max_chars=8000): 读文本文件；大文件分段读",
            "default_risk": "none",
        },
        {
            "name": "write_file",
            "description": "写入/新建文本文件（全量覆盖），默认自动把原文件备份成 .bak",
            "parameters": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
                "backup": {"type": "boolean", "description": "覆盖已有文件前是否备份，默认 true"},
            },
            "run": _write_file,
            "prompt_hint": "write_file(path, content, backup=True): 写文件（全量覆盖，自动备份）",
            "default_risk": "medium",
        },
        {
            "name": "run_cmd",
            "description": "执行一条命令并返回输出与退出码；破坏性命令会被直接拦截，且每次执行需用户确认",
            "parameters": {
                "command": {"type": "string", "description": "要执行的命令（一次一条）"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 60，上限 120"},
            },
            "run": _run_cmd,
            "prompt_hint": "run_cmd(command, timeout=60): 执行命令拿输出；一条一条执行，破坏性命令被拦截",
            "default_risk": "high",
        },
    ]
