#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "ID_TO_DIRNODE_CACHE", "type_of_attr", "traverse_stared_dirs", "ensure_attr_path", 
    "iterdir_raw", "iterdir", "iter_files", "iter_files_raw", "dict_files", "traverse_files", 
    "iter_dupfiles", "dict_dupfiles", "iter_image_files", "dict_image_files", 
]

import errno

from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable, Collection, Coroutine, Iterable, Iterator
from itertools import chain, islice
from operator import itemgetter
from typing import cast, overload, Any, Final, Literal, NamedTuple, TypeVar
from warnings import warn

from asynctools import async_filter, async_map, to_list
from iterutils import run_gen_step, run_gen_step_iter, through, async_through, Yield, YieldFrom
from dictattr import AttrDict
from httpx import ReadTimeout
from iter_collect import grouped_mapping, grouped_mapping_async, iter_keyed_dups, iter_keyed_dups_async, SupportsLT
from p115client import check_response, normalize_attr, P115Client, P115OSError, P115Warning
from p115client.const import CLASS_TO_TYPE, SUFFIX_TO_TYPE
from posixpatht import escape, splitext


D = TypeVar("D", bound=dict)
K = TypeVar("K")

#: 用于缓存每个用户（根据用户 id 区别）的每个目录 id 到所对应的 (名称, 父id) 的元组的字典的字典
ID_TO_DIRNODE_CACHE: Final[defaultdict[int, dict[int, DirNode]]] = defaultdict(dict)


class DirNode(NamedTuple):
    name: str
    parent_id: int = 0


def type_of_attr(attr: dict, /) -> int:
    """推断文件信息所属类型（试验版，未必准确）

    :param attr: 文件信息

    :return: 返回类型代码

        - 0: 目录
        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 其它文件
"""
    if attr["is_directory"]:
        return 0
    type: None | int
    if type := CLASS_TO_TYPE.get(attr.get("class", "")):
        return type
    if type := SUFFIX_TO_TYPE.get(splitext(attr["name"])[1].lower()):
        return type
    if "video_type" in attr:
        return 4
    if attr.get("thumb"):
        return 2
    return 99


@overload
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param payload: 请求参数，如果是 int 或 str，则视为 cid
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param only_dirs: 仅罗列目录
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if isinstance(payload, (str, int)):
        cid = int(payload)
        payload = {"cid": payload, "offset": 0}
    else:
        cid = int(payload.setdefault("cid", 0))
    if only_dirs:
        payload["fc_mix"] = 0
        payload["show_dir"] = 1
        payload["count_folders"] = 1
        key_of_count = "folder_count"
    else:
        key_of_count = "count"
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    ans: list[tuple[int, str]] = []
    def gen_step():
        nonlocal ans
        offset = int(payload.setdefault("offset", 0))
        if offset < 0:
            offset = payload["offset"] = 0
        count = 0
        while True:
            resp = yield client.fs_files(payload, async_=async_, **request_kwargs)
            check_response(resp)
            if int(resp["path"][-1]["cid"]) != cid:
                raise FileNotFoundError(errno.ENOENT, cid)
            cur_ans = [(0, "")]
            for info in resp["path"][1:]:
                pid, name = int(info["cid"]), info["name"]
                id_to_dirnode[pid] = DirNode(name, int(info["pid"]))
                cur_ans.append((pid, "name"))
            if ans and ans != cur_ans:
                warn(f"cid={cid} ancestors changed: {ans} -> {cur_ans}", category=P115Warning)
            if count == 0:
                count = int(resp.get(key_of_count) or 0)
            elif count != int(resp.get(key_of_count) or 0):
                message = f"cid={cid} detected count changes during iteration: {count} -> {resp['count']}"
                if raise_for_changed_count:
                    raise P115OSError(errno.EIO, message)
                else:
                    warn(message, category=P115Warning)
                count = int(resp.get(key_of_count) or 0)
            if not count or offset != resp["offset"]:
                return
            for info in resp["data"]:
                if "pid" in info:
                    id_to_dirnode[int(info["cid"])] = DirNode(info["n"], int(info["pid"]))
                elif only_dirs:
                    return
                yield Yield(info, identity=True)
            offset += len(resp["data"])
            if offset >= count:
                return
            payload["offset"] = offset
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def traverse_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    find_ids: None | Iterable[int] = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict]:
    ...
