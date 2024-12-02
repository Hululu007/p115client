#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "FIELDS", "query", "query_all", "attr_to_path_gen", "attr_to_path", "get_id_from_db", 
    "get_pickcode_from_db", "get_sha1_from_db", "get_path_from_db", "get_ancestors_from_db", 
    "get_attr_from_db", "get_children_from_db", "iter_descendants_from_db", 
]

from collections import deque
from collections.abc import Mapping, Iterator, Sequence
from contextlib import closing
from sqlite3 import Connection
from typing import Any

from dictattr import AttrDict
from encode_uri import encode_uri_component_loose
from p115client.tool import P115ID
from posixpatht import joins, path_is_dir_form, splits


FIELDS = ("id", "parent_id", "pickcode", "sha1", "name", "mtime", "size", "type", "is_dir", "is_collect")


def normattr(m, /) -> AttrDict:
    attr: AttrDict = AttrDict(m)
    name = encode_uri_component_loose(attr["name"])
    if attr["is_dir"]:
        attr["url"] = f"/{name}?file=false&id={attr['id']}"
        attr["ico"] = "folder"
    else:
        attr["url"] = f"/{name}?file=true&pickcode={attr['pickcode']}"
        if attr["is_collect"] and attr["size"] < 1024 * 1024 * 115:
            attr["url"] += "&web=true"
        attr["ico"] = attr["name"].rpartition(".")[-1].lower()
    return attr


ROOT = normattr({
    "id": "0", "parent_id": "0", "pickcode": "", "sha1": "", "name": "", 
    "mtime": 0, "size": 0, "type": 0, "is_dir": 1, "is_collect": 0, 
})


def query(
    con: Connection, 
    sql: str, 
    params: Any = None, 
    default: Any = None, 
):
    with closing(con.cursor()) as cur:
        if params is None:
            cur.execute(sql)
        elif isinstance(params, (tuple, Mapping)):
            cur.execute(sql, params)
        elif isinstance(params, list):
            cur.executemany(sql, params)
        else:
            cur.execute(sql, (params,))
        record = cur.fetchone()
    if record is None:
        if isinstance(default, BaseException):
            raise default
        return default
    return record[0]


def query_all(
    con: Connection, 
    sql: str, 
    params: Any = None, 
) -> list:
    with closing(con.cursor()) as cur:
        if params is None:
            cur.execute(sql)
        elif isinstance(params, (tuple, Mapping)):
            cur.execute(sql, params)
        elif isinstance(params, list):
            cur.executemany(sql, params)
        else:
            cur.execute(sql, (params,))
        return cur.fetchall()


def attr_to_path_gen(
    con: Connection, 
    path: str | Sequence[str] = "", 
    ensure_file: None | bool = None, 
    /, 
    parent_id: int = 0, 
) -> Iterator[AttrDict]:
    patht: Sequence[str]
    if isinstance(path, str):
        if ensure_file is None and path_is_dir_form(path):
            ensure_file = False
        patht, _ = splits("/" + path)
    else:
        patht = path
    if not parent_id and len(patht) == 1:
        yield ROOT
        return
    with closing(con.cursor()) as cur:
        execute = cur.execute
        if len(patht) > 2:
            sql = "SELECT id FROM data WHERE parent_id=? AND is_dir AND name=? LIMIT 1"
            for name in patht[1:-1]:
                val = execute(sql, (parent_id, name)).fetchone()
                if val is None:
                    return
                parent_id, = val
        sql = """\
SELECT CAST(id AS TEXT), CAST(parent_id AS TEXT), pickcode, sha1, name, mtime, size, type, is_dir, is_collect
FROM data WHERE parent_id=? AND name=?"""
        if ensure_file is None:
            sql += " ORDER BY is_dir DESC"
        elif ensure_file:
            sql += " AND NOT is_dir"
        else:
            sql += " AND is_dir LIMIT 1"
        for record in execute(sql, (parent_id, patht[-1])):
            yield normattr(zip(FIELDS, record))


def attr_to_path(
    con: Connection, 
    path: str | Sequence[str] = "", 
    ensure_file: None | bool = None, 
    /, 
    parent_id: int = 0, 
) -> None | AttrDict:
    return next(attr_to_path_gen(con, path, ensure_file, parent_id), None)


def get_id_from_db(
    con: Connection, 
    pickcode: str = "", 
    sha1: str = "", 
    path: str = "", 
) -> int:
    if pickcode:
        return query(con, "SELECT id FROM data WHERE pickcode=? LIMIT 1;", pickcode, default=FileNotFoundError(pickcode))
    elif sha1:
        return query(con, "SELECT id FROM data WHERE sha1=? LIMIT 1;", sha1, default=FileNotFoundError(sha1))
    elif path:
        attr = attr_to_path(con, path)
        if attr is None:
            raise FileNotFoundError(path)
        return P115ID(attr["id"], attr=attr)
    return 0


