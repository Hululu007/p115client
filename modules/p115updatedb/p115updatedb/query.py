#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "get_dir_count", "has_id", "iter_existing_id", "get_parent_id", "iter_parent_id", 
    "iter_id_to_parent_id", "iter_id_to_path", "id_to_path", "get_id", "get_pickcode", 
    "get_sha1", "get_path", "get_ancestors", "get_attr", "iter_children", 
    "iter_descendants", "iter_descendants_fast", "iter_files_with_path_url", 
    "select_na_ids", "select_mtime_groups", "dump_to_alist", 
]

from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime
from errno import ENOENT, ENOTDIR
from itertools import batched
from os.path import expanduser
from pathlib import Path
from sqlite3 import register_adapter, register_converter, Connection, Cursor, OperationalError
from posixpath import join
from typing import cast, overload, Any, Final, Literal
from urllib.parse import quote

from posixpatht import escape, path_is_dir_form, splits
from sqlitetools import find, query, transact

from .util import bfs_gen


FIELDS: Final = (
    "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", "type", 
    "ctime", "mtime", "is_collect", "is_alive", "updated_at", 
)
EXTENDED_FIELDS: Final = (*FIELDS, "path", "posixpath")

register_converter("DATETIME", lambda dt: datetime.fromisoformat(str(dt, "utf-8")))


def get_dir_count(
    con: Connection | Cursor, 
    id: int, 
    /, 
) -> None | dict:
    record = find(con, "SELECT dir_count, file_count, tree_dir_count, tree_file_count FROM dirlen WHERE id=?", id)
    if record is None:
        return None
    return dict(zip(("dir_count", "file_count", "tree_dir_count", "tree_file_count"), record))


def has_id(
    con: Connection | Cursor, 
    id: int, 
    /, 
    is_alive: bool = True, 
) -> int:
    if id == 0:
        return 1
    elif id < 0:
        return 0
    sql = "SELECT 1 FROM data WHERE id=?"
    if is_alive:
        sql += " AND is_alive"
    return find(con, sql, id, 0)


def iter_existing_id(
    con: Connection | Cursor, 
    ids: Iterable[int], 
    /, 
    is_alive: bool = True, 
) -> Iterator[int]:
    sql = "SELECT id FROM data WHERE id IN (%s)" % (",".join(map("%d".__mod__, ids)) or "NULL")
    if is_alive:
        sql += " AND is_alive"
    return (id for id, in query(con, sql))


def get_parent_id(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
    default: None | int = None, 
) -> int:
    if id == 0:
        return 0
    sql = "SELECT parent_id FROM data WHERE id=?"
    pid = find(con, sql, id, default)
    if pid is None:
        raise FileNotFoundError(ENOENT, id)
    return pid


def iter_parent_id(
    con: Connection | Cursor, 
    ids: Iterable[int], 
    /, 
) -> Iterator[int]:
    sql = "SELECT parent_id FROM data WHERE id IN (%s)" % (",".join(map("%d".__mod__, ids)) or "NULL")
    return (id for id, in query(con, sql))


def iter_id_to_parent_id(
    con: Connection | Cursor, 
    ids: Iterable[int], 
    /, 
    recursive: bool = False, 
):
    s_ids = "(%s)" % (",".join(map(str, ids)) or "NULL")
    if recursive:
        sql = """\
WITH pairs AS (
    SELECT id, parent_id FROM data WHERE id IN %s
    UNION ALL
    SELECT data.id, data.parent_id FROM pairs JOIN data ON (pairs.parent_id = data.id)
) SELECT * FROM pairs""" % s_ids
    else:
        sql = "SELECT id, parent_id FROM data WHERE id IN %s" % s_ids
    return query(con, sql)


