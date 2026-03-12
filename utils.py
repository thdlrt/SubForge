"""
通用工具函数
"""
import re


def sanitize_name(name):
    """将文件/目录名中对 Windows 路径和 ffmpeg subtitle filter 有害的字符替换为下划线。"""
    name = name.replace("：", "_")
    name = re.sub(r"[\\/:*?\"<>|']", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_. ")
