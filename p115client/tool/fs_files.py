#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["iter_fs_files", "iter_fs_files_threaded", "iter_fs_files_asynchronized"]
__doc__ = "这个模块利用 P115Client.fs_files 方法做了一些封装"

from asyncio import shield, wait_for, Task, TaskGroup
from collections import deque
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from copy import copy
from errno import EBUSY, ENOENT, ENOTDIR
from functools import partial
from itertools import cycle
from time import time
from typing import cast, overload, Final, Literal
from warnings import warn

from iterutils import run_gen_step, run_gen_step_iter, Yield
from p115client import check_response, P115Client
from p115client.client import get_status_code
from p115client.exception import BusyOSError, DataError, P115Warning


get_proapi_origin: Final = cycle(("https://proapi.115.com", "http://pro.api.115.com")).__next__


def is_timeouterror(exc: BaseException, /) -> bool:
    """通过名字来判断一个异常是不是 Timeout
    """
    exctype = type(exc)
    for exctype in exctype.mro():
        if exctype is Exception:
            break
        if "Timeout" in exctype.__name__:
            return True
    return False


@overload
def iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    /, 
    first_page_size: int = 0, 
    page_size: int = 10_000, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    /, 
    first_page_size: int = 0, 
    page_size: int = 10_000, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    /, 
    first_page_size: int = 0, 
    page_size: int = 10_000, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> AsyncIterator[dict] | Iterator[dict]:
    """拉取一个目录中的文件或目录的数据

    :param client: 115 网盘客户端对象
    :param payload: 目录的 id 或者详细的查询参数
    :param first_page_size: 首次拉取的分页大小，如果 <= 0，则自动确定
    :param page_size: 分页大小，如果 <= 0，则自动确定
    :param app: 使用此设备的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 迭代器，每次返回一次接口调用的结果
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    if first_page_size <= 0:
        first_page_size = page_size
    if isinstance(payload, (int, str)):
        payload = {"cid": payload}
    payload = {
        "asc": 0, "cid": 0, "custom_order": 1, "fc_mix": 1, "o": "user_utime", 
        "offset": 0, "limit": first_page_size, "show_dir": 1, **payload, 
    }
    cid = int(payload["cid"])
    if app in ("", "web", "desktop", "harmony"):
        fs_files = partial(client.fs_files, async_=async_, **request_kwargs)
    else:
        request_kwargs.setdefault("base_url", get_proapi_origin)
        fs_files = partial(client.fs_files_app, app=app, async_=async_, **request_kwargs)
    def get_files(payload: dict, /):
        while True:
            try:
                resp = yield fs_files(payload)
                return check_response(resp)
            except DataError:
                if payload["limit"] <= 1150:
                    raise
                payload["limit"] -= 1_000
                if payload["limit"] < 1150:
                    payload["limit"] = 1150
    def gen_step():
        resp = yield run_gen_step(get_files(payload), async_=async_)
        payload["limit"] = page_size
        count = int(resp["count"])
        while True:
            if cid and int(resp["path"][-1]["cid"]) != cid:
                raise NotADirectoryError(ENOTDIR, cid)
            yield Yield(resp, identity=True)
            payload["offset"] += len(resp["data"])
            if payload["offset"] >= count:
                break
            resp = yield run_gen_step(get_files(payload), async_=async_)
            if count != (count := int(resp["count"])):
                message = f"cid={cid} detected count changes during iteration: {count} -> {resp['count']}"
                if raise_for_changed_count:
                    raise BusyOSError(EBUSY, message)
                else:
                    warn(message, category=P115Warning)
    return run_gen_step_iter(gen_step, async_=async_)


def iter_fs_files_threaded(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    /, 
    page_size: int = 7_000, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    cooldown: int | float = 1, 
    max_workers: None | int = None, 
    **request_kwargs, 
) -> Iterator[dict]:
    """多线程并发拉取一个目录中的文件或目录的数据

    :param client: 115 网盘客户端对象
    :param payload: 目录的 id 或者详细的查询参数
    :param page_size: 分页大小，如果 <= 0，则自动确定
    :param app: 使用此设备的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param cooldown: 冷却时间，单位为秒
    :param max_workers: 最大工作线程数
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 迭代器
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 7_000
    if isinstance(payload, (int, str)):
        payload = {"cid": payload}
    payload = {
        "asc": 1, "cid": 0, "custom_order": 1, "fc_mix": 1, "o": "user_ctime", 
        "offset": 0, "limit": page_size, "show_dir": 1, **payload, 
    }
    cid = int(payload["cid"])
    request_kwargs["async_"] = False
    if app in ("", "web", "desktop", "harmony"):
        page_size = min(page_size, 1150)
        fs_files = partial(client.fs_files, **request_kwargs)
    else:
        request_kwargs.setdefault("base_url", get_proapi_origin)
        fs_files = partial(client.fs_files_app, app=app, **request_kwargs)
    dq: deque[tuple[Future, int]] = deque()
    push, pop = dq.append, dq.popleft
    executor = ThreadPoolExecutor(max_workers=max_workers)
    submit = executor.submit
    ts: int | float = 0
    def make_future(args: None | dict = None, /) -> Future:
        nonlocal ts
        if args is None:
            args = copy(payload)
        ts = time()
        return submit(fs_files, args)
    try:
        count = -1
        future = make_future()
        offset = payload["offset"]
        while True:
            try:
                resp = check_response(future.result(max(0, ts + cooldown - time())))
            except TimeoutError:
                payload["offset"] += page_size
                if count < 0 or payload["offset"] < count:
                    push((make_future(), payload["offset"]))
            except BaseException as e:
                if get_status_code(e) >= 400 or not is_timeouterror(e):
                    raise
                future = make_future({**payload, "offset": offset})
            else:
                if cid and int(resp["path"][-1]["cid"]) != cid:
                    if count < 0:
                        raise NotADirectoryError(ENOTDIR, cid)
                    else:
                        raise FileNotFoundError(ENOENT, cid)
                yield resp
                if count < 0:
                    count = int(resp["count"])
                elif count != (count := int(resp["count"])):
                    message = f"cid={cid} detected count changes during iteration: {count} -> {resp['count']}"
                    if raise_for_changed_count:
                        raise BusyOSError(EBUSY, message)
                    else:
                        warn(message, category=P115Warning)
                if dq:
                    future, offset = pop()
                elif not count or offset >= count or offset != resp["offset"] or offset + len(resp["data"]) >= count:
                    break
                else:
                    offset = payload["offset"] = offset + page_size
                    if offset >= count:
                        break
                    ts = time()
                    future = make_future()
    finally:
        executor.shutdown(False, cancel_futures=True)