def iter_id_to_path(
    con: Connection | Cursor, 
    /, 
    path: str | Sequence[str] = "", 
    ensure_file: None | bool = None, 
    parent_id: int = 0, 
) -> Iterator[int]:
    """查询匹配某个路径的文件或目录的信息字典

    .. note::
        同一个路径可以有多条对应的数据

    :param con: 数据库连接或游标
    :param path: 路径
    :param ensure_file: 是否文件

        - 如果为 True，必须是文件
        - 如果为 False，必须是目录
        - 如果为 None，可以是文件或目录

    :param parent_id: 顶层目录的 id

    :return: 迭代器，产生一组匹配指定路径的（文件或目录）节点的 id
    """
    patht: Sequence[str]
    if isinstance(path, str):
        if ensure_file is None and path_is_dir_form(path):
            ensure_file = False
        patht, _ = splits("/" + path)
    else:
        patht = ("", *filter(None, path))
    if not parent_id and len(patht) == 1:
        yield 0
        return
    if len(patht) > 2:
        sql = "SELECT id FROM data WHERE parent_id=? AND name=? AND is_alive AND is_dir LIMIT 1"
        for name in patht[1:-1]:
            parent_id = find(con, sql, (parent_id, name), default=-1)
            if parent_id < 0:
                return
    sql = "SELECT id FROM data WHERE parent_id=? AND name=? AND is_alive"
    if ensure_file is None:
        sql += " ORDER BY is_dir DESC"
    elif ensure_file:
        sql += " AND NOT is_dir"
    else:
        sql += " AND is_dir LIMIT 1"
    for id, in query(con, sql, (parent_id, patht[-1])):
        yield id


def id_to_path(
    con: Connection | Cursor, 
    /, 
    path: str | Sequence[str] = "", 
    ensure_file: None | bool = None, 
    parent_id: int = 0, 
) -> int:
    """查询匹配某个路径的文件或目录的信息字典，只返回找到的第 1 个

    :param con: 数据库连接或游标
    :param path: 路径
    :param ensure_file: 是否文件

        - 如果为 True，必须是文件
        - 如果为 False，必须是目录
        - 如果为 None，可以是文件或目录

    :param parent_id: 顶层目录的 id

    :return: 找到的第 1 个匹配的节点 id
    """
    try:
        return next(iter_id_to_path(con, path, ensure_file, parent_id))
    except StopIteration:
        raise FileNotFoundError(ENOENT, path) from None


def get_id(
    con: Connection | Cursor, 
    /, 
    pickcode: str = "", 
    sha1: str = "", 
    path: str = "", 
    is_alive: bool = True, 
) -> int:
    """查询匹配某个字段的文件或目录的 id

    :param con: 数据库连接或游标
    :param pickcode: 当前节点的提取码，优先级高于 sha1
    :param sha1: 当前节点的 sha1 校验散列值，优先级高于 path
    :param path: 当前节点的路径

    :return: 当前节点的 id
    """
    insertion = " AND is_alive" if is_alive else ""
    if pickcode:
        return find(
            con, 
            f"SELECT id FROM data WHERE pickcode=?{insertion} LIMIT 1", 
            pickcode, 
            default=FileNotFoundError(pickcode), 
        )
    elif sha1:
        return find(
            con, 
            f"SELECT id FROM data WHERE sha1=?{insertion} LIMIT 1", 
            sha1, 
            default=FileNotFoundError(sha1), 
        )
    elif path:
        return id_to_path(con, path)
    return 0


def get_pickcode(
    con: Connection | Cursor, 
    /, 
    id: int = -1, 
    sha1: str = "", 
    path: str = "", 
    is_alive: bool = True, 
) -> str:
    """查询匹配某个字段的文件或目录的提取码

    :param con: 数据库连接或游标
    :param id: 当前节点的 id，优先级高于 sha1
    :param sha1: 当前节点的 sha1 校验散列值，优先级高于 path
    :param path: 当前节点的路径

    :return: 当前节点的提取码
    """
    insertion = " AND is_alive" if is_alive else ""
    if id >= 0:
        if not id:
            return ""
        return find(
            con, 
            f"SELECT pickcode FROM data WHERE id=?{insertion} LIMIT 1;", 
            id, 
            default=FileNotFoundError(id), 
        )
    elif sha1:
        return find(
            con, 
            f"SELECT pickcode FROM data WHERE sha1=?{insertion} LIMIT 1;", 
            sha1, 
            default=FileNotFoundError(sha1), 
        )
    else:
        if path in ("", "/"):
            return ""
        return get_pickcode(con, id_to_path(con, path))


