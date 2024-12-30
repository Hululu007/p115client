#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "ID_TO_DIRNODE_CACHE", "P115ID", "unescape_115_charref", "type_of_attr", "get_path_to_cid", 
    "get_ancestors_to_cid", "get_id_to_path", "get_id_to_sha1", "get_id_to_pickcode", "filter_na_ids", 
    "iter_stared_dirs_raw", "iter_stared_dirs", "ensure_attr_path", "iterdir_raw", "iterdir", 
    "iter_files", "iter_files_raw", "dict_files", "traverse_files", "iter_dupfiles", "dict_dupfiles", 
    "iter_image_files", "dict_image_files", "iter_dangling_files", "share_extract_payload", 
    "share_iterdir", "share_iter_files", 
]
__doc__ = "这个模块提供了一些和目录信息罗列有关的函数"

import errno

from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable, Collection, Coroutine, Iterable, Iterator, Mapping, Sequence
from functools import partial
from itertools import chain, count, islice, takewhile
from operator import itemgetter
from re import compile as re_compile
from string import hexdigits
from time import time
from typing import cast, overload, Any, Final, Literal, NamedTuple, TypedDict, TypeVar
from warnings import warn

from asynctools import async_filter, async_map, to_list
from iterutils import async_foreach, run_gen_step, run_gen_step_iter, through, async_through, Yield, YieldFrom
from iter_collect import grouped_mapping, grouped_mapping_async, iter_keyed_dups, iter_keyed_dups_async, SupportsLT
from p115client import check_response, normalize_attr, DataError, P115Client, P115OSError, P115Warning
from p115client.const import CLASS_TO_TYPE, SUFFIX_TO_TYPE
from p115client.type import P115DictAttrLike
from posixpatht import escape, path_is_dir_form, splitext, splits

from .edit import update_desc, update_star


D = TypeVar("D", bound=dict)
K = TypeVar("K")

CRE_SHARE_LINK_search1 = re_compile(r"(?:/s/|share\.115\.com/)(?P<share_code>[a-z0-9]+)\?password=(?:(?P<receive_code>[a-z0-9]{4}))?").search
CRE_SHARE_LINK_search2 = re_compile(r"(?P<share_code>[a-z0-9]+)(?:-(?P<receive_code>[a-z0-9]{4}))?").search
CRE_115_CHARREF_sub = re_compile("\\[\x02([0-9]+)\\]").sub


class DirNode(NamedTuple):
    name: str
    parent_id: int


class OverviewAttr(NamedTuple):
    is_dir: bool
    id: int
    parent_id: int
    name: str
    ctime: int
    mtime: int


# TODO: 支持用 sqlite 作为缓存，实现一个 SqliteDefaultDict
#: 用于缓存每个用户（根据用户 id 区别）的每个目录 id 到所对应的 (名称, 父id) 的元组的字典的字典
ID_TO_DIRNODE_CACHE: Final[defaultdict[int, dict[int, tuple[str, int] | DirNode]]] = defaultdict(dict)


class SharePayload(TypedDict):
    share_code: str
    receive_code: None | str


def _overview_attr(info: Mapping, /) -> OverviewAttr:
    if "n" in info:
        is_dir = "fid" not in info
        name = info["n"]
        if is_dir:
            id = int(info["cid"])
            pid = int(info["pid"])
        else:
            id = int(info["fid"])
            pid = int(info["cid"])
        ctime = int(info["tp"])
        mtime = int(info["te"])
    elif "fn" in info:
        is_dir = info["fc"] == "0"
        name = info["fn"]
        id = int(info["fid"])
        pid = int(info["pid"])
        ctime = int(info["uppt"])
        mtime = int(info["upt"])
    elif "file_category" in info:
        is_dir = int(info["file_category"]) == 0
        if is_dir:
            name = info["category_name"]
            id = int(info["category_id"])
            pid = int(info["parent_id"])
            ctime = int(info["pptime"])
            mtime = int(info["ptime"])
        else:
            name = info["file_name"]
            id = int(info["file_id"])
            pid = int(info["category_id"])
            ctime = int(info["user_pptime"])
            mtime = int(info["user_ptime"])
    else:
        raise ValueError(f"can't overview attr data: {info!r}")
    return OverviewAttr(is_dir, id, pid, name, ctime, mtime)


def unescape_115_charref(s: str, /) -> str:
    """对 115 的字符引用进行解码

    :example:

        .. code:: python

            unescape_115_charref("[\x02128074]0号：优质资源") == "👊0号：优质资源"
    """
    return CRE_115_CHARREF_sub(lambda a: chr(int(a[1])), s)


def type_of_attr(attr: Mapping, /) -> int:
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
    if attr.get("is_directory") or attr.get("is_dir"):
        return 0
    type: None | int
    if type := CLASS_TO_TYPE.get(attr.get("class", "")):
        return type
    if type := SUFFIX_TO_TYPE.get(splitext(attr["name"])[1].lower()):
        return type
    if attr.get("is_video") or "defination" in attr:
        return 4
    return 99


@overload
def get_path_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    root_id: None | int = None, 
    escape: None | Callable[[str], str] = escape, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> str:
    ...
@overload
def get_path_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    root_id: None | int = None, 
    escape: None | Callable[[str], str] = escape, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, str]:
    ...
