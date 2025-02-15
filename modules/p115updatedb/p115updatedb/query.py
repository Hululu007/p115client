#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "get_dir_count", "has_id", "iter_existing_id", "get_parent_id", "iter_parent_id", 
    "iter_id_to_parent_id", "iter_id_to_path", "id_to_path", "get_id", "get_pickcode", 
    "get_sha1", "get_path", "get_ancestors", "get_attr", "iter_children", 
    "iter_descendants", "iter_descendants_dfs", "iter_files_with_path_url", 
    "iter_dup_files", "iter_dangling_parent_ids", "iter_dangling_ids", "select_na_ids", 
    "select_mtime_groups", "dump_to_alist", 
]

from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime
from errno import ENOENT, ENOTDIR
from itertools import batched
from os.path import expanduser
from pathlib import Path
from sqlite3 import register_converter, Connection, Cursor, OperationalError
from posixpath import join
from typing import cast, overload, Any, Final, Literal
from urllib.parse import quote

from iterutils import bfs_gen, group_collect
from orjson import dumps, loads
from posixpatht import escape, path_is_dir_form, splits
from sqlitetools import find, query, transact


FIELDS: Final = (
    "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", "type", 
    "ctime", "mtime", "is_collect", "is_alive", "updated_at", 
)
EXTENDED_FIELDS: Final = (*FIELDS, "path", "posixpath", "ancestors")

register_converter("DATETIME", lambda dt: datetime.fromisoformat(str(dt, "utf-8")))
register_converter("JSON", loads)


def get_dir_count(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
    is_alive: bool = True, 
) -> None | dict:
    """获取某个目录里的文件数和目录数统计
    """
    sql = "SELECT dir_count, file_count, tree_dir_count, tree_file_count FROM dirlen WHERE id=?"
    if is_alive:
        sql += " AND is_alive"
    return find(con, sql, id, row_factory="dict")


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
    return query(con, sql, row_factory="one")


def get_parent_id(
    con: Connection | Cursor, 
    id: int = 0, 
    /, 
    default: None | int = None, 
) -> int:
    if id == 0:
        return 0
    sql = "SELECT parent_id FROM data WHERE id=?"
    return find(con, sql, id, FileNotFoundError(ENOENT, id) if default is None else default)


def iter_parent_id(
    con: Connection | Cursor, 
    ids: Iterable[int], 
    /, 
) -> Iterator[int]:
    sql = "SELECT parent_id FROM data WHERE id IN (%s)" % (",".join(map("%d".__mod__, ids)) or "NULL")
    return query(con, sql, row_factory="one")


def iter_id_to_parent_id(
    con: Connection | Cursor, 
    ids: Iterable[int], 
    /, 
    recursive: bool = False, 
) -> Iterator[tuple[int, int]]:
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
        return iter((0,))
    if len(patht) > 2:
        sql = "SELECT id FROM data WHERE parent_id=? AND name=? AND is_alive AND is_dir LIMIT 1"
        for name in patht[1:-1]:
            parent_id = find(con, sql, (parent_id, name), default=-1)
            if parent_id < 0:
                return iter(())
    sql = "SELECT id FROM data WHERE parent_id=? AND name=? AND is_alive"
    if ensure_file is None:
        sql += " ORDER BY is_dir DESC"
    elif ensure_file:
        sql += " AND NOT is_dir"
    else:
        sql += " AND is_dir LIMIT 1"
    return query(con, sql, (parent_id, patht[-1]), row_factory="one")


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
    return find(
        con, 
        f"SELECT {','.join(FIELDS)} FROM data WHERE id=? LIMIT 1", 
        id, 
        FileNotFoundError(ENOENT, id), 
        row_factory="dict", 
    )