@overload
def traverse_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    find_ids: None | Iterable[int] = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[AttrDict]:
    ...
def traverse_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    find_ids: None | Iterable[int] = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict] | AsyncIterator[AttrDict]:
    """遍历以迭代获得所有被打上星标的目录信息

    :param client: 115 客户端或 cookies
    :param page_size: 分页大小
    :param find_ids: 需要寻找的 id 集合
        如果为 None 或空，则拉取所有打星标的文件夹；否则当找到所有这些 id 时，
        如果之前的迭代过程中获取到其它 id 都已存在于 id_to_dirnode 就立即终止，否则就拉取所有打星标的文件夹。
        如果从网上全部拉取完，还有一些在 find_ids 中的 id 没被看到，则报错 RuntimeError。
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，被打上星标的目录信息
    """
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    payload = {
        "asc": asc, "cid": 0, "count_folders": 1, "cur": 0, "fc_mix": 0, "limit": page_size, 
        "o": order, "offset": 0, "show_dir": 1, "star": 1, 
    }
    if find_ids:
        if not isinstance(find_ids, Collection):
            find_ids = tuple(find_ids)
        need_to_find = set(find_ids)
        remove_find = need_to_find.remove
    else:
        need_to_find = None
    def gen_step():
        all_seen: bool = True
        it = _iter_fs_files(
            client, 
            payload=payload, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            only_dirs=True, 
            async_=async_, 
            **request_kwargs, 
        )
        def process(info: dict, /) -> AttrDict:
            nonlocal all_seen
            attr = normalize_attr(info)
            cid = attr["id"]
            if need_to_find and cid in need_to_find:
                remove_find(cid)
            elif cid not in id_to_dirnode:
                all_seen = False
            id_to_dirnode[cid] = DirNode(attr["name"], attr["parent_id"])
            return attr
        if async_:
            async def request():
                async for attr in async_map(process, it):
                    yield attr
                    if all_seen and not need_to_find:
                        return
                if need_to_find:
                    raise P115OSError(errno.EIO, f"unable to find these ids: {need_to_find!r}")
            yield YieldFrom(request())
        else:
            for attr in map(process, cast(Iterator, it)):
                yield Yield(attr, identity=True)
                if all_seen and not need_to_find:
                    return
            if need_to_find:
                raise P115OSError(errno.EIO, f"unable to find these ids: {need_to_find!r}")
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def ensure_attr_path(
    client: str | P115Client, 
    attrs: Iterable[D], 
    page_size: int = 10_000, 
    with_ancestors: bool = False, 
    with_path: bool = True, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Collection[D]:
    ...
@overload
def ensure_attr_path(
    client: str | P115Client, 
    attrs: Iterable[D], 
    page_size: int = 10_000, 
    with_ancestors: bool = False, 
    with_path: bool = True, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, Collection[D]]:
    ...
def ensure_attr_path(
    client: str | P115Client, 
    attrs: Iterable[D], 
    page_size: int = 10_000, 
    with_ancestors: bool = False, 
    with_path: bool = True, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Collection[D] | Coroutine[Any, Any, Collection[D]]:
    """为一组文件信息添加 "path" 字段，表示文件的路径

    :param client: 115 客户端或 cookies
    :param attrs: 一组文件信息
    :param page_size: 分页大小
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 返回这一组文件信息
    """
    if not (with_ancestors or with_path):
        raise ValueError("`with_ancestors` and `with_path` can't be False at the same time")
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    if not isinstance(attrs, Collection):
        attrs = tuple(attrs)
    if with_ancestors:
        id_to_ancestors: dict[int, list[dict]] = {}

        def get_ancestors(id: int, attr: dict | DirNode, /) -> list[dict]:
            if isinstance(attr, DirNode):
                name, pid = attr
            else:
                pid = attr["parent_id"]
                name = attr["name"]
            if pid == 0:
                ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
            else:
                if pid not in id_to_ancestors:
                    id_to_ancestors[pid] = get_ancestors(pid, id_to_dirnode[pid])
                ancestors = [*id_to_ancestors[pid]]
            ancestors.append({"id": id, "parent_id": pid, "name": name})
            return ancestors
    if with_path:
        id_to_path: dict[int, str] = {}

        def get_path(attr: dict | DirNode, /) -> str:
            if isinstance(attr, DirNode):
                name, pid = attr
            else:
                pid = attr["parent_id"]
                name = attr["name"]
            if escape is not None:
                name = escape(name)
            if pid == 0:
                return "/" + name
            elif pid in id_to_path:
                return id_to_path[pid] + name
            else:
                dirname = id_to_path[pid] = get_path(id_to_dirnode[pid]) + "/"
                return dirname + name
    walk_next: Any = anext if async_ else next
    walk_through: Any = async_through if async_ else through
    def gen_step():
        if len(id_to_dirnode) <= 10_000:
            yield walk_through(traverse_stared_dirs(
                client, 
                id_to_dirnode=id_to_dirnode, 
                async_=async_, 
                **request_kwargs, 
            ))
        pids: set[int] = set()
        for attr in attrs:
            pid = attr["parent_id"]
            if attr.get("is_directory", False):
                id_to_dirnode[attr["id"]] = DirNode(attr["name"], pid)
            if pid != 0:
                pids.add(pid)
        while pids:
            if find_ids := pids - id_to_dirnode.keys():
                if len(find_ids) <= len(id_to_dirnode) // page_size:
                    for pid in find_ids:
                        yield walk_next(iterdir(
                            client, 
                            pid, 
                            page_size=1, 
                            id_to_dirnode=id_to_dirnode, 
                            async_=async_, 
                            **request_kwargs, 
                        ), None)
                else:
                    ids_it = iter(find_ids)
                    while ids := ",".join(map(str, islice(ids_it, 10_000))):
                        yield client.fs_star_set(ids, async_=async_, **request_kwargs)
                    yield walk_through(traverse_stared_dirs(
                        client, 
                        page_size, 
                        find_ids, 
                        id_to_dirnode=id_to_dirnode, 
                        async_=async_, 
                        **request_kwargs, 
                    ))
            pids = {ppid for pid in pids if (ppid := id_to_dirnode[pid][1]) != 0}
        if with_ancestors:
            for attr in attrs:
                attr["ancestors"] = get_ancestors(attr["id"], attr)
        if with_path:
            for attr in attrs:
                attr["path"] = get_path(attr)
        return attrs
    return run_gen_step(gen_step, async_=async_)


@overload
def iterdir_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iterdir_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iterdir_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param show_dir: 展示文件夹。0: 否，1: 是
    :param fc_mix: 文件夹置顶。0: 文件夹在文件之前，1: 文件和文件夹混合并按指定排序
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param only_dirs: 仅罗列目录
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if page_size <= 0:
        page_size = 10_000
    return _iter_fs_files(
        client, 
        payload={
            "asc": asc, "cid": cid, "count_folders": 1, "fc_mix": fc_mix, "limit": page_size, 
            "show_dir": show_dir, "o": order, "offset": 0, 
        }, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        only_dirs=only_dirs, 
        async_=async_, 
        **request_kwargs, 
    )


@overload
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict]:
    ...
@overload
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[AttrDict]:
    ...
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    only_dirs: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict] | AsyncIterator[AttrDict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param show_dir: 展示文件夹。0: 否，1: 是
    :param fc_mix: 文件夹置顶。0: 文件夹在文件之前，1: 文件和文件夹混合并按指定排序
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param only_dirs: 仅罗列目录
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    def gen_step():
        it = iterdir_raw(
            client, 
            cid=cid, 
            page_size=page_size, 
            order=order, 
            asc=asc, 
            show_dir=show_dir, 
            fc_mix=fc_mix, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            only_dirs=only_dirs, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        do_map = async_map if async_ else map
        dirname = ""
        pancestors: list[dict] = []
        if with_ancestors or with_path:
            def process(info: dict, /) -> AttrDict:
                nonlocal dirname, pancestors
                attr = normalize_attr(info)
                if not pancestors:
                    cid = attr["parent_id"]
                    while cid != 0:
                        name, pid = id_to_dirnode[cid]
                        pancestors.append({"id": cid, "parent_id": pid, "name": name})
                        cid = pid
                    pancestors.append({"id": 0, "parent_id": 0, "name": ""})
                    pancestors.reverse()
                if with_ancestors:
                    attr["ancestors"] = [
                        *pancestors, 
                        {"id": attr["id"], "parent_id": attr["parent_id"], "name": attr["name"]}, 
                    ]
                if with_path:
                    if not dirname:
                        if escape is None:
                            dirname = "/".join(info["name"] for info in pancestors) + "/"
                        else:
                            dirname = "/".join(escape(info["name"]) for info in pancestors) + "/"
                    name = attr["name"]
                    if escape is not None:
                        name = escape(name)
                    attr["path"] = dirname + name
                return attr
            yield YieldFrom(do_map(process, it), identity=True) # type: ignore
        else:
            yield YieldFrom(do_map(normalize_attr, it), identity=True) # type: ignore
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_files_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_files_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_files_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历目录树，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    suffix = suffix.strip(".")
    if not (type or suffix):
        raise ValueError("please set the non-zero value of suffix or type")
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    return _iter_fs_files(
        client, 
        payload={
            "asc": asc, "cid": cid, "count_folders": 0, "cur": cur, "limit": page_size, 
            "o": order, "offset": 0, "show_dir": 0, "suffix": suffix, "type": type, 
        }, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, 
        **request_kwargs, 
    )


@overload
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict]:
    ...
@overload
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[AttrDict]:
    ...
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict] | AsyncIterator[AttrDict]:
    """遍历目录树，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    if with_ancestors or with_path:
        cache: list[AttrDict] = []
        add_to_cache = cache.append
    if with_ancestors:
        id_to_ancestors: dict[int, list[dict]] = {}

        def get_ancestors(id: int, attr: dict | DirNode, /) -> list[dict]:
            if isinstance(attr, DirNode):
                name, pid = attr
            else:
                pid = attr["parent_id"]
                name = attr["name"]
            if pid == 0:
                ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
            else:
                if pid not in id_to_ancestors:
                    id_to_ancestors[pid] = get_ancestors(pid, id_to_dirnode[pid])
                ancestors = [*id_to_ancestors[pid]]
            ancestors.append({"id": id, "parent_id": pid, "name": name})
            return ancestors
    if with_path:
        id_to_path: dict[int, str] = {}

        def get_path(attr: dict | DirNode, /) -> str:
            if isinstance(attr, DirNode):
                name, pid = attr
            else:
                pid = attr["parent_id"]
                name = attr["name"]
            if escape is not None:
                name = escape(name)
            if pid == 0:
                return "/" + name
            elif pid in id_to_path:
                return id_to_path[pid] + name
            else:
                dirname = id_to_path[pid] = get_path(id_to_dirnode[pid]) + "/"
                return dirname + name
    def gen_step():
        it = iter_files_raw(
            client, 
            cid=cid, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            order=order, 
            asc=asc, 
            cur=cur, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        do_map = async_map if async_ else map
        if with_path or with_ancestors:
            do_filter = async_filter if async_ else filter
            def process(info):
                attr = normalize_attr(info)
                try:
                    if with_ancestors:
                        attr["ancestors"] = get_ancestors(attr["id"], attr)
                    if with_path:
                        attr["path"] = get_path(attr)
                except KeyError:
                    add_to_cache(attr)
                else:
                    return attr
            yield YieldFrom(do_filter(bool, do_map(process, it)), identity=True) # type: ignore
        else:
            yield YieldFrom(do_map(normalize_attr, it), identity=True) # type: ignore
        if (with_ancestors or with_path) and cache:
            yield YieldFrom(ensure_attr_path(
                client, 
                cache, 
                page_size=page_size, 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                escape=escape, 
                id_to_dirnode=id_to_dirnode, 
                async_=async_, 
                **request_kwargs, 
            ))
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def dict_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[int, AttrDict]:
    ...
@overload
def dict_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[int, AttrDict]]:
    ...
def dict_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[int, AttrDict] | Coroutine[Any, Any, dict[int, AttrDict]]:
    """获取一个目录内的所有文件信息

    :param client: 115 客户端或 cookies
    :param cid: 待被遍历的目录 id，默认为根目录
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是 id，value 是 文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        it = iter_files(
            client, 
            cid, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            order=order, 
            asc=asc, 
            cur=cur, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        if async_:
            async def request():
                return {attr["id"]: attr async for attr in it} # type: ignore
            id_to_attr: dict[int, AttrDict] = yield request
        else:
            id_to_attr = {attr["id"]: attr for attr in it}
        if with_ancestors or with_path:
            yield ensure_attr_path(
                client, 
                id_to_attr.values(), 
                page_size=page_size, 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                escape=escape, 
                id_to_dirnode=id_to_dirnode, 
                async_=async_, # type: ignore
                **request_kwargs, 
            )
        return id_to_attr
    return run_gen_step(gen_step, async_=async_)


@overload
def traverse_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict]:
    ...