def get_path_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    root_id: None | int = None, 
    escape: None | Callable[[str], str] = escape, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> str | Coroutine[Any, Any, str]:
    """获取目录对应的路径（绝对路径或相对路径）

    :param client: 115 客户端或 cookies
    :param cid: 目录的 id
    :param root_id: 根目录 id，如果指定此参数且不为 None，则返回相对路径，否则返回绝对路径
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param refresh: 是否刷新。如果为 True，则会执行网络请求以查询；如果为 False，则直接从 `id_to_dirnode` 中获取
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 目录对应的绝对路径或相对路径
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    def gen_step():
        nonlocal cid
        parts: list[str] = []
        if cid and (refresh or cid not in id_to_dirnode):
            resp = yield client.fs_files_app({"cid": cid, "hide_data": 1}, async_=async_, **request_kwargs)
            check_response(resp)
            if cid and int(resp["path"][-1]["cid"]) != cid:
                raise FileNotFoundError(errno.ENOENT, cid)
            parts.extend(info["name"] for info in resp["path"][1:])
            for info in resp["path"][1:]:
                id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
        else:
            while cid and (not root_id or cid != root_id):
                name, cid = id_to_dirnode[cid]
                parts.append(name)
            parts.reverse()
        if root_id is not None and cid != root_id:
            return ""
        if escape is None:
            path = "/".join(parts)
        else:
            path = "/".join(map(escape, parts))
        if root_id is None or root_id:
            return "/" + path
        else:
            return path
    return run_gen_step(gen_step, async_=async_)


@overload
def get_ancestors_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> list[dict]:
    ...
@overload
def get_ancestors_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, list[dict]]:
    ...
def get_ancestors_to_cid(
    client: str | P115Client, 
    cid: int = 0, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> list[dict] | Coroutine[Any, Any, list[dict]]:
    """获取目录对应的 ancestors（祖先信息列表）

    :param client: 115 客户端或 cookies
    :param cid: 目录的 id
    :param refresh: 是否刷新。如果为 True，则会执行网络请求以查询；如果为 False，则直接从 `id_to_dirnode` 中获取
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 目录所对应的祖先信息列表，每一条的结构如下

        .. code:: python

            {
                "id": int, # 目录的 id
                "parent_id": int, # 上级目录的 id
                "name": str, # 名字
            }
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    def gen_step():
        nonlocal cid
        parts: list[dict] = []
        if cid and (refresh or cid not in id_to_dirnode):
            resp = yield client.fs_files_app({"cid": cid, "hide_data": 1}, async_=async_, **request_kwargs)
            check_response(resp)
            if cid and int(resp["path"][-1]["cid"]) != cid:
                raise FileNotFoundError(errno.ENOENT, cid)
            parts.append({"id": 0, "name": "", "parent_id": 0})
            for info in resp["path"][1:]:
                id, pid, name = int(info["cid"]), int(info["pid"]), info["name"]
                id_to_dirnode[id] = DirNode(name, pid)
                parts.append({"id": id, "name": name, "parent_id": pid})
        else:
            while cid:
                id = cid
                name, cid = id_to_dirnode[cid]
                parts.append({"id": id, "name": name, "parent_id": cid})
            parts.append({"id": 0, "name": "", "parent_id": 0})
            parts.reverse()
        return parts
    return run_gen_step(gen_step, async_=async_)


class P115ID(P115DictAttrLike, int):

    def __str__(self, /) -> str:
        return int.__repr__(self)