def iter_children(
    con: Connection | Cursor, 
    parent_id: int | dict = 0, 
    /, 
    ensure_file: None | bool = None, 
) -> Iterator[dict]:
    """获取某个目录之下的文件或目录的信息

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
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
    if not attr["is_dir"]:
        raise NotADirectoryError(ENOTDIR, attr)
    sql = f"SELECT {','.join(FIELDS)} FROM data WHERE parent_id=? AND is_alive"
    if ensure_file is not None:
        if ensure_file:
            sql += " AND NOT is_dir"
        else:
            sql += " AND is_dir"
    return query(con, sql, attr["id"], row_factory="dict")


def iter_descendants(
    con: Connection | Cursor, 
    parent_id: int | dict = 0, 
    /, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    use_relpath: bool = False, 
    topdown: None | bool = True, 
) -> Iterator[dict]:
    """遍历获取某个目录之下的所有文件或目录的信息

    :param con: 数据库连接或游标
    :param parent_id: 顶层目录的 id
    :param max_depth: 最大深度。如果小于 0，则无限深度
    :param ensure_file: 是否仅输出文件

        - 如果为 True，仅输出文件
        - 如果为 False，仅输出目录
        - 如果为 None，全部输出

    :param use_relpath: 仅输出相对路径，否则输出完整路径（从 / 开始）
    :param topdown: 是否自顶向下深度优先遍历

        - 如果为 True，则自顶向下深度优先遍历
        - 如果为 False，则自底向上深度优先遍历
        - 如果为 None，则自顶向下宽度优先遍历

    :return: 迭代器，产生一组信息的字典
    """
    if isinstance(parent_id, int):
        if use_relpath:
            ancestors = []
            dir_ = posixdir = ""
        else:
            ancestors = get_ancestors(con, parent_id)
            dir_ = "/".join(escape(a["name"]) for a in ancestors) + "/"
            posixdir = "/".join(a["name"].replace("/", "|") for a in ancestors) + "/"
    else:
        attr = parent_id
        ancestors = attr["ancestors"]
        dir_ = attr["path"]
        posixdir = attr["posixpath"]
        if dir_ != "/":
            dir_ += "/"
            posixdir += "/"
    if topdown is None:
        gen = bfs_gen((parent_id, max_depth, ancestors, dir_, posixdir))
        send = gen.send
        for parent_id, depth, ancestors, dir_, posixdir in gen:
            depth -= depth > 0
            for attr in iter_children(con, parent_id, False if ensure_file is False else None):
                ancestors = attr["ancestors"] = [
                    *ancestors, 
                    {k: attr[k] for k in ("id", "parent_id", "name")}, 
                ]
                dir_ = attr["path"] = dir_ + escape(attr["name"])
                posixdir = attr["posixpath"] = posixdir + attr["name"].replace("/", "|")
                is_dir = attr["is_dir"]
                if is_dir and depth:
                    send((attr, depth, ancestors, dir_ + "/", posixdir + "/")) # type: ignore
                if ensure_file is None:
                    yield attr
                elif is_dir:
                    if not ensure_file:
                        yield attr
                elif ensure_file:
                    yield attr
    else:
        max_depth -= max_depth > 0
        for attr in iter_children(con, parent_id, False if ensure_file is False else None):
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
def iter_descendants_dfs(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    use_relpath: bool = False, 
    *, 
    fields: str, 
) -> Iterator[Any]:
    ...
@overload
def iter_descendants_dfs(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    use_relpath: bool = False, 
    *, 
    fields: None | tuple[str, ...] = None, 
    to_dict: Literal[False], 
) -> Iterator[tuple[Any, ...]]:
    ...
@overload
def iter_descendants_dfs(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    use_relpath: bool = False, 
    *, 
    fields: None | tuple[str, ...] = None, 
    to_dict: Literal[True] = True, 
) -> Iterator[dict[str, Any]]:
    ...
def iter_descendants_dfs(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    max_depth: int = -1, 
    ensure_file: None | bool = None, 
    use_relpath: bool = False, 
    *, 
    fields: None | str | tuple[str, ...] = None, 
    to_dict: bool = True, 
) -> Iterator:
    """获取某个目录之下的所有目录节点的 id 或者信息字典

    :param con: 数据库连接或游标
    :param parent_id: 顶层目录的 id
    :param max_depth: 最大深度。如果小于 0，则无限深度
    :param ensure_file: 是否仅输出文件

        - 如果为 True，仅输出文件
        - 如果为 False，仅输出目录
        - 如果为 None，全部输出

    :param use_relpath: 仅输出相对路径，否则输出完整路径（从 / 开始）
    :param fields: 需要获取的字段，接受如下这些：

        .. code:: python

            (
                "id", "parent_id", "pickcode", "sha1", "name", "size", "is_dir", 
                "type", "ctime", "mtime", "is_collect", "is_alive", "updated_at", 
                "ancestors", "path", "posixpath", 
            )

        - 如果为 None，则获取如上所有
        - 如果为 str，则获取指定的字段的值
        - 如果为 tuple，则拉取这一组字段的值（但会过滤掉不可用的）

    :param to_dict: 是否产生字典，如果为 True 且 fields 不为 str，则产生字典

    :return: 迭代器，产生一组数据
    """
    one_value = False
    if fields is None:
        with_id = with_path = with_posixpath = with_ancestors = True
        fields = FIELDS
    elif isinstance(fields, str):
        one_value = True
        if fields not in EXTENDED_FIELDS:
            raise ValueError(f"invalid field {fields!r}, must be in {EXTENDED_FIELDS!r}")
        with_id = "id" == fields
        with_path = "path" == fields
        with_posixpath = "posixpath" == fields
        with_ancestors = "ancestors" == fields
        if with_path or with_posixpath or with_ancestors:
            fields = ()
        else:
            fields = fields,
    else:
        seen = set(fields)
        with_id = "id" in seen
        with_path = "path" in seen
        with_posixpath = "posixpath" in seen
        with_ancestors = "ancestors" in seen
        fields = tuple(f for f in FIELDS if f in seen)
        del seen
    if with_id:
        fields0 = fields
    else:
        fields0 = ("id", *fields)
    with_route = with_path or with_posixpath or with_ancestors
    if with_route:
        IDX_ID = 0
        try:
            IDX_PID = fields0.index("parent_id", 1)
        except ValueError:
            IDX_PID = len(fields0)
            fields0 += "parent_id",
        try:
            IDX_NAME = fields0.index("name", 1)
        except ValueError:
            IDX_NAME = len(fields0)
            fields0 += "name",
        try:
            IDX_ISDIR = fields0.index("is_dir", 1)
        except ValueError:
            IDX_ISDIR = len(fields0)
            fields0 += "is_dir",
        if use_relpath:
            path = posixpath = ""
            ancestors = []
        elif parent_id:
            ancestors = get_ancestors(con, parent_id)
            if with_path:
                path = "/".join(escape(a["name"]) for a in ancestors) + "/"
            if with_posixpath:
                posixpath = "/".join(a["name"].replace("/", "|") for a in ancestors) + "/"
        else:
            path = posixpath = "/"
            ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
        if with_ancestors:
            pid_to_ancestors = {parent_id: ancestors}
        if with_path:
            pid_to_dirname = {parent_id: path}
        if with_posixpath:
            pid_to_posix_dirname = {parent_id: posixpath}
    if one_value and not with_route:
        row_factory = lambda _, record, /: record[0]
    else:
        def iter_pairs(record, /):
            if one_value:
                pass
            elif to_dict:
                if with_id:
                    yield from zip(fields, record)
                else:
                    yield from zip(fields, record[1:])
            else:
                if with_id:
                    yield from record[:len(fields)]
                else:
                    yield from record[1:len(fields)+1]
            if with_route:
                id = record[0]
                pid = record[IDX_PID]
                is_dir = record[IDX_ISDIR]
                name = record[IDX_NAME]
                if with_ancestors:
                    ancestors = [
                        *pid_to_ancestors[pid], 
                        {"id": id, "parent_id": pid, "name": name}, 
                    ]
                    if is_dir:
                        pid_to_ancestors[id] = ancestors
                    if one_value or not to_dict:
                        yield ancestors
                    else:
                        yield "ancestors", ancestors   
                if with_path:
                    path = pid_to_dirname[pid] + escape(name)
                    if is_dir:
                        pid_to_dirname[id] = path + "/"
                    if one_value or not to_dict:
                        yield path
                    else:
                        yield "path", path
                if with_posixpath:
                    posixpath = pid_to_posix_dirname[pid] + name.replace("/", "|")
                    if is_dir:
                        pid_to_posix_dirname[id] = posixpath + "/"
                    if one_value or not to_dict:
                        yield posixpath
                    else:
                        yield "posixpath", posixpath
                if is_dir and ensure_file is True:
                    raise ValueError
        def row_factory(_, record):
            try:
                if one_value:
                    if with_route:
                        return next(iter_pairs(record))
                    else:
                        return record[-1]
                elif to_dict:
                    return dict(iter_pairs(record))
                else:
                    return tuple(iter_pairs(record))
            except ValueError:
                pass
    select_fields_1 = ", ".join(fields0)
    if 0 <= max_depth <= 1:
        sql = f"SELECT {select_fields_1} FROM data WHERE parent_id=:parent_id AND is_alive"
        if ensure_file is True:
            sql += " AND NOT is_dir"
        elif ensure_file is False:
            sql += " AND is_dir"
    else:
        select_fields_2 = "data." + ", data.".join(fields0)
        if max_depth < 0:
            args = ("",) * 4
        else:
            args = (
                ", 1 AS depth", 
                "", 
                ", t.depth + 1", 
                " AND depth < :max_depth", 
            )
        if ensure_file is True:
            if "is_dir" not in fields0:
                args = (
                    args[0] + ", is_dir", 
                    args[1], 
                    args[2] + ", data.is_dir", 
                    args[3], 
                )
        elif ensure_file is False:
            args = (
                args[0], 
                args[1] + " AND is_dir", 
                args[2], 
                args[3] + " AND data.is_dir", 
            )
        sql = f"""\
