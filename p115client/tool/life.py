#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "BEHAVIOR_TYPE_TO_NAME", "BEHAVIOR_NAME_TO_TYPE", "life_show", 
    "iter_life_list", "iter_life_behavior", 
]
__doc__ = "这个模块提供了一些和 115 生活事件有关的函数"

from asyncio import sleep as async_sleep
from collections.abc import AsyncIterator, Container, Coroutine, Iterator
from functools import partial
from itertools import count
from time import time, sleep
from typing import overload, Any, Final, Literal

from iterutils import run_gen_step_iter, Yield
from p115client import check_response, P115Client


IGNORE_BEHAVIOR_TYPES: Final = frozenset((3, 4, 7, 8, 9, 10, 19))
#: 115 生活事件名称到类型的映射
BEHAVIOR_NAME_TO_TYPE: Final = {
    "upload_image_file": 1, 
    "upload_file": 2, 
    "star_image": 3, 
    "star_file": 4, 
    "move_image_file": 5, 
    "move_file": 6, 
    "browse_image": 7, 
    "browse_video": 8, 
    "browse_audio": 9, 
    "browse_document": 10, 
    "receive_files": 14, 
    "new_folder": 17, 
    "copy_folder": 18, 
    "folder_label": 19, 
    "folder_rename": 20, 
    "delete_file": 22, 
}
#: 115 生活事件类型到名称的映射
BEHAVIOR_TYPE_TO_NAME: Final = {v: k for k, v in BEHAVIOR_NAME_TO_TYPE.items()}


@overload
def life_show(
    client: str | P115Client, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict:
    ...
@overload
def life_show(
    client: str | P115Client, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict]:
    ...
def life_show(
    client: str | P115Client, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict | Coroutine[Any, Any, dict]:
    """确保 115 生活的事件列表为开启状态

    :param client: 115 客户端或 cookies
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 接口返回值
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    return client.life_calendar_setoption(async_=async_, **request_kwargs)


@overload
def iter_life_list(
    client: str | P115Client, 
    start_time: int | float = 0, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_life_list(
    client: str | P115Client, 
    start_time: int | float = 0, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_life_list(
    client: str | P115Client, 
    start_time: int | float = 0, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> AsyncIterator[dict] | Iterator[dict]:
    """持续拉取 115 生活事件列表

    .. caution::
        115 并没有收集 复制文件 和 文件改名 的事件，以及第三方上传可能会没有 上传事件 ("upload_image_file" 和 "upload_file")

    :param client: 115 客户端或 cookies
    :param start_time: 开始时间（不含），若为 0 则从上 1 秒开始
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生 115 生活事件日志数据字典
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    life_list = partial(client.life_list, **request_kwargs)
    life_behavior_detail = partial(client.life_behavior_detail_app, **request_kwargs)
    def gen_step():
        nonlocal start_time
        end_time = int(time())
        if start_time == 0:
            start_time = end_time - 2
        while True:
            resp = yield life_list({"show_type": 0, "start_time": start_time, "end_time": end_time}, async_=async_)
            data = check_response(resp)["data"]
            if data["count"]:
                for items in data["list"]:
                    if "items" not in items:
                        if start_time < items["update_time"] < end_time:
                            yield Yield(items, identity=True)
                        continue
                    behavior_type = items["behavior_type"]
                    date = items["date"]
                    for item in items["items"]:
                        item["behavior_type"] = behavior_type
                        item["date"] = date
                        yield Yield(item, identity=True)
                    if behavior_type.startswith("upload_") or items["total"] > len(items["items"]):
                        seen_items: set[str] = {item["id"] for item in items["items"]}
                        payload = {"offset": 0, "limit": 32, "type": behavior_type, "date": date}
                        while True:
                            resp = yield life_behavior_detail(payload, async_=async_)
                            for item in check_response(resp)["data"]["list"]:
                                if item["id"] in seen_items or item["update_time"] >= end_time:
                                    continue
                                elif item["update_time"] <= start_time:
                                    break
                                seen_items.add(item["id"])
                                item["behavior_type"] = behavior_type
                                item["date"] = date
                                yield Yield(item, identity=True)
                            else:
                                if not resp["data"]["next_page"]:
                                    break
                                payload["offset"] += 32
                                continue
                            break
                start_time = data["list"][0]["update_time"]
            if (diff := time() - end_time) < 1:
                if async_:
                    yield async_sleep(1 - diff)
                else:
                    sleep(1 - diff)
            end_time = int(time())
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_life_behavior(
    client: str | P115Client, 
    from_time: int | float = 0, 
    from_id: int = 0, 
    interval: int | float = 0, 
    ignore_types: None | Container[int] = IGNORE_BEHAVIOR_TYPES, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_life_behavior(
    client: str | P115Client, 
    from_time: int | float = 0, 
    from_id: int = 0, 
    interval: int | float = 0, 
    ignore_types: None | Container[int] = IGNORE_BEHAVIOR_TYPES, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_life_behavior(
    client: str | P115Client, 
    from_time: int | float = 0, 
    from_id: int = 0, 
    interval: int | float = 0, 
    ignore_types: None | Container[int] = IGNORE_BEHAVIOR_TYPES, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> AsyncIterator[dict] | Iterator[dict]:
    """持续拉取 115 生活事件

    .. caution::
        115 并没有收集 复制文件 和 文件改名 的事件，以及第三方上传可能会没有 上传事件 ("upload_image_file" 和 "upload_file")

    :param client: 115 客户端或 cookies
    :param from_time: 开始时间（含），若为 0 则从当前时间开始，若小于 0 则从最早开始
    :param from_id: 开始的事件 id （不含）
    :param interval: 睡眠时间间隔，如果小于等于 0，则不睡眠
    :param ignore_types: 忽略的事件类型
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生 115 生活事件日志数据字典
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if app in ("web", "desktop", "harmony"):
        life_behavior_detail = partial(client.life_behavior_detail, **request_kwargs)
    else:
        life_behavior_detail = partial(client.life_behavior_detail_app, app=app, **request_kwargs)
    first_limit = 64
    def gen_step():
        nonlocal from_time, from_id
        if from_time == 0:
            from_time = time()
        seen: set[str] = set()
        seen_add = seen.add
        while True:
            seen.clear()
            offset = 0
            resp = yield life_behavior_detail({"limit": first_limit}, async_=async_)
            events = check_response(resp)["data"]["list"]
            if not events:
                continue
            new_from_id = int(events[0]["id"])
            if from_id == new_from_id:
                continue
            new_from_time = int(events[0]["update_time"])
            offset = first_limit
            while True:
                for event in events:
                    if ignore_types and event["type"] in ignore_types:
                        continue
                    if int(event["id"]) == from_id or int(event["update_time"]) < from_time:
                        break
                    fid = event["file_id"]
                    if fid not in seen:
                        yield Yield(event, identity=True)
                        seen_add(fid)
                else:
                    if interval > 0:
                        if async_:
                            yield async_sleep(interval)
                        else:
                            sleep(interval)
                    resp = yield life_behavior_detail({"limit": 1000, "offset": offset}, async_=async_)
                    events = check_response(resp)["data"]["list"]
                    offset += 1000
                    continue
                from_id = new_from_id
                from_time = new_from_time
                break
    return run_gen_step_iter(gen_step, async_=async_)