def get_pickcode_from_db(
    con: Connection, 
    id: int = 0, 
    sha1: str = "", 
    path: str = "", 
) -> str:
    if id:
        if id == 0:
            raise IsADirectoryError("root directory has no pickcode")
        return query(con, "SELECT pickcode FROM data WHERE id=? AND LENGTH(pickcode) LIMIT 1;", id, default=FileNotFoundError(id))
    elif sha1:
        return query(con, "SELECT pickcode FROM data WHERE sha1=? AND LENGTH(pickcode) LIMIT 1;", sha1, default=FileNotFoundError(sha1))
    else:
        if path in ("", "/"):
            raise IsADirectoryError("root directory has no pickcode")
        attr = attr_to_path(con, path)
        if attr is None:
            raise FileNotFoundError(path)
        return attr["pickcode"]


def get_sha1_from_db(
    con: Connection, 
    id: int = 0, 
    pickcode: str = "", 
    path: str = "", 
) -> str:
    if id:
        if id == 0:
            raise IsADirectoryError("root directory has no sha1")
        return query(con, "SELECT sha1 FROM data WHERE id=? AND LENGTH(sha1) LIMIT 1;", id, default=FileNotFoundError(id))
    elif pickcode:
        return query(con, "SELECT sha1 FROM data WHERE pickcode=? AND LENGTH(sha1) LIMIT 1;", pickcode, default=FileNotFoundError(pickcode))
    elif path:
        if path in ("", "/"):
            raise IsADirectoryError("root directory has no sha1")
        attr = attr_to_path(con, path)
        if attr is None:
            raise FileNotFoundError(path)
        elif attr["is_dir"]:
            raise IsADirectoryError(path)
        return attr["sha1"]
    raise IsADirectoryError(path)


def get_path_from_db(
    con: Connection, 
    id: int = 0, 
) -> str:
    ancestors = get_ancestors_from_db(con, id)
    return joins([a["name"] for a in ancestors])


def get_ancestors_from_db(
    con: Connection, 
    id: int = 0, 
) -> list[dict]:
    ancestors = [{"id": "0", "parent_id": "0", "name": ""}]
    if id == 0:
        return ancestors
    ls = query_all(con, """\
WITH RECURSIVE t AS (
    SELECT id, parent_id, name FROM data WHERE id = ?
    UNION ALL
    SELECT data.id, data.parent_id, data.name FROM t JOIN data ON (t.parent_id = data.id)
)
SELECT CAST(id AS TEXT), CAST(parent_id AS TEXT), name FROM t;""", id)
    if not ls:
        raise FileNotFoundError(id)
    if ls[-1][1] != "0":
        raise ValueError(f"dangling id: {id}")
    ancestors.extend(dict(zip(("id", "parent_id", "name"), map(str, record))) for record in reversed(ls))
    return ancestors


def get_attr_from_db(
    con: Connection, 
    id: int = 0, 
) -> AttrDict:
    if id == 0:
        return ROOT
    ls = query_all(con, """\
SELECT CAST(id AS TEXT), CAST(parent_id AS TEXT), pickcode, sha1, name, mtime, size, type, is_dir, is_collect
FROM data WHERE id=? LIMIT 1""", id)
    if not ls:
        raise FileNotFoundError(id)
    return normattr(zip(FIELDS, ls[0]))


def get_children_from_db(
    con: Connection, 
    id: int = 0, 
) -> list[AttrDict]:
    attr = get_attr_from_db(con, id)
    if not attr["is_dir"]:
        raise NotADirectoryError(id)
    return [normattr(zip(FIELDS, record)) for record in query_all(con, """\
SELECT CAST(id AS TEXT), CAST(parent_id AS TEXT), pickcode, sha1, name, mtime, size, type, is_dir, is_collect
FROM data WHERE parent_id=?""", id)]


def iter_descendants_from_db(
    con: Connection, 
    id: int = 0, 
    depth_first: bool = False, 
) -> Iterator[AttrDict]:
    if depth_first:
        for attr in get_children_from_db(con, id):
            yield attr
            if attr["is_dir"]:
                yield from get_children_from_db(con, int(attr["id"]))
    else:
        dq: deque[int] = deque((id,))
        push, pop = dq.append, dq.popleft
        while dq:
            for attr in get_children_from_db(con, id):
                yield attr
                if attr["is_dir"]:
                    dq.append(int(attr["id"]))