async def iter_fs_files_asynchronized(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    /, 
    page_size: int = 7_000, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    cooldown: int | float = 1, 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    """异步并发拉取一个目录中的文件或目录的数据

    :param client: 115 网盘客户端对象
    :param payload: 目录的 id 或者详细的查询参数
    :param page_size: 分页大小，如果 <= 0，则自动确定
    :param app: 使用此设备的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param cooldown: 冷却时间，单位为秒
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 迭代器
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 7_000
    if isinstance(payload, (int, str)):
        payload = {"cid": payload}
    payload = {
        "asc": 1, "cid": 0, "custom_order": 1, "fc_mix": 1, "o": "user_ctime", 
        "offset": 0, "limit": page_size, "show_dir": 1, **payload, 
    }
    cid = int(payload["cid"])
    request_kwargs["async_"] = True
    if app in ("", "web", "desktop", "harmony"):
        page_size = min(page_size, 1150)
        fs_files = partial(client.fs_files, **request_kwargs)
    else:
        request_kwargs.setdefault("base_url", get_proapi_origin)
        fs_files = partial(client.fs_files_app, app=app, **request_kwargs)
    dq: deque[tuple[Task, int]] = deque()
    push, pop = dq.append, dq.popleft
    async with TaskGroup() as tg:
        create_task = tg.create_task
        ts: int | float = 0
        def make_task(args: None | dict = None, /) -> Task:
            nonlocal ts
            if args is None:
                args = copy(payload)
            ts = time()
            return create_task(fs_files(args)) # type: ignore
        count = -1
        task = make_task()
        offset = payload["offset"]
        while True:
            try:
                resp = check_response(await wait_for(shield(task), max(0, ts + cooldown - time())))
            except TimeoutError:
                payload["offset"] += page_size
                if count < 0 or payload["offset"] < count:
                    push((make_task(), payload["offset"]))
            except BaseException as e:
                if get_status_code(e) >= 400 or not is_timeouterror(e):
                    raise
                task = make_task({**payload, "offset": offset})
            else:
                if cid and int(resp["path"][-1]["cid"]) != cid:
                    if count < 0:
                        raise NotADirectoryError(ENOTDIR, cid)
                    else:
                        raise FileNotFoundError(ENOENT, cid)
                yield resp
                if count < 0:
                    count = int(resp["count"])
                elif count != (count := int(resp["count"])):
                    message = f"cid={cid} detected count changes during iteration: {count} -> {resp['count']}"
                    if raise_for_changed_count:
                        raise BusyOSError(EBUSY, message)
                    else:
                        warn(message, category=P115Warning)
                if dq:
                    task, offset = pop()
                elif not count or offset >= count or offset != resp["offset"] or offset + len(resp["data"]) >= count:
                    break
                else:
                    offset = payload["offset"] = offset + page_size
                    if offset >= count:
                        break
                    task = make_task()

# TODO: 以上的数据获取方式某种程度上应该是通用的，只要是涉及到 offset 和 count，因此可以总结出一个更抽象的函数
