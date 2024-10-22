#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["update_desc", "update_star"]
__doc__ = "这个模块提供了一些和修改文件或目录信息有关的函数"

from collections.abc import Iterable, Iterator, Sequence
from itertools import count, islice, takewhile
from typing import overload, Literal

from iterutils import run_gen_step
from p115client import check_response, P115Client


def update_desc(
    client: str | P115Client, 
    ids: Iterable[int | str], 
    /, 
    desc: str = "", 
    batch_size: int = 10_000, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
):
    """批量设置文件或目录的备注，此举可更新此文件或目录的 mtime

    :param client: 115 客户端或 cookies
    :param ids: 一组文件或目录的 id
    :param desc: 备注文本
    :param batch_size: 批次大小，分批次，每次提交的 id 数
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    set_desc = client.fs_desc_set
    def gen_step():
        if isinstance(ids, Sequence):
            it: Iterator[Iterable[int | str]] = (ids[i:i+batch_size] for i in range(0, len(ids), batch_size))
        else:
            ids_it = iter(ids)
            it = takewhile(bool, (tuple(islice(ids_it, batch_size)) for _ in count()))
        for batch in it:
            resp = yield set_desc(batch, desc, async_=async_, **request_kwargs)
            check_response(resp)
    return run_gen_step(gen_step, async_=async_)


def update_star(
    client: str | P115Client, 
    ids: Iterable[int | str], 
    /, 
    star: bool = True, 
    batch_size: int = 10_000, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
):
    """批量给文件或目录设置或取消星标

    :param client: 115 客户端或 cookies
    :param ids: 一组文件或目录的 id
    :param star: 是否设置星标
    :param batch_size: 批次大小，分批次，每次提交的 id 数
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    set_star = client.fs_star_set
    def gen_step():
        if isinstance(ids, Sequence):
            it: Iterator[Iterable[int | str]] = (ids[i:i+batch_size] for i in range(0, len(ids), batch_size))
        else:
            ids_it = iter(ids)
            it = takewhile(bool, (tuple(islice(ids_it, batch_size)) for _ in count()))
        for batch in it:
            resp = yield set_star(batch, star, async_=async_, **request_kwargs)
            check_response(resp)
    return run_gen_step(gen_step, async_=async_)

