#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "parse_export_dir_as_dict_iter", "parse_export_dir_as_path_iter", 
    "export_dir", "export_dir_parse_iter", 
]
__doc__ = "这个模块提供了一些和导出目录树有关的函数"

from collections.abc import Iterator
from io import TextIOBase, TextIOWrapper
from os import PathLike
from re import compile as re_compile
from typing import IO

from posixpatht import escape


CRE_TREE_PREFIX_match = re_compile("^(?:\| )+\|-(.*)").match


def parse_export_dir_as_dict_iter(
    file: bytes | str | PathLike | IO, 
) -> Iterator[dict]:
    """解析 115 导出的目录树（可通过 P115Client.fs_export_dir 提交导出任务）

    :param file: 文件路径或者已经打开的文件

    :return: 把每一行解析为一个字典，迭代返回，格式为

        .. code:: python

            {
                "key":        int, # 序号
                "parent_key": int, # 上级目录的序号
                "depth":      int, # 深度
                "name":       str, # 名字
            }
    """
    if isinstance(file, (bytes, str, PathLike)):
        file = open(file, encoding="utf-16", newline="\n")
    elif not isinstance(file, TextIOBase):
        file = TextIOWrapper(file, encoding="utf-16", newline="\n")
    stack = [0]
    push = stack.append
    next(file, None)
    for i, m in enumerate(map(CRE_TREE_PREFIX_match, file)):
        name = m[1]
        depth = (len(m.string) - len(name)) // 2 - 1
        yield {
            "key": i, 
            "parent_key": stack[depth-1], 
            "depth": depth, 
            "name": name, 
        }
        try:
            stack[depth] = i
        except IndexError:
            push(i)


def parse_export_dir_as_path_iter(
    file: bytes | str | PathLike | IO, 
    escape: None | Callable[[str], str] = escape, 
) -> Iterator[str]:
    """解析 115 导出的目录树（可通过 P115Client.fs_export_dir 提交导出任务）

    :param file: 文件路径或已经打开的文件
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等

    :return: 把每一行解析为一个路径，并逐次迭代返回
    """
    if isinstance(file, (bytes, str, PathLike)):
        file = open(file, encoding="utf-16", newline="\n")
    elif not isinstance(file, TextIOBase):
        file = TextIOWrapper(file, encoding="utf-16", newline="\n")
    root = next(file)[3:-1]
    if root == "根目录":
        stack = [""]
    else:
        if escape is not None:
            root = escape(root)
        stack = ["/" + root]
    push = stack.append
    for m in map(CRE_TREE_PREFIX_match, file):
        name = m[1]
        depth = (len(m.string) - len(name)) // 2 - 1
        if escape is not None:
            name = escape(name)
        path = stack[depth-1] + "/" + name
        yield path
        try:
            stack[depth] = path
        except IndexError:
            push(path)


def export_dir(
    client: str | P115Client, 
    export_file_ids: int | str | Iterable[int] = 0, 
    target_pid: int | str = 0, 
) -> ExportDirStatus:
    """导出目录树

    :param client: 115 客户端或 cookies
    :param export_file_ids: 待导出的文件夹 id 或 路径
    :param target_pid: 导出到的目标文件夹 id 或 路径

    :return: 返回对象以获取进度
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if isinstance(export_file_ids, str):
        export_file_ids = client.fs_dir_getid(export_file_ids)
    elif not isinstance(export_file_ids, int):
        export_file_ids = ",".join(map(str, export_file_ids))
    if isinstance(target_pid, str):
        target_pid = client.fs.get_id(target_pid, pid=0)    
    return client.fs_export_dir_future({"file_ids": export_file_ids, "target": f"U_0_{target_pid}"})


def export_dir_parse_iter(
    client: str | P115Client, 
    export_file_ids: int | str | Iterable[int] = 0, 
    target_pid: int | str = 0, 
    parse_iter: Callable[[IO[bytes]], Iterator] = parse_export_dir_as_path_iter, 
    delete: bool = True, 
) -> Iterator:
    """导出目录树到文件，读取文件并解析后返回生成器，关闭后自动删除导出的文件

    :param client: 115 客户端或 cookies
    :param export_file_ids: 待导出的文件夹 id 或 路径
    :param target_pid: 导出到的目标文件夹 id 或 路径
    :param parse_iter: 解析打开的二进制文件，返回可迭代对象
    :param delete: 最终删除目录树文件

    :return: 解析导出文件的迭代器
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    future = export_dir(client, export_file_ids, target_pid)
    result = future.result()
    url = client.download_url(result["pick_code"], use_web_api=True)
    try:
        with client.open(url) as file:
            yield from parse_iter(file)
    finally:
        if delete:
            client.fs_delete(result["file_id"])