def get_sha1(
    con: Connection | Cursor, 
    /, 
    id: int = -1, 
    pickcode: str = "", 
    path: str = "", 
    is_alive: bool = True, 
) -> str:
    """查询匹配某个字段的文件的 sha1

    :param con: 数据库连接或游标
    :param id: 当前节点的 id，优先级高于 pickcode
    :param pickcode: 当前节点的提取码，优先级高于 path
    :param path: 当前节点的路径

    :return: 当前节点的 sha1 校验散列值
    """
    insertion = " AND is_alive" if is_alive else ""
    if id >= 0:
        if not id:
            return ""
        return find(
            con, 
            f"SELECT sha1 FROM data WHERE id=?{insertion} LIMIT 1;", 
            id, 
            default=FileNotFoundError(id), 
        )
    elif pickcode:
        return find(
            con, 
            f"SELECT sha1 FROM data WHERE pickcode=?{insertion} LIMIT 1;", 
            pickcode, 
            default=FileNotFoundError(pickcode), 
        )
    else:
        if path in ("", "/"):
            return ""
        return get_sha1(con, id_to_path(con, path))


def get_path(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
) -> str:
    """获取某个文件或目录的路径

    :param con: 数据库连接或游标
    :param id: 当前节点的 id

    :return: 当前节点的路径
    """
    if not id:
        return "/"
    ancestors = get_ancestors(con, id)
    return "/".join(escape(a["name"]) for a in ancestors)


def get_ancestors(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
) -> list[dict]:
    """获取某个文件或目录的祖先节点信息，包括 id、parent_id 和 name

    :param con: 数据库连接或游标
    :param id: 当前节点的 id

    :return: 当前节点的祖先节点列表，从根目录开始（id 为 0）直到当前节点
    """
    ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
    if not id:
        return ancestors
    ls = list(query(con, """\
WITH t AS (
    SELECT id, parent_id, name FROM data WHERE id = ?
    UNION ALL
    SELECT data.id, data.parent_id, data.name FROM t JOIN data ON (t.parent_id = data.id)
)
SELECT id, parent_id, name FROM t;""", id))
    if not ls:
        raise FileNotFoundError(ENOENT, id)
    if ls[-1][1]:
        raise ValueError(f"dangling id: {id}")
    ancestors.extend(dict(zip(("id", "parent_id", "name"), record)) for record in reversed(ls))
    return ancestors


def get_attr(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
) -> dict:
    """获取某个文件或目录的信息

    :param con: 数据库连接或游标
    :param id: 当前节点的 id

    :return: 当前节点的信息字典
    """
    if not id:
        return {
            "id": 0, "parent_id": 0, "pickcode": "", "sha1": "", "name": "", "size": 0, 
            "is_dir": 1, "type": 0, "ctime": 0, "mtime": 0, "is_collect": 0, 
            "is_alive": 1, "updated_at": datetime.fromtimestamp(0), 
        }
    record = next(query(con, "SELECT * FROM data WHERE id=? LIMIT 1", id), None)
    if record is None:
        raise FileNotFoundError(ENOENT, id)
    return dict(zip(FIELDS, record))