@overload
def get_id_to_path(
    client: str | P115Client, 
    path: str | Sequence[str], 
    ensure_file: None | bool = None, 
    is_posixpath: bool = False, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> int:
    ...
@overload
def get_id_to_path(
    client: str | P115Client, 
    path: str | Sequence[str], 
    ensure_file: None | bool = None, 
    is_posixpath: bool = False, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, int]:
    ...
def get_id_to_path(
    client: str | P115Client, 
    path: str | Sequence[str], 
    ensure_file: None | bool = None, 
    is_posixpath: bool = False, 
    refresh: bool = False, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> int | Coroutine[Any, Any, int]:
    """获取路径对应的 id

    :param client: 115 客户端或 cookies
    :param path: 路径
    :param ensure_file: 是否确保为文件

        - True: 必须是文件
        - False: 必须是目录
        - None: 可以是目录或文件

    :param is_posixpath: 使用 posixpath，会把 "/" 转换为 "|"，因此解析的时候，会对 "|" 进行特别处理
    :param refresh: 是否刷新。如果为 True，则会执行网络请求以查询；如果为 False，则直接从 `id_to_dirnode` 中获取
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 文件或目录的 id
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    error = FileNotFoundError(errno.ENOENT, f"no such path: {path!r}")
    def gen_step():
        nonlocal client, ensure_file
        if not isinstance(path, str):
            patht = ["", *filter(None, path)]
            if len(patht) == 1:
                return 0
            if is_posixpath:
                for i in range(1, len(patht)):
                    patht[i] = patht[i].replace("/", "|")
        elif path in (".", "..", "/"):
            if ensure_file:
                raise error
            return 0
        elif path.startswith("根目录 > "):
            patht = path.split(" > ")
            patht[0] = ""
            if is_posixpath:
                for i in range(1, len(patht)):
                    patht[i] = patht[i].replace("/", "|")
        elif is_posixpath:
            if ensure_file is None and path.endswith("/"):
                ensure_file = False
            patht = ["", *filter(None, path.split("/"))]
        else:
            if ensure_file is None and path_is_dir_form(path):
                ensure_file = False
            patht, _ = splits("/" + path)
        if len(patht) == 1:
            if ensure_file:
                raise error
            return 0
        stop = len(patht) - bool(ensure_file)
        obj = "|" if is_posixpath else "/"
        for i in range(stop):
            if obj in patht[i]:
                break
        else:
            i += 1
        j = 1
        pid = 0
        if stop > 1 and not refresh and id_to_dirnode:
            if stop == 2:
                if is_posixpath:
                    needle = (patht[1].replace("/", "|"), pid)
                else:
                    needle = (patht[1], pid)
                for k, t in id_to_dirnode.items():
                    if is_posixpath:
                        t = (t[0].replace("/", "|"), t[1])
                    if t == needle:
                        pid = k
                        j = 2
            else:
                if is_posixpath:
                    table = {(n.replace("/", "|"), pid): k for k, (n, pid) in id_to_dirnode.items()}
                else:
                    table = {cast(tuple[str, int], tuple(t)): k for k, t in id_to_dirnode.items()}
                try:
                    for j in range(1, stop):
                        if is_posixpath:
                            needle = (patht[j].replace("/", "|"), pid)
                        else:
                            needle = (patht[j], pid)
                        pid = table[needle]
                    j += 1
                except KeyError:
                    pass
        if j >= i:
            i = j
            cid = pid
        else:
            if ensure_file and len(patht) == i:
                i -= 1
            if app in ("", "web", "desktop", "harmony"):
                fs_dir_getid: Callable = client.fs_dir_getid
            else:
                fs_dir_getid = partial(client.fs_dir_getid_app, app=app)
            cid = 0
            while i > 1:
                dirname = "/".join(patht[:i])
                resp = yield fs_dir_getid(dirname, async_=async_, **request_kwargs)
                if not (resp["state"] and (cid := resp["id"])):
                    if len(patht) == i and ensure_file is None:
                        ensure_file = True
                        i -= 1
                        continue
                    raise error
                cid = int(cid)
                if not refresh and cid not in id_to_dirnode:
                    yield get_path_to_cid(client, cid, id_to_dirnode=id_to_dirnode, async_=async_, **request_kwargs)
                break
        if len(patht) == i:
            return cid
        for name in patht[i:-1]:
            if async_:
                async def request():
                    nonlocal cid
                    async for info in iterdir_raw(
                        client, 
                        cid, 
                        ensure_file=False, 
                        app=app, 
                        id_to_dirnode=id_to_dirnode, 
                        async_=True, 
                        **request_kwargs, 
                    ):
                        attr = _overview_attr(info)
                        if (attr.name.replace("/", "|") if is_posixpath else attr.name) == name:
                            cid = attr.id
                            break
                    else:
                        raise error
                yield request
            else:
                for info in iterdir_raw(
                    client, 
                    cid, 
                    ensure_file=False, 
                    app=app, 
                    id_to_dirnode=id_to_dirnode, 
                    **request_kwargs, 
                ):
                    attr = _overview_attr(info)
                    if (attr.name.replace("/", "|") if is_posixpath else attr.name) == name:
                        cid = attr.id
                        break
                else:
                    raise error
        name = patht[-1]
        if async_:
            async def request():
                async for info in iterdir_raw(
                    client, 
                    cid, 
                    app=app, 
                    id_to_dirnode=id_to_dirnode, 
                    async_=True, 
                    **request_kwargs, 
                ):
                    attr = _overview_attr(info)
                    if (attr.name.replace("/", "|") if is_posixpath else attr.name) == name:
                        if ensure_file:
                            if not attr.is_dir:
                                return P115ID(attr.id, info, about="path")
                        elif attr.is_dir:
                            return P115ID(attr.id, info, about="path")
                else:
                    raise error
            return (yield request)
        else:
            for info in iterdir_raw(
                client, 
                cid, 
                app=app, 
                id_to_dirnode=id_to_dirnode, 
                **request_kwargs, 
            ):
                attr = _overview_attr(info)
                if (attr.name.replace("/", "|") if is_posixpath else attr.name) == name:
                    if ensure_file:
                        if not attr.is_dir:
                            return P115ID(attr.id, info, about="path")
                    elif attr.is_dir:
                        return P115ID(attr.id, info, about="path")
            else:
                raise error
    return run_gen_step(gen_step, async_=async_)


@overload
def get_id_to_pickcode(
    client: str | P115Client, 
    pickcode: str, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> P115ID:
    ...
@overload
def get_id_to_pickcode(
    client: str | P115Client, 
    pickcode: str, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, P115ID]:
    ...
def get_id_to_pickcode(
    client: str | P115Client, 
    pickcode: str, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> P115ID | Coroutine[Any, Any, P115ID]:
    if not 17 <= len(pickcode) <= 18 or not pickcode.isalnum():
        raise ValueError(f"bad pickcode: {pickcode!r}")
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        resp = yield client.download_url_web(pickcode, base_url=True, async_=async_, **request_kwargs)
        if file_id := resp.get("file_id"):
            msg_code = resp.get("msg_code", False)
            resp["is_dir"] = msg_code and msg_code != 50028
            return P115ID(file_id, resp, about="pickcode")
        check_response(resp)
    return run_gen_step(gen_step, async_=async_)


@overload
def get_id_to_sha1(
    client: str | P115Client, 
    sha1: str, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> P115ID:
    ...
@overload
def get_id_to_sha1(
    client: str | P115Client, 
    sha1: str, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, P115ID]:
    ...
def get_id_to_sha1(
    client: str | P115Client, 
    sha1: str, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> P115ID | Coroutine[Any, Any, P115ID]:
    if len(sha1) != 40 or sha1.strip(hexdigits):
        raise ValueError(f"bad sha1: {sha1!r}")
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        resp = yield client.fs_shasearch(sha1, base_url=True, async_=async_, **request_kwargs)
        check_response(resp)
        resp["data"]["file_sha1"] = sha1.upper()
        return P115ID(resp["data"]["file_id"], resp["data"], about="sha1")
    return run_gen_step(gen_step, async_=async_)


@overload
def filter_na_ids(
    client: str | P115Client, 
    ids: Iterable[int | str], 
    batch_size: int = 50_000, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[int]:
    ...
@overload
def filter_na_ids(
    client: str | P115Client, 
    ids: Iterable[int | str], 
    batch_size: int = 50_000, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[int]:
    ...
def filter_na_ids(
    client: str | P115Client, 
    ids: Iterable[int | str], 
    batch_size: int = 50_000, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[int] | AsyncIterator[int]:
    """找出一组 id 中无效的，所谓无效就是指不在网盘中，可能已经被删除，也可能从未存在过

    :param client: 115 客户端或 cookies
    :param ids: 一组文件或目录的 id
    :param batch_size: 批次大小，分批次，每次提交的 id 数
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，筛选出所有无效的 id
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    file_skim = client.fs_file_skim
    def gen_step():
        if isinstance(ids, Sequence):
            it: Iterator[Iterable[int | str]] = (ids[i:i+batch_size] for i in range(0, len(ids), batch_size))
        else:
            ids_it = iter(ids)
            it = takewhile(bool, (tuple(islice(ids_it, batch_size)) for _ in count()))
        for batch in it:
            resp = yield file_skim(batch, method="POST", async_=async_, **request_kwargs)
            if resp.get("error") == "文件不存在":
                yield YieldFrom(map(int, batch), identity=True)
            else:
                check_response(resp)
                yield YieldFrom(
                    set(map(int, batch)) - {int(a["file_id"]) for a in resp["data"]}, 
                    identity=True, 
                )
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    first_page_size: None | int = None, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    first_page_size: None | int = None, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def _iter_fs_files(
    client: str | P115Client, 
    payload: int | str | dict = 0, 
    first_page_size: None | int = None, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param payload: 请求参数，如果是 int 或 str，则视为 cid
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param ensure_file: 是否确保为文件

        - True: 必须是文件
        - False: 必须是目录
        - None: 可以是目录或文件

    :param app: 使用某个 app （设备）的接口
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
    page_size = payload.setdefault("limit", 10_000)
    if not isinstance(page_size, int) or page_size <= 0:
        page_size = payload["limit"] = 10_000
    if first_page_size is not None and first_page_size > 0:
        payload["limit"] = first_page_size
    key_of_count = "count"
    if ensure_file:
        payload["show_dir"] = 0
        if not (payload.get("suffix") or payload.get("type")):
            payload.setdefault("cur", 1)
    elif ensure_file is False:
        payload["fc_mix"] = 0
        payload["show_dir"] = 1
        payload["count_folders"] = 1
        key_of_count = "folder_count"
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    ans: list[tuple[int, str]] = []
    if app in ("", "web", "desktop", "harmony"):
        fs_files: Callable = client.fs_files
    else:
        fs_files = partial(client.fs_files_app, app=app)
    if payload.get("type") == 99:
        payload.pop("type", None)
        payload.setdefault("show_dir", 0)
    def gen_step():
        nonlocal ans
        offset = int(payload.setdefault("offset", 0))
        if offset < 0:
            offset = payload["offset"] = 0
        count = 0
        while True:
            try:
                resp = yield fs_files(payload, async_=async_, **request_kwargs)
                break
            except DataError:
                if payload["limit"] <= 1150:
                    raise
                payload["limit"] -= 1000
                if payload["limit"] < 1150:
                    payload["limit"] = 1150
        payload["limit"] = page_size
        while True:
            check_response(resp)
            if cid and int(resp["path"][-1]["cid"]) != cid:
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
            if not count and not len(resp["data"]) or offset != resp["offset"]:
                return
            for info in resp["data"]:
                attr = _overview_attr(info)
                if attr.is_dir:
                    id_to_dirnode[attr.id] = DirNode(attr.name, attr.parent_id)
                elif ensure_file is False:
                    return
                yield Yield(info, identity=True)
            offset += len(resp["data"])
            if count and offset >= count or offset >= resp["count"]:
                return
            payload["offset"] = offset
            if count and (diff := count - offset) < page_size:
                payload["limit"] = diff
            while True:
                try:
                    resp = yield fs_files(payload, async_=async_, **request_kwargs)
                    break
                except DataError:
                    if payload["limit"] <= 1150:
                        raise
                    payload["limit"] -= 1000
                    if payload["limit"] < 1150:
                        payload["limit"] = 1150
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_stared_dirs_raw(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_stared_dirs_raw(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_stared_dirs_raw(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历以迭代获得所有被打上星标的目录信息

    :param client: 115 客户端或 cookies
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
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
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，被打上星标的目录信息
    """
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    payload = {
        "asc": asc, "cid": 0, "count_folders": 1, "cur": 0, "fc_mix": 0, "limit": page_size, 
        "o": order, "offset": 0, "show_dir": 1, "star": 1, 
    }
    return _iter_fs_files(
        client, 
        payload=payload, 
        first_page_size=first_page_size, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        ensure_file=False, 
        app=app, 
        async_=async_, 
        **request_kwargs, 
    )


@overload
def iter_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历以迭代获得所有被打上星标的目录信息

    :param client: 115 客户端或 cookies
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，被打上星标的目录信息
    """
    do_map = async_map if async_ else map
    return do_map(normalize_attr, iter_stared_dirs_raw( # type: ignore
        client, 
        page_size=page_size, 
        first_page_size=first_page_size, 
        order=order, 
        asc=asc, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        app=app, 
        async_=async_, # type: ignore
        **request_kwargs, 
    ))


@overload
def ensure_attr_path(
    client: str | P115Client, 
    attrs: Iterable[D], 
    page_size: int = 10_000, 
    with_ancestors: bool = False, 
    with_path: bool = True, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    errors: Literal["ignore", "raise", "warn"] = "raise", 
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
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    errors: Literal["ignore", "raise", "warn"] = "raise", 
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
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    errors: Literal["ignore", "raise", "warn"] = "raise", 
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
    :param app: 使用某个 app （设备）的接口
    :param errors: 如何处理错误

        - "ignore": 忽略异常后继续
        - "raise": 抛出异常
        - "warn": 输出警告信息后继续

    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 返回这一组文件信息
    """
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
        def get_ancestors(id: int, attr: dict | tuple[str, int] | DirNode, /) -> list[dict]:
            if isinstance(attr, (DirNode, tuple)):
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
        def get_path(attr: dict | tuple[str, int] | DirNode, /) -> str:
            if isinstance(attr, (DirNode, tuple)):
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
        if not id_to_dirnode:
            try:
                yield walk_through(iter_stared_dirs_raw(
                    client, 
                    id_to_dirnode=id_to_dirnode, 
                    app=app, 
                    async_=async_, 
                    **request_kwargs, 
                ))
            except Exception as e:
                match errors:
                    case "raise":
                        raise
                    case "warn":
                        warn(f"{type(e).__module__}.{type(e).__qualname__}: {e}", category=P115Warning)
        pids: set[int] = set()
        for attr in attrs:
            pid = attr["parent_id"]
            if attr.get("is_directory", False):
                id_to_dirnode[attr["id"]] = DirNode(attr["name"], pid)
            if pid:
                pids.add(pid)
        def take_while(info, /) -> bool:
            attr = _overview_attr(info)
            find_ids.discard(attr.id)
            if int(attr.mtime) < start:
                return False
            return bool(find_ids)
        start: float
        find_ids: set[int]
        while pids:
            if find_ids := pids - id_to_dirnode.keys():
                try:
                    if len(find_ids) <= len(id_to_dirnode) // page_size:
                        for pid in find_ids:
                            if pid in id_to_dirnode:
                                continue
                            yield walk_next(iterdir_raw(
                                client, 
                                pid, 
                                first_page_size=1, 
                                id_to_dirnode=id_to_dirnode, 
                                app=app, 
                                async_=async_, 
                                **request_kwargs, 
                            ), None)
                    else:
                        start = int(time())
                        ids_it = iter(find_ids)
                        while t_ids := tuple(islice(ids_it, 10_000)):
                            # NOTE: 批量给目录添加星标，这样便于把这些目录进行批量拉取
                            yield update_star(client, t_ids, async_=async_, **request_kwargs)
                            # NOTE: 批量给目录添加空备注，这样可以更新这些目录的更新时间
                            yield update_desc(client, t_ids, async_=async_, **request_kwargs)
                        yield walk_through(iter_stared_dirs_raw(
                            client, 
                            page_size, 
                            first_page_size=min(16, len(find_ids)), 
                            order="user_utime", 
                            asc=0, 
                            id_to_dirnode=id_to_dirnode, 
                            app=app, 
                            async_=async_, 
                            **request_kwargs, 
                        ), take_while=take_while)
                        if find_ids:
                            # NOTE: 首先检查一下，这些 id 中如果有已经被删除的 id，则报错
                            make_list: Callable = to_list if async_ else list
                            na_ids = yield make_list((yield filter_na_ids(client, find_ids, async_=async_, **request_kwargs)))
                            if na_ids:
                                raise P115OSError(
                                    errno.EIO, 
                                    f"these ids have been deleted: {na_ids}", 
                                )
                            warn(
                                f"unable to process these ids in bulk, back to separate processing: {find_ids}", 
                                category=P115Warning, 
                            )
                            for pid in find_ids:
                                if pid in id_to_dirnode:
                                    continue
                                yield walk_next(iterdir_raw(
                                    client, 
                                    pid, 
                                    first_page_size=1, 
                                    id_to_dirnode=id_to_dirnode, 
                                    app=app, 
                                    async_=async_, 
                                    **request_kwargs, 
                                ), None)
                except Exception as e:
                    match errors:
                        case "raise":
                            raise
                        case "warn":
                            warn(f"{type(e).__module__}.{type(e).__qualname__}: {e}", category=P115Warning)
            pids = {ppid for pid in pids if (ppid := id_to_dirnode[pid][1])}
        if with_ancestors:
            for attr in attrs:
                try:
                    attr["ancestors"] = get_ancestors(attr["id"], attr)
                except Exception as e:
                    match errors:
                        case "raise":
                            raise
                        case "warn":
                            warn(f"{type(e).__module__}.{type(e).__qualname__}: {e}", category=P115Warning)
                    attr["ancestors"] = None
        if with_path:
            for attr in attrs:
                try:
                    attr["path"] = get_path(attr)
                except Exception as e:
                    match errors:
                        case "raise":
                            raise
                        case "warn":
                            warn(f"{type(e).__module__}.{type(e).__qualname__}: {e}", category=P115Warning)
                    attr["path"] = ""
        return attrs
    return run_gen_step(gen_step, async_=async_)


@overload
def iterdir_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
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
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iterdir_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
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
    :param ensure_file: 是否确保为文件

        - True: 必须是文件
        - False: 必须是目录
        - None: 可以是目录或文件

    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if page_size <= 0:
        page_size = 10_000
    return _iter_fs_files(
        client, 
        payload={
            "asc": asc, "cid": cid, "cur": 1, "count_folders": 1, "fc_mix": fc_mix, 
            "limit": page_size, "show_dir": show_dir, "o": order, "offset": 0, 
        }, 
        first_page_size=first_page_size, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        ensure_file=ensure_file, 
        app=app, 
        async_=async_, # type: ignore
        **request_kwargs, 
    )


@overload
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    ensure_file: None | bool = None, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param ensure_file: 是否确保为文件

        - True: 必须是文件
        - False: 必须是目录
        - None: 可以是目录或文件

    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    def gen_step():
        nonlocal cid
        it = iterdir_raw(
            client, 
            cid=cid, 
            page_size=page_size, 
            first_page_size=first_page_size, 
            order=order, 
            asc=asc, 
            show_dir=show_dir, 
            fc_mix=fc_mix, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            ensure_file=ensure_file, 
            app=app, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        do_map = async_map if async_ else map
        dirname = ""
        pancestors: list[dict] = []
        if with_ancestors or with_path:
            def process(info: dict, /) -> dict:
                nonlocal dirname, pancestors
                attr = normalize_attr(info)
                if not pancestors:
                    cid = attr["parent_id"]
                    while cid:
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
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
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
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_files_raw(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    raise_for_changed_count: bool = False, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历目录树，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
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
    :param app: 使用某个 app （设备）的接口
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
    payload: dict = {
        "asc": asc, "cid": cid, "count_folders": 0, "cur": cur, "limit": page_size, 
        "o": order, "offset": 0, "show_dir": 0, 
    }
    if suffix:
        payload["suffix"] = suffix
    elif type == 99:
        payload["show_dir"] = 0
    else:
        payload["type"] = type
    return _iter_fs_files(
        client, 
        payload=payload, 
        first_page_size=first_page_size, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        app=app, 
        async_=async_, 
        **request_kwargs, 
    )


@overload
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    first_page_size: None | int = None, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """遍历目录树，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param first_page_size: 第一次拉取时的分页大小，如果为 None 或 <= 0，则自动确定
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
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
        cache: list[dict] = []
        add_to_cache = cache.append
    if with_ancestors:
        id_to_ancestors: dict[int, list[dict]] = {}

        def get_ancestors(id: int, attr: dict | tuple[str, int] | DirNode, /) -> list[dict]:
            if isinstance(attr, (DirNode, tuple)):
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

        def get_path(attr: dict | tuple[str, int] | DirNode, /) -> str:
            if isinstance(attr, (DirNode, tuple)):
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
            first_page_size=first_page_size, 
            suffix=suffix, 
            type=type, 
            order=order, 
            asc=asc, 
            cur=cur, 
            id_to_dirnode=id_to_dirnode, 
            raise_for_changed_count=raise_for_changed_count, 
            app=app, 
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
                app=app, 
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[int, dict]:
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[int, dict]]:
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[int, dict] | Coroutine[Any, Any, dict[int, dict]]:
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
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
            normalize_attr=normalize_attr, 
            id_to_dirnode=id_to_dirnode, 
            app=app, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        if async_:
            async def request():
                return {attr["id"]: attr async for attr in it} # type: ignore
            id_to_attr: dict[int, dict] = yield request
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
                app=app, 
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
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
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    from httpx import ReadTimeout

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
            normalize_attr=normalize_attr, 
            id_to_dirnode=id_to_dirnode, 
            app=app, 
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
    if app in ("", "web", "desktop", "harmony"):
        fs_files: Callable = client.fs_files
    else:
        fs_files = partial(client.fs_files_app, app=app)
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
                        resp = check_response((yield fs_files(
                            payload, 
                            async_=async_, 
                            **{
                                **request_kwargs, 
                                "timeout": auto_splitting_statistics_timeout, 
                            }, 
                        )))
                        if cid and int(resp["path"][-1]["cid"]) != cid:
                            continue
                        for info in resp["path"][1:]:
                            id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
                    except (ReadTimeout, TimeoutError):
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
                                    app=app, 
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
                                normalize_attr=normalize_attr, 
                                id_to_dirnode=id_to_dirnode, 
                                app=app, 
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
                    normalize_attr=normalize_attr, 
                    id_to_dirnode=id_to_dirnode, 
                    app=app, 
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
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[tuple[K, dict]]:
    ...
@overload
def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[tuple[K, dict]]:
    ...
def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[tuple[K, dict]] | AsyncIterator[tuple[K, dict]]:
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回 key 和 重复文件信息 的元组
    """
    it: Iterator[dict] | AsyncIterator[dict] = traverse_files(
        client, 
        cid, 
        page_size=page_size, 
        suffix=suffix, 
        type=type, 
        auto_splitting_tasks=auto_splitting_tasks, 
        auto_splitting_threshold=auto_splitting_threshold, 
        auto_splitting_statistics_timeout=auto_splitting_statistics_timeout, 
        normalize_attr=normalize_attr, 
        id_to_dirnode=id_to_dirnode, 
        app=app, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, # type: ignore
        **request_kwargs, 
    )
    if async_:
        it = cast(AsyncIterator[dict], it)
        return iter_keyed_dups_async(
            it, 
            key=key, 
            keep_first=keep_first, 
        )
    else:
        it = cast(Iterator[dict], it)
        return iter_keyed_dups(
            it, 
            key=key, 
            keep_first=keep_first, 
        )


@overload
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[K, list[dict]]:
    ...
@overload
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[K, list[dict]]]:
    ...
def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[dict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[dict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_splitting_tasks: bool = True, 
    auto_splitting_threshold: int = 150_000, 
    auto_splitting_statistics_timeout: None | int | float = 5, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[K, list[dict]] | Coroutine[Any, Any, dict[K, list[dict]]]:
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
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是分组的 key，value 是归属这一组的文件信息列表
    """
    def gen_step():
        it: Iterator[tuple[K, dict]] | AsyncIterator[tuple[K, dict]] = iter_dupfiles(
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
            normalize_attr=normalize_attr, 
            id_to_dirnode=id_to_dirnode, 
            app=app, 
            raise_for_changed_count=raise_for_changed_count, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )
        if async_:
            it = cast(AsyncIterator[tuple[K, dict]], it)          
            dups: dict[K, list[dict]] = yield grouped_mapping_async(it)
        else:
            it = cast(Iterator[tuple[K, dict]], it)
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
                app=app, 
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
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
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
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
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
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
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
                app="android", 
                async_=async_, # type: ignore
                **request_kwargs, 
            )
        return d
    return run_gen_step(gen_step, async_=async_)


@overload
def iter_dangling_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_dangling_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_dangling_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """找出所有悬空的文件，即所在的目录 id 不为 0 且不存在

    .. todo::
        实际上，广义的悬空，包括所有这样的文件或目录，它们的祖先节点中存在一个节点，这个节点的 id 目前不存在于网盘（可能被删除或移入回收站）

    .. danger::
        你可以用 `P115Client.fs_move` 方法，把文件或目录随意移动到任何目录 id 下，即使这个 id 不存在

    .. note::
        你可以用 `P115Client.tool_space` 方法，把所有悬空文件找出来，放到专门的目录中，但这个接口一天只能用一次

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

    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if app in ("", "web", "desktop", "harmony"):
        fs_files: Callable = client.fs_files
    else:
        fs_files = partial(client.fs_files_app, app=app)
    def gen_step():
        na_cids: set[int] = set()
        ok_cids: set[int] = set()
        payload = {"cid": cid, "limit": page_size, "offset": 0, "suffix": suffix, "type": type}
        while True:
            resp = yield fs_files(payload, async_=async_, **request_kwargs)
            if cid and int(resp["path"][-1]["cid"]) != cid:
                break
            if resp["offset"] != payload["offset"]:
                break
            t = tuple(map(_overview_attr, resp["data"]))
            pids = {
                pid for a in t
                if (pid := a.parent_id) not in na_cids
                    and pid not in ok_cids
            }
            if pids:
                if async_:
                    na_cids.update(filter_na_ids(client, pids, **request_kwargs))
                else:
                    yield async_foreach(
                        na_cids.add, 
                        filter_na_ids(client, pids, async_=True, **request_kwargs), 
                    )
                ok_cids |= pids - na_cids
            for a, info in zip(t, resp["data"]):
                if a.parent_id in na_cids:
                    yield Yield(normalize_attr(info), identity=True)
            payload["offset"] += len(resp["data"]) # type: ignore
            if payload["offset"] >= resp["count"]:
                break
    return run_gen_step_iter(gen_step, async_=async_)


def share_extract_payload(link: str, /) -> SharePayload:
    """从链接中提取 share_code 和 receive_code

    .. hint::
        `link` 支持 3 种形式（圆括号中的字符表示可有可无）：

        1. http(s)://115.com/s/{share_code}?password={receive_code}(#) 或 http(s)://share.115.com/{share_code}?password={receive_code}(#)
        2. (/){share_code}-{receive_code}(/)
        3. {share_code}
    """
    m = CRE_SHARE_LINK_search1(link)
    if m is None:
        m = CRE_SHARE_LINK_search2(link)
    if m is None:
        raise ValueError("not a valid 115 share link")
    return cast(SharePayload, m.groupdict())


@overload
def share_iterdir(
    client: str | P115Client, 
    share_code: str, 
    receive_code: str = "", 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: None | Callable[[dict], dict] = normalize_attr, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def share_iterdir(
    client: str | P115Client, 
    share_code: str, 
    receive_code: str = "", 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: None | Callable[[dict], dict] = normalize_attr, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def share_iterdir(
    client: str | P115Client, 
    share_code: str, 
    receive_code: str = "", 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    normalize_attr: None | Callable[[dict], dict] = normalize_attr, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """对分享链接迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param share_code: 分享码
    :param receive_code: 接收码
    :param cid: 目录的 id
    :param page_size: 分页大小
    :param order: 排序

        - "file_name": 文件名
        - "file_size": 文件大小
        - "file_type": 文件种类
        - "user_utime": 修改时间
        - "user_ptime": 创建时间
        - "user_otime": 上一次打开时间

    :param asc: 升序排列。0: 否，1: 是
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，被打上星标的目录信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size < 0:
        page_size = 10_000
    def gen_step():
        nonlocal receive_code
        if not receive_code:
            resp = yield client.share_info(share_code, async_=async_, **request_kwargs)
            check_response(resp)
            receive_code = resp["data"]["receive_code"]
        payload = {
            "share_code": share_code, 
            "receive_code": receive_code, 
            "cid": cid, 
            "limit": page_size, 
            "offset": 0, 
            "asc": asc, 
            "o": order, 
        }
        count = 0
        while True:
            resp = yield client.share_snap(payload, base_url=True, async_=async_, **request_kwargs)
            check_response(resp)
            if count == (count := resp["data"]["count"]):
                break
            for attr in resp["data"]["list"]:
                attr["share_code"] = share_code
                attr["receive_code"] = receive_code
                if normalize_attr is not None:
                    attr = normalize_attr(attr)
                yield Yield(attr, identity=True)
            payload["offset"] += page_size # type: ignore
            if payload["offset"] >= count: # type: ignore
                break
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def share_iter_files(
    client: str | P115Client, 
    share_link: str, 
    receive_code: str = "", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def share_iter_files(
    client: str | P115Client, 
    share_link: str, 
    receive_code: str = "", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def share_iter_files(
    client: str | P115Client, 
    share_link: str, 
    receive_code: str = "", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """批量获取分享链接中的文件列表

    .. hint::
        `share_link` 支持 3 种形式（圆括号中的字符表示可有可无）：

        1. http(s)://115.com/s/{share_code}?password={receive_code}(#) 或 http(s)://share.115.com/{share_code}?password={receive_code}(#)
        2. (/){share_code}-{receive_code}(/)
        3. {share_code}

        如果使用第 3 种形式，而且又不提供 `receive_code`，则认为这是你自己所做的分享，会尝试自动去获取这个密码

        如果 `share_link` 中有 `receive_code`，而你又单独提供了 `receive_code`，则后者的优先级更高

    :param client: 115 客户端或 cookies
    :param share_link: 分享码或分享链接
    :param receive_code: 密码
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，返回此分享链接下的（仅文件）文件信息，由于接口返回信息有限，所以比较简略

        .. code:: python

            {
                "id": int, 
                "sha1": str, 
                "name": str, 
                "size": int, 
                "path": str, 
            }

    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        payload: dict = cast(dict, share_extract_payload(share_link))
        if receive_code:
            payload["receive_code"] = receive_code
        elif not payload["receive_code"]:
            resp = yield client.share_info(payload["share_code"], async_=async_, **request_kwargs)
            check_response(resp)
            payload["receive_code"] = resp["data"]["receive_code"]
        payload["cid"] = 0
        it = share_iterdir(client, **payload, async_=async_, **request_kwargs)
        do_next: Callable = anext if async_ else next
        try:
            while True:
                attr = yield do_next(it)
                if attr["is_directory"]:
                    payload["cid"] = attr["id"]
                    resp = yield client.share_downlist(payload, async_=async_, **request_kwargs)
                    check_response(resp)
                    for info in resp["data"]["list"]:
                        fid, sha1 = info["fid"].split("_", 1)
                        yield Yield({
                            "id": int(fid), 
                            "sha1": sha1, 
                            "name": info["fn"], 
                            "size": int(info["si"]), 
                            "path": f"/{info['pt']}/{info['fn']}", 
                        }, identity=True)
                else:
                    yield Yield({k: attr[k] for k in ("id", "sha1", "name", "size", "path")}, identity=True)
        except (StopIteration, StopAsyncIteration):
            pass
    return run_gen_step(gen_step, async_=async_)