@overload
def traverse_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[AttrDict]:
    ...
def traverse_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[AttrDict] | AsyncIterator[AttrDict]:
    """遍历目录树，获取文件信息（会根据统计信息，分解任务）

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param auto_splitting_tasks: 是否根据统计信息自动拆分任务
    :param auto_splitting_threshold: 如果 `auto_splitting_tasks` 为 True，且目录内的文件数大于 `auto_splitting_threshold`，则分拆此任务到它的各个直接子目录，否则批量拉取
    :param auto_splitting_statistics_timeout: 如果执行统计超过此时间，则立即终止，并认为文件是无限多
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    if not auto_splitting_tasks:
        return iter_files(
            client, 
            cid, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            with_ancestors=with_ancestors, 
            with_path=with_path, 
            escape=escape, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
    suffix = suffix.strip(".")
    if not (type or suffix):
        raise ValueError("please set the non-zero value of suffix or type")
    if suffix:
        suffix = "." + suffix.lower()
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if auto_splitting_threshold < 16:
        auto_splitting_threshold = 16
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    dq: deque[int] = deque()
    get, put = dq.pop, dq.appendleft
    put(cid)
    def gen_step():
        while dq:
            try:
                if cid := get():
                    # NOTE: 必要时也可以根据不同的扩展名进行分拆任务，通过 client.fs_files_second_type({"cid": cid, "type": type}) 获取目录内所有的此种类型的扩展名，并且如果响应为空时，则直接退出
                    try:
                        payload = {
                            "asc": 1, "cid": cid, "cur": 0, "limit": 16, "o": "user_ptime", "offset": 0, 
                            "show_dir": 0, "suffix": suffix, "type": type, 
                        }
                        resp = check_response((yield client.fs_files(payload, async_=async_, **{
                            **request_kwargs, 
                            "timeout": auto_splitting_statistics_timeout, 
                        })))
                        if int(resp["path"][-1]["cid"]) != cid:
                            continue
                        for info in resp["path"][1:]:
                            id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
                    except ReadTimeout:
                        file_count = float("inf")
                    else:
                        file_count = int(resp.get("count") or 0)
                    if file_count <= auto_splitting_threshold:
                        if file_count <= 16:
                            attrs = map(normalize_attr, resp["data"])
                            if with_ancestors or with_path:
                                attrs = yield ensure_attr_path(
                                    client, 
                                    attrs, 
                                    page_size=page_size, 
                                    with_ancestors=with_ancestors, 
                                    with_path=with_path, 
                                    escape=escape, 
                                    id_to_dirnode=id_to_dirnode, 
                                    async_=async_, 
                                    **request_kwargs, 
                                )
                            yield YieldFrom(attrs, identity=True)
                        else:
                            yield YieldFrom(iter_files(
                                client, 
                                cid, 
                                page_size=page_size, 
                                suffix=suffix, 
                                type=type, 
                                with_ancestors=with_ancestors, 
                                with_path=with_path, 
                                escape=escape, 
                                id_to_dirnode=id_to_dirnode, 
                                raise_for_changed_count=raise_for_changed_count, 
                                async_=async_, 
                                **request_kwargs, 
                            ))
                        continue
                it = iterdir(
                    client, 
                    cid, 
                    page_size=page_size, 
                    with_ancestors=with_ancestors, 
                    with_path=with_path, 
                    escape=escape, 
                    id_to_dirnode=id_to_dirnode, 
                    raise_for_changed_count=raise_for_changed_count, 
                    async_=async_, 
                    **request_kwargs, 
                )
                if async_:
                    it = yield to_list(it)
                for attr in cast(Iterable, it):
                    if attr.get("is_directory", False):
                        put(attr["id"])
                    else:
                        ext = splitext(attr["name"])[1].lower()
                        if suffix:
                            if suffix != ext:
                                continue
                        elif 0 < type <= 7 and type_of_attr(attr) != type:
                            continue
                        yield attr
            except FileNotFoundError:
                pass
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[tuple[K, AttrDict]]:
    ...
@overload
def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[tuple[K, AttrDict]]:
    ...
def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[tuple[K, AttrDict]] | AsyncIterator[tuple[K, AttrDict]]:
    """遍历以迭代获得所有重复文件

    :param client: 115 客户端或 cookies
    :param cid: 待被遍历的目录 id，默认为根目录
    :param key: 函数，用来给文件分组，当多个文件被分配到同一组时，它们相互之间是重复文件关系
    :param keep_first: 保留某个重复文件不输出，除此以外的重复文件都输出

        - 如果为 None，则输出所有重复文件（不作保留）
        - 如果是 Callable，则保留值最小的那个文件
        - 如果为 True，则保留最早入组的那个文件
        - 如果为 False，则保留最晚入组的那个文件

    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param auto_splitting_tasks: 是否根据统计信息自动拆分任务
    :param auto_splitting_threshold: 如果 `auto_splitting_tasks` 为 True，且目录内的文件数大于 `auto_splitting_threshold`，则分拆此任务到它的各个直接子目录，否则批量拉取
    :param auto_splitting_statistics_timeout: 如果执行统计超过此时间，则立即终止，并认为文件是无限多
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回 key 和 重复文件信息 的元组
    """
    it: Iterator[AttrDict] | AsyncIterator[AttrDict] = traverse_files(
        client, 
        cid, 
        page_size=page_size, 
        suffix=suffix, 
        type=type, 
        auto_splitting_tasks=auto_splitting_tasks, 
        auto_splitting_threshold=auto_splitting_threshold, 
        auto_splitting_statistics_timeout=auto_splitting_statistics_timeout, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, # type: ignore
        **request_kwargs, 
    )
    if async_:
        it = cast(AsyncIterator[AttrDict], it)
        return iter_keyed_dups_async(
            it, 
            key=key, 
            keep_first=keep_first, 
        )
    else:
        it = cast(Iterator[AttrDict], it)
        return iter_keyed_dups(
            it, 
            key=key, 
            keep_first=keep_first, 
        )


@overload
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[K, list[AttrDict]] | Coroutine[Any, Any, dict[K, list[AttrDict]]]:
    ...
@overload
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[K, list[AttrDict]]]:
    ...
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[K, list[AttrDict]] | Coroutine[Any, Any, dict[K, list[AttrDict]]]:
    """遍历以迭代获得所有重复文件的分组字典

    :param client: 115 客户端或 cookies
    :param cid: 待被遍历的目录 id，默认为根目录
    :param key: 函数，用来给文件分组，当多个文件被分配到同一组时，它们相互之间是重复文件关系
    :param keep_first: 保留某个重复文件不输出，除此以外的重复文件都输出

        - 如果为 None，则输出所有重复文件（不作保留）
        - 如果是 Callable，则保留值最小的那个文件
        - 如果为 True，则保留最早入组的那个文件
        - 如果为 False，则保留最晚入组的那个文件

    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param auto_splitting_tasks: 是否根据统计信息自动拆分任务
    :param auto_splitting_threshold: 如果 `auto_splitting_tasks` 为 True，且目录内的文件数大于 `auto_splitting_threshold`，则分拆此任务到它的各个直接子目录，否则批量拉取
    :param auto_splitting_statistics_timeout: 如果执行统计超过此时间，则立即终止，并认为文件是无限多
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是分组的 key，value 是归属这一组的文件信息列表
    """
    def gen_step():
        it: Iterator[tuple[K, AttrDict]] | AsyncIterator[tuple[K, AttrDict]] = iter_dupfiles(
            client, 
            cid, 
            key=key, 
            keep_first=keep_first, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            auto_splitting_tasks=auto_splitting_tasks, 
            auto_splitting_threshold=auto_splitting_threshold, 
            auto_splitting_statistics_timeout=auto_splitting_statistics_timeout, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        if async_:
            it = cast(AsyncIterator[tuple[K, AttrDict]], it)          
            dups: dict[K, list[AttrDict]] = yield grouped_mapping_async(it)
        else:
            it = cast(Iterator[tuple[K, AttrDict]], it)
            dups = grouped_mapping(it)
        if with_ancestors or with_path:
            yield ensure_attr_path(
                client, 
                chain.from_iterable(dups.values()), 
                page_size=page_size, 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                escape=escape, 
                id_to_dirnode=id_to_dirnode, 
                async_=async_, # type: ignore
                **request_kwargs, 
            )
        return dups
    return run_gen_step(gen_step, async_=async_)


@overload
def iter_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历目录树，获取图片文件信息（包含图片的 CDN 链接）

    .. tip::
        这个函数的效果相当于 ``iter_files(client, cid, type=2, ...)`` 所获取的文件列表，只是返回信息有些不同，速度似乎还是 ``iter_files`` 更快

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的图片文件信息
    """
    def normalize(attr: dict, /):
        for key, val in attr.items():
            if key.endswith(("_id", "_type", "_size", "time")) or key.startswith("is_") or val in "01":
                attr[key] = int(val)
        attr["id"] = attr["file_id"]
        attr["name"] = attr["file_name"]
        return attr
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 8192
    elif page_size < 16:
        page_size = 16
    payload = {"asc": asc, "cid": cid, "cur": cur, "limit": page_size, "o": order, "offset": 0}
    def gen_step():
        offset = 0
        count = 0
        while True:
            resp = check_response((yield client.fs_imglist_app(payload, async_=async_, **request_kwargs)))
            if int(resp["cid"]) != cid:
                raise FileNotFoundError(errno.ENOENT, cid)
            if count == 0:
                count = int(resp.get("count") or 0)
            elif count != int(resp.get("count") or 0):
                message = f"cid={cid} detected count changes during traversing: {count} => {resp['count']}"
                if raise_for_changed_count:
                    raise P115OSError(errno.EIO, message)
                else:
                    warn(message, category=P115Warning)
                count = int(resp.get("count") or 0)
            if offset != resp["offset"]:
                break
            yield YieldFrom(map(normalize, resp["data"]), identity=True)
            offset += len(resp["data"])
            if offset >= count:
                break
            payload["offset"] = offset
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def dict_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[int, dict]:
    ...
@overload
def dict_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[int, dict]]:
    ...
def dict_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[int, dict] | Coroutine[Any, Any, dict[int, dict]]:
    """获取一个目录内的所有图片文件信息（包含图片的 CDN 链接）

    .. tip::
        这个函数的效果相当于 ``dict_files(client, cid, type=2, ...)`` 所获取的文件列表，只是返回信息有些不同，速度似乎还是 ``dict_files`` 更快

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是 id，value 是 图片文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        it = iter_image_files(
            client, 
            cid, 
            page_size=page_size, 
            order=order, 
            asc=asc, 
            cur=cur, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, 
            **request_kwargs, 
        )
        if async_:
            async def request():
                return {attr["id"]: attr async for attr in it} # type: ignore
            d: dict[int, dict] = yield request
        else:
            d = {attr["id"]: attr for attr in it} # type: ignore
        if with_ancestors or with_path:
            yield ensure_attr_path(
                client, 
                d.values(), 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                escape=escape, 
                id_to_dirnode=id_to_dirnode, 
                async_=async_, # type: ignore
                **request_kwargs, 
            )
        return d
    return run_gen_step(gen_step, async_=async_)