def iter_children(
    con: Connection | Cursor, 
    parent_id: int | dict = 0, 
    /, 
    fields: tuple[str, ...] = FIELDS, 
    ensure_file: None | bool = None, 
) -> Iterator[dict]:
    """获取某个目录之下的文件或目录的信息

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
    :param fields: 需要获取的字段，接受如下这些

        .. code:: python

            (
                "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", "type", 
                "ctime", "mtime", "is_collect", "is_alive", "updated_at", 
            )

    :param ensure_file: 是否仅输出文件

        - 如果为 True，仅输出文件
        - 如果为 False，仅输出目录
        - 如果为 None，全部输出

    :return: 迭代器，产生一组信息的字典
    """
    if isinstance(parent_id, int):
        attr = get_attr(con, parent_id)
    else:
        attr = parent_id
    if not fields:
        fields = FIELDS
    if not attr["is_dir"]:
        raise NotADirectoryError(ENOTDIR, attr)
    sql = "SELECT %s FROM data WHERE parent_id=? AND is_alive" % ",".join(fields)
    if ensure_file:
        sql += " AND NOT is_dir"
    elif ensure_file is not None:
        sql += " AND is_dir"
    return (dict(zip(fields, record)) for record in query(con, sql, attr["id"]))


def iter_descendants(
    con: Connection | Cursor, 
    parent_id: int | dict = 0, 
    /, 
    topdown: None | bool = True, 
    max_depth: int = -1, 
    fields: tuple[str, ...] = FIELDS, 
    ensure_file: None | bool = None, 
) -> Iterator[dict]:
    """遍历获取某个目录之下的所有文件或目录的信息

    :param con: 数据库连接或游标
    :param parent_id: 顶层目录的 id
    :param topdown: 是否自顶向下深度优先遍历

        - 如果为 True，则自顶向下深度优先遍历
        - 如果为 False，则自底向上深度优先遍历
        - 如果为 None，则自顶向下宽度优先遍历

    :param max_depth: 最大深度。如果小于 0，则无限深度
    :param fields: 需要获取的字段，接受如下这些

        .. code:: python

            (
                "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", "type", 
                "ctime", "mtime", "is_collect", "is_alive", "updated_at", 
            )

    :param ensure_file: 是否仅输出文件

        - 如果为 True，仅输出文件
        - 如果为 False，仅输出目录
        - 如果为 None，全部输出

    :return: 迭代器，产生一组信息的字典
    """
    if isinstance(parent_id, int):
        ancestors = get_ancestors(con, parent_id)
        dir_ = "/".join(escape(a["name"]) for a in ancestors) + "/"
        posixdir = "/".join(a["name"].replace("/", "|") for a in ancestors) + "/"
    else:
        attr = parent_id
        ancestors = attr["ancestors"]
        dir_ = attr["path"]
        posixdir = attr["posixpath"]
    if topdown is None:
        gen = bfs_gen((parent_id, max_depth, ancestors, dir_, posixdir))
        send = gen.send
        for parent_id, depth, ancestors, dir_, posixdir in gen:
            depth -= depth > 0
            for attr in iter_children(con, parent_id, fields=fields):
                ancestors = attr["ancestors"] = [
                    *ancestors, 
                    {k: attr[k] for k in ("id", "parent_id", "name")}, 
                ]
                dir_ = attr["path"] = dir_ + escape(attr["name"])
                posixdir = attr["posixpath"] = posixdir + attr["name"].replace("/", "|")
                is_dir = attr["is_dir"]
                if is_dir and depth:
                    send((attr, depth, ancestors, dir_, posixdir)) # type: ignore
                if ensure_file is None:
                    yield attr
                elif is_dir:
                    if not ensure_file:
                        yield attr
                elif ensure_file:
                    yield attr
    else:
        max_depth -= max_depth > 0
        for attr in iter_children(con, parent_id, fields=fields):
            is_dir = attr["is_dir"]
            attr["ancestors"] = [
                *ancestors, 
                {k: attr[k] for k in ("id", "parent_id", "name")}, 
            ]
            attr["path"] = dir_ + escape(attr["name"])
            attr["posixpath"] = posixdir + attr["name"].replace("/", "|")
            if topdown:
                if ensure_file is None:
                    yield attr
                elif is_dir:
                    if not ensure_file:
                        yield attr
                elif ensure_file:
                    yield attr
            if is_dir and max_depth:
                yield from iter_descendants(
                    con, 
                    attr, 
                    topdown=topdown, 
                    max_depth=max_depth, 
                    ensure_file=ensure_file, 
                )
            if not topdown:
                if ensure_file is None:
                    yield attr
                elif is_dir:
                    if not ensure_file:
                        yield attr
                elif ensure_file:
                    yield attr