WITH t AS (
    SELECT {select_fields_1}%s FROM data WHERE parent_id=:parent_id AND is_alive%s
    UNION ALL
    SELECT {select_fields_2}%s FROM t JOIN data ON(t.id = data.parent_id) WHERE data.is_alive%s
)
SELECT {", ".join(fields0 if with_route else fields)} FROM t AS data""" % args
        if not with_route and ensure_file is True:
            sql += " WHERE NOT is_dir"
    return filter(None, query(con, sql, locals(), row_factory=row_factory))


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
    for attr in iter_descendants_dfs(
        con, 
        parent_id, 
        fields=("id", "sha1", "pickcode", "size", "name", "posixpath"), 
        ensure_file=True, 
    ):
        yield attr["posixpath"], eval(code, None, attr)


def iter_dup_files(
    con: Connection | Cursor, 
    /, 
) -> Iterator[dict]:
    """罗列所有重复文件

    :param con: 数据库连接或游标

    :return: 迭代器，一组文件的信息
    """
    sql = f"""\
WITH stats AS (
    SELECT
        COUNT(1) OVER w AS total, 
        ROW_NUMBER() OVER w AS nth, 
        {",".join(FIELDS)}
    FROM data
    WHERE NOT is_dir AND is_alive
    WINDOW w AS (PARTITION BY sha1, size)
)
SELECT * FROM stats WHERE total > 1"""
    return query(con, sql, row_factory="dict")


def iter_dangling_parent_ids(
    con: Connection | Cursor, 
    /, 
) -> Iterator[int]:
    """罗列所有悬空的 parent_id

    .. note::
        悬空的 parent_id，即所有的 parent_id 中，，不为 0 且不在 `data` 表中的部分

    :param con: 数据库连接或游标

    :return: 迭代器，一组目录的 id
    """
    sql = """\
