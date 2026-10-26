"""Legacy browser mode for explicit development use; desktop is the default."""
import argparse
import fcntl
import os
from pathlib import Path
import sys

from .config import load_accounts
from .demo import seed
from .service import MailService
from .web import MailServer

# ==========================================
# Function: Run a single local TeleMail instance.
# Method: Resolve TeleMail-only profile paths, lock the database, and start workers and loopback UI.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description='TeleMail 本地邮件客户端')
    parser.add_argument('--demo', action='store_true', help='使用合成邮件，不连接真实邮箱')
    parser.add_argument('--config', type=Path, help='账户配置文件；默认使用 TeleMail 配置目录')
    parser.add_argument('--data', type=Path, help='本地数据目录')
    parser.add_argument('--port', type=int, default=8765, help='localhost 端口，0 自动分配')
    parser.add_argument('--interval', type=int, default=60, help='收件轮询秒数（至少 15）')
    args = parser.parse_args()
    os.umask(0o077)
    from .storage_paths import StorageLocations, configure_cache
    locations = StorageLocations(args.demo, args.config, args.data)
    configure_cache(locations)
    data_dir = locations.data
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (data_dir / 'instance.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('该数据目录已有运行中的 TeleMail，请使用另一端口和 --data 目录')
    try:
        accounts = [] if args.demo else load_accounts(locations.config)
        service = MailService(data_dir, accounts, interval=args.interval, demo=args.demo)
        if args.demo:
            seed(service.store)
        server = MailServer(args.port, service)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    service.start()
    print(f'TeleMail 已启动：http://127.0.0.1:{server.server_port}', flush=True)
    print('演示模式 · 使用合成邮件，禁用外发' if args.demo else '真实邮箱模式 · 授权信息来自环境变量', flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\n正在关闭 TeleMail…', flush=True)
    finally:
        server.server_close()
        service.close()
        lock.close()

if __name__ == '__main__':
    main()