@overload
def iter_descendants_fast(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    *, 
    fields: Literal[False], 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    where: str = "", 
    orderby: str = "", 
) -> Iterator[int]:
    ...
@overload
def iter_descendants_fast(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    *, 
    fields: Literal[True] | tuple[str, ...] = True, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    to_dict: Literal[True] = True, 
    where: str = "", 
    orderby: str = "", 
) -> Iterator[dict[str, Any]]:
    ...
@overload
def iter_descendants_fast(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    *, 
    fields: Literal[True] | tuple[str, ...] = True, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    to_dict: Literal[False], 
    where: str = "", 
    orderby: str = "", 
) -> Iterator:
    ...
def iter_descendants_fast(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    *, 
    fields: bool | tuple[str, ...] = True, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    to_dict: bool = True, 
    where: str = "", 
    orderby: str = "", 
) -> Iterator:
    """获取某个目录之下的所有目录节点的 id 或者信息字典

    :param con: 数据库连接或游标
    :param parent_id: 顶层目录的 id
    :param fields: 需要获取的字段，接受如下这些，其中无论是否提供，"id" 必会被包含：

        .. code:: python

            (
                "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", "type", 
                "ctime", "mtime", "is_collect", "is_alive", "updated_at", "path", "posixpath", 
            )

        - 如果为 False，则只拉取 id
        - 如果为 True，则拉取上面提到的所有字段
        - 如果为 tuple，则是指定了所要拉取的一组字段，无论是否提供，必会包含 "id"，且在最前面，且会把 "path" 和 "posixpath" 放在最后（如果有的话）

    :param max_depth: 最大深度。如果小于 0，则无限深度
    :param ensure_file: 是否仅输出文件

        - 如果为 True，仅输出文件
        - 如果为 False，仅输出目录
        - 如果为 None，全部输出

    :param to_dict: 是否产生字典，如果为 False，则直接迭代返回游标的数据
    :param where: 一些 WHERE 查询条件，直接拼接到查询语句最后
    :param orderby: 一些 ORDER BY 排序条件，直接拼接到查询语句最后

    :return: 迭代器，产生一组 id
    """
    if fields is False:
        if 0 <= max_depth <= 1:
            sql = "SELECT id FROM data WHERE parent_id=:parent_id AND is_alive"
        else:
            if max_depth < 0:
                args = ("", "", "")
            else:
                args = (
                    ", 1 AS depth", 
                    ", t.depth + 1", 
                    " AND depth < :max_depth", 
                )
            if ensure_file is not None:
                args = (
                    args[0] + ", is_dir", 
                    args[1] + ", data.is_dir", 
                    args[2], 
                )
            sql = """\
WITH t AS (
    SELECT id%s FROM data WHERE parent_id=:parent_id AND is_alive
    UNION ALL
    SELECT data.id%s FROM t JOIN data ON(t.id = data.parent_id) WHERE data.is_alive%s
)
SELECT id FROM t AS data WHERE TRUE""" % args
        if ensure_file:
            sql += " AND NOT is_dir"
        elif ensure_file is not None:
            sql += " AND is_dir"
        if where:
            sql += f" AND ({where})"
        if orderby:
            sql += f" ORDER BY {orderby}"
        return (id for id, in query(con, sql, locals()))
    else:
        if fields is True:
            fields = EXTENDED_FIELDS
        fields = cast(tuple[str, ...], fields)
        with_path = "path" in fields
        with_posixpath = "posixpath" in fields
        if with_path:
            try:
                (con.connection if isinstance(con, Cursor) else con).create_function(
                    "escape_name", 1, escape, deterministic=True)
            except OperationalError:
                pass
        if with_path or with_posixpath:
            if parent_id:
                ancestors = get_ancestors(con, parent_id)
                if with_path:
                    path = "/".join(escape(a["name"]) for a in ancestors)
                if with_posixpath:
                    posixpath = "/".join(a["name"].replace("/", "|") for a in ancestors)
            else:
                path = posixpath = ""
        predicate: Callable[[str], bool] = frozenset(FIELDS[1:]).__contains__
        fields = ("id", *filter(predicate, fields))
        select_fields_1 = ", ".join(fields)
        select_fields_2 = "data." + ", data.".join(fields)
        if with_path:
            select_fields_1 += ", :path || '/' || escape_name(name) AS path"
            select_fields_2 += ", t.path || '/' || escape_name(data.name)"
            fields += "path",
        if with_posixpath:
            select_fields_1 += ", :posixpath || '/' || REPLACE(name, '/', '|') AS posixpath"
            select_fields_2 += ", t.posixpath || '/' || REPLACE(data.name, '/', '|')"
            fields += "posixpath",
        if 0 <= max_depth <= 1:
            sql = f"SELECT {select_fields_1} FROM data WHERE parent_id=:parent_id AND is_alive"
        else:
            if max_depth < 0:
                args = ("", "", "")
            else:
                args = (
                    ", 1 AS depth", 
                    ", t.depth + 1", 
                    " AND depth < :max_depth", 
                )
            if ensure_file is not None:
                args = (
                    args[0] + ", is_dir", 
                    args[1] + ", data.is_dir", 
                    args[2], 
                )
            sql = f"""\
WITH t AS (
    SELECT {select_fields_1}%s FROM data WHERE parent_id=:parent_id AND is_alive
    UNION ALL
    SELECT {select_fields_2}%s FROM t JOIN data ON(t.id = data.parent_id) WHERE data.is_alive%s
)
SELECT {",".join(fields)} FROM t AS data WHERE TRUE""" % args
        if ensure_file:
            sql += " AND NOT is_dir"
        elif ensure_file is not None:
            sql += " AND is_dir"
        if where:
            sql += f" AND ({where})"
        if orderby:
            sql += f" ORDER BY {orderby}"
        cur = query(con, sql, locals())
        if to_dict:
            return (dict(zip(fields, record)) for record in cur)
        return cur


