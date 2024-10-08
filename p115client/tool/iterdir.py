#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "traverse_stared_dirs", "ensure_attr_path", "iterdir", "iter_files", 
    "dict_files", "traverse_files", "iter_dupfiles", "dict_dupfiles", 
    "iter_image_files", "dict_image_files", 
]

from collections import defaultdict, deque
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from itertools import chain, islice, takewhile
from operator import itemgetter
from typing import Any, Final, Literal, NamedTuple, TypeVar
from warnings import warn

from dictattr import AttrDict
from httpx import ReadTimeout
from iter_collect import grouped_mapping, iter_keyed_dups, SupportsLT
from p115client import check_response, P115Client, P115Warning
from p115client.const import CLASS_TO_TYPE, SUFFIX_TO_TYPE
from posixpatht import escape, splitext


K = TypeVar("K")

ID_TO_DIRNODE_CACHE: Final[dict[int, dict[int, DirNode]]] = defaultdict(dict)


class DirNode(NamedTuple):
    name: str
    parent_id: int = 0


def normalize_attr(info: Mapping, /) -> AttrDict[str, Any]:
    attr: AttrDict[str, Any] = AttrDict()
    is_directory = attr["is_directory"] = "fid" not in info
    if is_directory:
        attr["id"] = int(info["cid"])        # cid => category_id
        attr["parent_id"] = int(info["pid"]) # pid => parent_id
    else:
        attr["id"] = int(info["fid"])        # fid => file_id
        attr["parent_id"] = int(info["cid"])
    #attr["area_id"] = int(attr["aid"])
    attr["pickcode"] = info["pc"]
    #attr["pick_time"] = int(info["pt"])
    #attr["pick_expire"] = info["e"]
    attr["name"] = info["n"]
    attr["size"] = int(info.get("s") or 0)
    attr["sha1"] = info.get("sha")
    attr["labels"] = info["fl"]
    attr["score"] = int(info.get("score") or 0)
    attr["ico"] = info.get("ico", "folder" if is_directory else "")
    attr["mtime"] = attr["user_utime"] = int(info["te"])
    attr["ctime"] = attr["user_ptime"] = int(info["tp"])
    if "to" in info:
        attr["atime"] = attr["user_otime"] = int(info["to"])
    if "tu" in info:
        attr["utime"] = int(info["tu"])
    for key, name in (
        ("m", "star"), 
        ("issct", "shortcut"), 
        ("hdf", "hidden"), 
        ("fdes", "described"), 
        ("c", "violated"), 
        #("sh", "shared"), 
        #("d", "has_desc"), 
        #("p", "has_pass"), 
    ):
        if key in info:
            attr[name] = int(info[key] or 0) == 1
    for key, name in (
        #("dp", "dir_path"), 
        #("style", "style"), 
        #("ns", "name_show"), 
        #("cc", "category_cover"), 
        ("sta", "status"), 
        ("class", "class"), 
        ("u", "thumb"), 
        ("vdi", "video_type"), 
        ("play_long", "play_long"), 
        ("current_time", "current_time"), 
        ("last_time", "last_time"), 
        ("played_end", "played_end"), 
    ):
        if key in info:
            attr[name] = info[key]
    return attr


def type_of_attr(attr: dict, /) -> int:
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


