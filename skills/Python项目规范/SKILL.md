---
name: Python项目规范
version: 1.0.0
type: skill
description: 新建或整理 Python 项目时的标准摆法
triggers: 新建项目, python项目, 整理目录, requirements
---

Python 项目按这个规矩来：
1. 最简结构：主程序放根目录，测试文件 test_ 开头，文档放 docs/，示例放 examples/
2. 依赖一律写进 requirements.txt（版本用 >= 下限），装过的包不许不记录
3. 不改系统 Python 环境；不往 C:\Windows、Program Files 写任何文件
4. 临时文件放 temp 目录或加 .tmp 后缀，用完删除
5. 注释和提示语用中文；每个函数开头一句中文说明「这个函数干什么」
6. 新建项目先搭骨架再填肉：目录 → 主程序框架 → 测试 → 逐步实现