WITH pids(id) AS (
    SELECT DISTINCT parent_id FROM data WHERE parent_id
)
SELECT pids.id FROM pids LEFT JOIN data USING (id) WHERE data.id IS NULL"""
    return query(con, sql, row_factory="one")


def iter_dangling_ids(
    con: Connection | Cursor, 
    /, 
) -> Iterator[int]:
    """罗列所有悬空的文件或目录的 id

    .. note::
        悬空的 id，即祖先节点中，存在一个节点，它的 parent_id 是悬空的

    :param con: 数据库连接或游标

    :return: 迭代器，一组目录的 id
    """
    sql = """\
WITH pids(id) AS (
    SELECT DISTINCT parent_id FROM data WHERE parent_id
), dangling_pids(parent_id) AS (
    SELECT pids.id FROM pids LEFT JOIN data USING (id) WHERE data.id IS NULL
), dangling_ids AS (
    SELECT data.parent_id FROM data JOIN dangling_pids USING (parent_id)
    UNION ALL
    SELECT data.parent_id FROM dangling_ids JOIN data USING (parent_id)
)
SELECT parent_id AS id FROM dangling_ids"""
    return query(con, sql, row_factory="one")


def select_na_ids(
    con: Connection | Cursor, 
    /, 
) -> set[int]:
    """找出所有的失效节点和悬空节点的 id

    .. note::
        悬空节点，就是此节点有一个祖先节点的 parant_id，不为 0 且不在 `data` 表中

    :param con: 数据库连接或游标

    :return: 一组悬空节点的 id 的集合
    """
    ok_ids: set[int] = set(query(con, "SELECT id FROM data WHERE NOT is_alive", row_factory="one"))
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
) -> list[tuple[int, set[int]]]:
    """获取某个目录之下的节点（不含此节点本身），按 mtime 进行分组，相同 mtime 的 id 归入同一组

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
    :param tree: 是否拉取目录树，如果为 True，则拉取全部后代的文件节点（不含目录节点），如果为 False，则只拉取子节点（含目录节点）

    :return: 元组的列表（逆序排列），每个元组第 1 个元素是 mtime，第 2 个元素是相同 mtime 的 id 的集合
    """
    if tree:
        it = iter_descendants_dfs(con, parent_id, fields=("mtime", "id"), ensure_file=True, to_dict=False)
    else:
        it = iter_descendants_dfs(con, parent_id, fields=("mtime", "id"), max_depth=1, to_dict=False)
    d: dict[int, set[int]] = group_collect(it, factory=set)
    return sorted(d.items(), reverse=True)


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
        CASE WHEN is_dir THEN CONCAT(:dirname, '/', REPLACE(name, '/', '|')) END AS dirname 
    FROM data WHERE parent_id=:parent_id AND is_alive
    UNION ALL
    SELECT 
        t.dirname AS parent, 
        data.name, 
        data.is_dir, 
        data.size, 
        data.id, 
        CASE WHEN data.is_dir THEN CONCAT(t.dirname, '/', REPLACE(data.name, '/', '|')) END AS dirname
    FROM t JOIN data ON(t.id = data.parent_id) WHERE data.is_alive
)
SELECT parent, name, is_dir, size FROM t"""
    dirname = "/" + dirname.strip("/")
    with transact(alist_db) as cur:
        if clean:
            cur.execute("DELETE FROM x_search_nodes WHERE parent=? OR parent LIKE ? || '/%';", (dirname, dirname))
        count = 0
        executemany = cur.executemany
        for items in batched(query(con, sql, locals()), 10_000):
            executemany("INSERT INTO x_search_nodes(parent, name, is_dir, size) VALUES (?, ?, ?, ?)", items)
            count += len(items)
        return count

# TODO: 增加函数，用来导出到 efu (everything)、mlocatedb 等软件的索引数据库
