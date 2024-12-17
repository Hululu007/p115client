#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__doc__ = """\
            \x1b[1;5m🚄\x1b[0m 115 302 极小版 \x1b[1;5m🚇\x1b[0m

    ╭───────────────────────── \x1b[31mWelcome to \x1b[1m115 nano 302\x1b[0m ────────────────────────────╮
    │                                                                              │
    │  \x1b[1;35mmaintained by\x1b[0m \x1b[3;5;31m❤\x1b[0m     \x1b[32mChenyangGao \x1b[4;34mhttps://chenyanggao.github.io\x1b[0m               │
    │                                                                              │
    │                      \x1b[32mGithub      \x1b[4;34mhttps://github.com/ChenyangGao/p115client/\x1b[0m  │
    │                                                                              │
    │                      \x1b[32mlicence     \x1b[4;34mhttps://www.gnu.org/licenses/gpl-3.0.txt\x1b[0m    │
    │                                                                              │
    │                      \x1b[32mversion     \x1b[1;36m0.0.1\x1b[0m                                       │
    │                                                                              │
    ╰──────────────────────────────────────────────────────────────────────────────╯

⏰ 仅支持用 \x1b[3;36mpickcode\x1b[0m 查询

🌰 查询示例：

    0. 查询 \x1b[3;36mpickcode\x1b[0m
        \x1b[4;34mhttp://localhost:8000?ecjq9ichcb40lzlvx\x1b[0m
        \x1b[4;34mhttp://localhost:8000/ecjq9ichcb40lzlvx\x1b[0m
        \x1b[4;34mhttp://localhost:8000?pickcode=ecjq9ichcb40lzlvx\x1b[0m
    1. 带（任意）名字查询 \x1b[3;36mpickcode\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?ecjq9ichcb40lzlvx\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?pickcode=ecjq9ichcb40lzlvx\x1b[0m
"""

from argparse import ArgumentParser, Namespace, RawTextHelpFormatter

parser = ArgumentParser(description=__doc__, formatter_class=RawTextHelpFormatter)
parser.add_argument("-c", "--cookies", default="", help="cookies 字符串，优先级高于 -cp/--cookies-path")
parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000，如果为 0 则自动确定")
parser.add_argument("-d", "--debug", action="store_true", help="启用调试，会输出更详细信息")
parser.add_argument("-uc", "--uvicorn-run-config-path", help="uvicorn 启动时的配置文件路径，会作为关键字参数传给 `uvicorn.run`，支持 JSON、YAML 或 TOML 格式，会根据扩展名确定，不能确定时视为 JSON")
parser.add_argument("-v", "--version", action="store_true", help="输出版本号")
parser.add_argument("-l", "--license", action="store_true", help="输出授权信息")


def parse_args(argv: None | list[str] = None, /) -> Namespace:
    args = parser.parse_args(argv)
    if args.version:
        from p115nano302 import __version__
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
    elif args.license:
        from p115nano302 import __license__
        print(__license__)
        raise SystemExit(0)
    return args


def main(argv: None | list[str] | Namespace = None, /):
    if isinstance(argv, Namespace):
        args = argv
    else:
        args = parse_args(argv)

    from p115client import P115Client

    if cookies := args.cookies.strip():
        client = P115Client(cookies, check_for_relogin=True)
    else:
        from pathlib import Path
        client = P115Client(Path(args.cookies_path or "115-cookies.txt"), check_for_relogin=True)

    uvicorn_run_config_path = args.uvicorn_run_config_path
    if uvicorn_run_config_path:
        file = open(uvicorn_run_config_path, "rb")
        match suffix := Path(uvicorn_run_config_path).suffix.lower():
            case ".yml" | "yaml":
                from yaml import load as yaml_load, Loader
                run_config = yaml_load(file, Loader=Loader)
            case ".toml":
                from tomllib import load as toml_load
                run_config = toml_load(file)
            case _:
                from orjson import loads as json_loads
                run_config = json_loads(file.read())
    else:
        run_config = {}

    if args.host:
        run_config["host"] = args.host
    else:
        run_config.setdefault("host", "0.0.0.0")
    if args.port:
        run_config["port"] = args.port
    elif not run_config.get("port"):
        from socket import create_connection

        def get_available_ip(start: int = 1024, stop: int = 65536) -> int:
            for port in range(start, stop):
                try:
                    with create_connection(("127.0.0.1", port), timeout=1):
                        pass
                except OSError:
                    return port
            raise RuntimeError("no available ports")

        run_config["port"] = get_available_ip()

    run_config.setdefault("proxy_headers", True)
    run_config.setdefault("server_header", False)
    run_config.setdefault("forwarded_allow_ips", "*")
    run_config.setdefault("timeout_graceful_shutdown", 1)

    from p115nano302 import make_application
    from uvicorn import run

    print(__doc__)
    app = make_application(client, debug=args.debug)
    run(app, **run_config)


if __name__ == "__main__":
    from pathlib import Path
    from sys import path

    path[0] = str(Path(__file__).parents[1])
    main()