def traverse_stared_dirs(
    client: str | P115Client, 
    page_size: int = 10_000, 
    find_ids: None | Iterable[int] = None, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> Iterator[AttrDict]:
    """遍历以迭代获得所有被打上星标的目录信息

    :param client: 115 客户端或 cookies
    :param page_size: 分页大小
    :param find_ids: 需要寻找的 id 集合
        如果为 None 或空，则拉取所有打星标的文件夹；否则当找到所有这些 id 时，
        如果之前的迭代过程中获取到其它 id 都已存在于 id_to_dirnode 就立即终止，否则就拉取所有打星标的文件夹。
        如果从网上全部拉取完，还有一些在 find_ids 中的 id 没被看到，则报错 RuntimeError。
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典

    :return: 迭代器，被打上星标的目录信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    offset = 0
    payload = {
        "asc": asc, "cid": 0, "count_folders": 1, "cur": 0, "fc_mix": 0, "limit": page_size, 
        "o": order, "offset": offset, "show_dir": 1, "star": 1, 
    }
    if find_ids:
        if not isinstance(find_ids, Collection):
            find_ids = tuple(find_ids)
        need_to_find = set(find_ids)
    count = 0
    all_seen: bool = True
    while True:
        resp = check_response(client.fs_files(payload))
        if count == 0:
            count = resp.get("folder_count", 0)
        elif count != resp.get("folder_count", 0):
            warn(f"detected count changes during traversing stared dirs: {count} => {resp.get('folder_count', 0)}", category=P115Warning)
            count = resp.get("folder_count", 0)
        if not count:
            break
        if offset != resp["offset"]:
            break
        for attr in map(normalize_attr, takewhile(lambda info: "fid" not in info, resp["data"])):
            cid = attr["id"]
            if need_to_find and cid in need_to_find:
                need_to_find.remove(cid)
            elif cid not in id_to_dirnode:
                all_seen = False
            id_to_dirnode[cid] = DirNode(attr["name"], attr["parent_id"])
            yield attr
        else:
            if all_seen and not need_to_find:
                return
        offset += len(resp["data"])
        if offset >= count:
            break
        payload["offset"] = offset
    if find_ids and need_to_find:
        raise RuntimeError(f"unable to find these ids: {need_to_find!r}")


def ensure_attr_path(
    client: str | P115Client, 
    attrs: Iterable[dict], 
    page_size: int = 10_000, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    escape: None | Callable[[str], str] = escape, 
) -> Collection[dict]:
    """为一组文件信息添加 "path" 字段，表示文件的路径

    :param client: 115 客户端或 cookies
    :param attrs: 一组文件信息
    :param page_size: 分页大小
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等

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
                    next(iterdir(client, pid, page_size=1, id_to_dirnode=id_to_dirnode), None)
            else:
                ids_it = iter(find_ids)
                while ids := ",".join(map(str, islice(ids_it, 10_000))):
                    client.fs_star_set(ids)
                for _ in traverse_stared_dirs(client, page_size, find_ids, id_to_dirnode=id_to_dirnode):
                    pass
        pids = {ppid for pid in pids if (ppid := id_to_dirnode[pid][1]) != 0}
    for attr in attrs:
        attr["path"] = get_path(attr)
    return attrs


def iterdir(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    show_dir: Literal[0, 1] = 1, 
    fc_mix: Literal[0, 1] = 1, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> Iterator[AttrDict]:
    """迭代目录，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param show_dir: 展示文件夹。0: 否，1: 是
    :param fc_mix: 文件夹置顶。0: 文件夹在文件之前，1: 文件和文件夹混合并按指定排序
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典

    :return: 迭代器，返回此目录内的文件信息（文件和目录）
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    offset = 0
    payload = {
        "asc": asc, "cid": cid, "count_folders": 1, "fc_mix": fc_mix, "limit": page_size, 
        "show_dir": show_dir, "o": order, "offset": offset, 
    }
    count = 0
    while True:
        resp = check_response(client.fs_files(payload))
        if int(resp["path"][-1]["cid"]) != cid:
            raise FileNotFoundError(2, cid)
        for info in resp["path"][1:]:
            id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
        if count == 0:
            count = resp["count"]
        elif count != resp["count"]:
            raise RuntimeError(f"{cid} detected count changes during iteration")
        for attr in map(normalize_attr, resp["data"]):
            if attr.get("is_directory", False):
                id_to_dirnode[attr["id"]] = DirNode(attr["name"], attr["parent_id"])
            yield attr
        offset += len(resp["data"])
        if offset >= count:
            break
        payload["offset"] = offset


def iter_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> Iterator[AttrDict]:
    """遍历目录树，获取文件信息

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型
        - 全部: 0
        - 文档: 1
        - 图片: 2
        - 音频: 3
        - 视频: 4
        - 压缩包: 5
        - 应用: 6
        - 书籍: 7
        - 仅文件: 99
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    suffix = suffix.strip(".")
    if not (type or suffix):
        raise ValueError("please set the non-zero value of suffix or type")
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if page_size <= 0:
        page_size = 10_000
    elif page_size < 16:
        page_size = 16
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    offset = 0
    payload = {
        "asc": asc, "cid": cid, "count_folders": 0, "cur": cur, "limit": page_size, 
        "o": order, "offset": offset, "show_dir": 0, "suffix": suffix, "type": type, 
    }
    count = 0
    while True:
        resp = check_response(client.fs_files(payload))
        if int(resp["path"][-1]["cid"]) != cid:
            raise FileNotFoundError(2, cid)
        for info in resp["path"][1:]:
            id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
        if count == 0:
            count = resp["count"]
        elif count != resp["count"]:
            warn(f"{cid} detected count changes during traversing: {count} => {resp['count']}", category=P115Warning)
            count = resp["count"]
        if offset != resp["offset"]:
            break
        yield from map(normalize_attr, resp["data"])
        offset += len(resp["data"])
        if offset >= count:
            break
        payload["offset"] = offset


def dict_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> dict[int, AttrDict]:
    """获取一个目录内的所有文件信息

    :param client: 115 客户端或 cookies
    :param cid: 待被遍历的目录 id，默认为根目录
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型
        - 全部: 0
        - 文档: 1
        - 图片: 2
        - 音频: 3
        - 视频: 4
        - 压缩包: 5
        - 应用: 6
        - 书籍: 7
        - 仅文件: 99
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_path: 文件信息中是否要包含 路径
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等

    :return: 字典，key 是 id，value 是 文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    id_to_attr: dict[int, AttrDict] = {
        attr["id"]: attr
        for attr in iter_files(
            client, 
            cid, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            order=order, 
            asc=asc, 
            cur=cur, 
            id_to_dirnode=id_to_dirnode, 
        )
    }
    if with_path:
        ensure_attr_path(
            client, 
            id_to_attr.values(), 
            page_size=page_size, 
            id_to_dirnode=id_to_dirnode, 
            escape=escape, 
        )
    return id_to_attr


def traverse_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_split_tasks: bool = True, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> Iterator[AttrDict]:
    """遍历目录树，获取文件信息（会根据统计信息，分解任务）

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param suffix: 后缀名（优先级高于 type）
    :param type: 文件类型
        - 全部: 0
        - 文档: 1
        - 图片: 2
        - 音频: 3
        - 视频: 4
        - 压缩包: 5
        - 应用: 6
        - 书籍: 7
        - 仅文件: 99
    :param auto_split_tasks: 根据统计信息自动拆分任务（如果目录内的文件数大于 150_000，则分拆此任务到它的各个直接子目录，否则批量拉取）
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典

    :return: 迭代器，返回此目录内的（仅文件）文件信息
    """
    if not auto_split_tasks:
        try:
            yield from iter_files(
                client, 
                cid, 
                page_size=page_size, 
                suffix=suffix, 
                type=type, 
                id_to_dirnode=id_to_dirnode, 
            )
        except FileNotFoundError:
            pass
        return
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
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    dq: deque[int] = deque()
    get, put = dq.pop, dq.appendleft
    put(cid)
    while dq:
        try:
            if cid := get():
                # NOTE: 必要时也可以根据不同的扩展名进行分拆任务，通过 client.fs_files_second_type({"cid": cid, "type": type}) 获取目录内所有的此种类型的扩展名，并且如果响应为空时，则直接退出
                try:
                    payload = {
                        "asc": 1, "cid": cid, "cur": 0, "limit": 16, "o": "user_ptime", "offset": 0, 
                        "show_dir": 0, "suffix": suffix, "type": type, 
                    }
                    resp = check_response(client.fs_files(payload, timeout=5))
                    if int(resp["path"][-1]["cid"]) != cid:
                        continue
                except ReadTimeout:
                    file_count = float("inf")
                else:
                    file_count = resp["count"]
                if file_count <= 150_000:
                    yield from iter_files(
                        client, 
                        cid, 
                        page_size=page_size, 
                        suffix=suffix, 
                        type=type, 
                        id_to_dirnode=id_to_dirnode, 
                    )
                    continue
                for attr in iterdir(client, cid, page_size=page_size, id_to_dirnode=id_to_dirnode):
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


def iter_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_split_tasks: bool = True, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
) -> Iterator[tuple[K, AttrDict]]:
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
        - 全部: 0
        - 文档: 1
        - 图片: 2
        - 音频: 3
        - 视频: 4
        - 压缩包: 5
        - 应用: 6
        - 书籍: 7
        - 仅文件: 99
    :param auto_split_tasks: 根据统计信息自动拆分任务（如果目录内的文件数大于 150_000，则分拆此任务到它的各个直接子目录，否则批量拉取）
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典

    :return: 迭代器，返回 key 和 重复文件信息 的元组
    """
    return iter_keyed_dups(
        traverse_files(
            client, 
            cid, 
            page_size=page_size, 
            suffix=suffix, 
            type=type, 
            auto_split_tasks=auto_split_tasks, 
            id_to_dirnode=id_to_dirnode, 
        ), 
        key=key, 
        keep_first=keep_first, 
    )


def dict_dupfiles(
    client: str | P115Client, 
    cid: int = 0, 
    key: Callable[[AttrDict], K] = itemgetter("sha1", "size"), 
    keep_first: None | bool | Callable[[AttrDict], SupportsLT] = None, 
    page_size: int = 10_000, 
    suffix: str = "", 
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    auto_split_tasks: bool = True, 
    with_path: bool = False, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    escape: None | Callable[[str], str] = escape, 
) -> dict[K, list[AttrDict]]:
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
        - 全部: 0
        - 文档: 1
        - 图片: 2
        - 音频: 3
        - 视频: 4
        - 压缩包: 5
        - 应用: 6
        - 书籍: 7
        - 仅文件: 99
    :param auto_split_tasks: 根据统计信息自动拆分任务（如果目录内的文件数大于 150_000，则分拆此任务到它的各个直接子目录，否则批量拉取）
    :param with_path: 文件信息中是否要包含 路径
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等

    :return: 字典，key 是分组的 key，value 是归属这一组的文件信息列表
    """
    dups = grouped_mapping(iter_dupfiles(
        client, 
        cid, 
        key=key, 
        keep_first=keep_first, 
        page_size=page_size, 
        suffix=suffix, 
        type=type, 
        auto_split_tasks=auto_split_tasks, 
        id_to_dirnode=id_to_dirnode, 
    ))
    if with_path:
        ensure_attr_path(
            client, 
            chain.from_iterable(dups.values()), 
            page_size=page_size, 
            id_to_dirnode=id_to_dirnode, 
            escape=escape, 
        )
    return dups


def iter_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
) -> Iterator[dict]:
    """遍历目录树，获取图片文件信息（包含图片的 CDN 链接）

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是

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
    offset = 0
    payload = {"asc": asc, "cid": cid, "cur": cur, "limit": page_size, "o": order, "offset": offset}
    count = 0
    while True:
        resp = check_response(client.fs_imglist(payload))
        if int(resp["cid"]) != cid:
            raise FileNotFoundError(2, cid)
        if count == 0:
            count = resp["count"]
        elif count != resp["count"]:
            warn(f"{cid} detected count changes during traversing: {count} => {resp['count']}", category=P115Warning)
            count = resp["count"]
        if offset != resp["offset"]:
            break
        yield from map(normalize, resp["data"])
        offset += len(resp["data"])
        if offset >= count:
            break
        payload["offset"] = offset


def dict_image_files(
    client: str | P115Client, 
    cid: int = 0, 
    page_size: int = 8192, 
    order: Literal["file_name", "file_size", "file_type", "user_utime", "user_ptime", "user_otime"] = "user_ptime", 
    asc: Literal[0, 1] = 1, 
    cur: Literal[0, 1] = 0, 
    with_path: bool = False, 
    id_to_dirnode: None | dict[int, DirNode] = None, 
    escape: None | Callable[[str], str] = escape, 
) -> dict[int, dict]:
    """获取一个目录内的所有图片文件信息（包含图片的 CDN 链接）
    TIPS: 这个函数的效果相当于 dict_files(client, cid, type=2, ...) 所获取的文件列表，只是返回信息有些不同

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param page_size: 分页大小
    :param order: 排序
        - 文件名："file_name"
        - 文件大小："file_size"
        - 文件种类："file_type"
        - 修改时间："user_utime"
        - 创建时间："user_ptime"
        - 上一次打开时间："user_otime"
    :param asc: 升序排列。0: 否，1: 是
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_path: 文件信息中是否要包含 路径
    :param id_to_dirnode: 字典，保存 id 到对应文件的 DirNode(name, parent_id) 命名元组的字典
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等

    :return: 字典，key 是 id，value 是 图片文件信息
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    d: dict[int, dict] = {
        attr["id"]: attr 
        for attr in iter_image_files(
            client, 
            cid, 
            page_size=page_size, 
            order=order, 
            asc=asc, 
            cur=cur, 
        )
    }
    if with_path:
        ensure_attr_path(
            client, 
            d.values(), 
            id_to_dirnode=id_to_dirnode, 
            escape=escape, 
        )
    return d

