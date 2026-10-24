import argparse
from src import server
from src import config
from src.load_data import init_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="论文资料库查看器")
    parser.add_argument("--no-open-viewer", action="store_true", default=not config.OPEN_BROWSER, help="启动服务但不自动打开浏览器")
    parser.add_argument("--without-check", action="store_true", help="跳过 repo 数据和附件目录检查")
    parser.add_argument("--port", type=int, default=config.SERVER_PORT, help=f"指定服务端口，默认 {config.SERVER_PORT}")
    parser.add_argument("-s", "--auto-shutdown", action="store_false", default=config.AUTO_SHUTDOWN, help="关闭长时间无请求后的自动退出")
    args = parser.parse_args()
    if not args.without_check:
        init_data()
    server.launch(open_browser=not args.no_open_viewer, port=args.port, auto_shutdown=args.auto_shutdown)