def iter_files_with_path_url(
    con: Connection | Cursor, 
    parent_id: int | str = 0, 
    /, 
    base_url: str = "http://localhost:8000", 
) -> Iterator[tuple[str, str]]:
    """迭代获取所有文件的路径和下载链接

    :param con: 数据库连接或游标
    :param parent_id: 根目录 id 或者路径
    :param base_url: 115 的 302 服务后端地址

    :return: 迭代器，返回每个文件的 路径 和 下载链接 的 2 元组
    """
    if isinstance(parent_id, str):
        parent_id = get_id(con, path=parent_id)
    code = compile('f"%s/{quote(name, '"''"')}?{id=}&{pickcode=!s}&{sha1=!s}&{size=}&file=true"' % base_url.translate({ord(c): c*2 for c in "{}"}), "-", "eval")
    for attr in iter_descendants_fast(
        con, 
        parent_id, 
        fields=("id", "sha1", "pickcode", "size", "name", "posixpath"), 
        ensure_file=True, 
    ):
        yield attr["posixpath"], eval(code, None, attr)


def select_na_ids(
    con: Connection | Cursor, 
    /, 
) -> set[int]:
    """找出所有的失效节点和悬空节点的 id

    .. note::
        悬空节点，就是此节点有一个祖先节点的 id，不为 0 且不在 `data` 表中

    :param con: 数据库连接或游标

    :return: 一组悬空节点的 id 的集合
    """
    ok_ids: set[int] = set(query(con, "SELECT id FROM data WHERE NOT is_alive"))
    na_ids: set[int] = set()
    d = dict(query(con, "SELECT id, parent_id FROM data WHERE is_alive"))
    temp: list[int] = []
    push = temp.append
    clear = temp.clear
    update_ok = ok_ids.update
    update_na = na_ids.update
    for k, v in d.items():
        try:
            push(k)
            while k := d[k]:
                if k in ok_ids:
                    update_ok(temp)
                    break
                elif k in na_ids:
                    update_na(temp)
                    break
                push(k)
            else:
                update_ok(temp)
        except KeyError:
            update_na(temp)
        finally:
            clear()
    return na_ids


def select_mtime_groups(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    tree: bool = False, 
) -> tuple[int, list[tuple[int, set[int]]]]:
    """获取某个目录之下的节点（不含此节点本身），按 mtime 进行分组，相同 mtime 的 id 归入同一组

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
    :param tree: 是否拉取目录树，如果为 True，则拉取全部后代的文件节点（不含目录节点），如果为 False，则只拉取子节点（含目录节点）

    :return: 字典，表示相同 mtime 的 id 的集合，所以 key 是 mtime，value 是一组 id 的集合
    """
    if tree:
        it = iter_descendants_fast(con, parent_id, fields=("id", "mtime"), ensure_file=True, to_dict=False)
    else:
        it = iter_descendants_fast(con, parent_id, fields=("id", "mtime"), max_depth=1, to_dict=False)
    d: dict[int, set[int]] = {}
    n = 0
    for n, (id, mtime) in enumerate(it, 1):
        try:
            d[mtime].add(id)
        except KeyError:
            d[mtime] = {id}
    return n, sorted(d.items(), reverse=True)


def dump_to_alist(
    con: Connection | Cursor, 
    /, 
    alist_db: str | Path | Connection | Cursor = expanduser("~/alist.d/data/data.db"), 
    parent_id: int | str = 0, 
    dirname: str = "/115", 
    clean: bool = True, 
) -> int:
    """把 p115updatedb 导出的数据，导入到 alist 的搜索索引

    :param con: 数据库连接或游标
    :param alist_db: alist 数据库文件路径或连接
    :param parent_id: 在 p115updatedb 所导出数据库中的顶层目录 id 或路径
    :param dirname: 在 alist 中所对应的的顶层目录路径
    :param clean: 在插入前先清除 alist 的数据库中 `dirname` 目录下的所有数据

    :return: 总共导入的数量
    """
    if isinstance(parent_id, str):
        parent_id = get_id(con, path=parent_id)
    sql = """\
WITH t AS (
    SELECT 
        :dirname AS parent, 
        name, 
        is_dir, 
        size, 
        id, 
        CASE WHEN is_dir THEN :dirname || '/' || REPLACE(name, '/', '|') END AS dirname 
    FROM data WHERE parent_id=:parent_id AND is_alive
    UNION ALL
    SELECT 
        t.dirname AS parent, 
        data.name, 
        data.is_dir, 
        data.size, 
        data.id, 
        CASE WHEN data.is_dir THEN t.dirname || '/' || REPLACE(data.name, '/', '|') END AS dirname
    FROM t JOIN data ON(t.id = data.parent_id) WHERE data.is_alive
)
SELECT * FROM t"""
    dirname = "/" + dirname.strip("/")
    with transact(alist_db) as cur:
        if clean:
            cur.execute("DELETE FROM x_search_nodes WHERE parent=? OR parent LIKE ? || '/%';", (dirname, dirname))
        count = 0
        it = (t[:4] for t in query(con, sql, locals()))
        executemany = cur.executemany
        for items in batched(it, 10_000):
            executemany("INSERT INTO x_search_nodes(parent, name, is_dir, size) VALUES (?, ?, ?, ?)", items)
            count += len(items)
        return count

# TODO: 增加函数，用来导出到 efu (everything)、mlocatedb 等软件的索引数据库
