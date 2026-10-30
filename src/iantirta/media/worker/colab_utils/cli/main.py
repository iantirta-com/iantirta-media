import argparse
import sys
from inspect import cleandoc
from dataclasses import asdict
from datetime import datetime
import os
import tempfile
import time
from pathlib import Path
from ..state import state
from ..client import Shape
from ..auth import get_user_info

class Colab:
    name = None
    description = None
    epilog = None
    usage = None
    _parser = None

    def __init__(self):
        self._populate_commands()

    def _populate_commands(self):
        parser = self.parser
        parser.set_defaults(func=lambda _: exit(parser.format_help()))

        subs = parser.add_subparsers()

        # Sessions
        session = subs.add_parser(
            'session',
            help='Colab Sessions Management'
        )
        session.set_defaults(func=lambda _: sys.exit(session.format_help()))
        sess_subs = session.add_subparsers()

        new = sess_subs.add_parser(
            'new',
            help='Create new session'
        )
        new.set_defaults(func=self.new_session)
        self.new_session.__func__.__parser = new
        new.add_argument(
            '-s', dest='name',
            help='Session name'
        )
        new.add_argument(
            '--gpu',
            help='Accelerator to use'
        )

        stop = sess_subs.add_parser(
            'stop',
            help='Stop a session'
        )
        stop.set_defaults(func=self.stop_session)
        self.stop_session.__func__.__parser = stop
        stop.add_argument(
            '-s', dest='name',
            help='Session name'
        )

        list = sess_subs.add_parser(
            'list',
            help='List all sessions'
        )
        list.set_defaults(func=self.list_sessions)

        # Kernel
        console = subs.add_parser(
            'console',
            help='Connect to a console runtime'
        )
        console.set_defaults(func=self.console)
        self.console.__func__.__parser = console
        console.add_argument(
            '-s', dest='name',
            help='Session name'
        )

        # Files
        ls = subs.add_parser(
            'ls',
            help='List directory on a runtime session'
        )
        ls.set_defaults(func=self.ls)
        self.ls.__func__.__parser = ls
        ls.add_argument(
            '-s', dest='name',
            required=True,
            help='Session name'
        )
        ls.add_argument(
            'remote_path', nargs='?', default='content',
            help='path to list'
        )

        cat = subs.add_parser(
            'cat',
            help='List directory on a runtime session'
        )
        cat.set_defaults(func=self.cat)
        self.cat.__func__.__parser = cat
        cat.add_argument(
            '-s', dest='name',
            required=True,
            help='Session name'
        )
        cat.add_argument(
            'remote_path',
            help='path to list'
        )

        tail = subs.add_parser(
            "tail",
            help="Display the end of a remote file",
            description="Display the last lines of a remote file, optionally following updates.",
        )
        tail.set_defaults(func=self.tail)
        self.tail.__func__.__parser = tail

        tail.add_argument(
            "-s",
            dest="name",
            required=True,
            help="Runtime session name",
        )
        tail.add_argument(
            "-n",
            "--lines",
            type=int,
            default=10,
            help="Number of lines to display (default: 10)",
        )
        tail.add_argument(
            "-f",
            "--follow",
            action="store_true",
            help="Follow appended content",
        )
        tail.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Polling interval in seconds (default: 1)",
        )
        tail.add_argument(
            "remote_path",
            help="Remote file path",
        )

        # Others
        quota = subs.add_parser(
            'quota',
            help='Show usage quota'
        )
        quota.set_defaults(func=self.get_quota)

        whoami = subs.add_parser(
            'whoami',
            help='Display user auth information'
        )
        whoami.set_defaults(func=self.whoami)

    @property
    def prog(self):
        return 'icolab'

    @property
    def parser(self):
        if not self._parser:
            self._parser = argparse.ArgumentParser(
                    formatter_class=argparse.RawDescriptionHelpFormatter,
                    prog=self.prog,
                    description=cleandoc(
                        self.description or self.__doc__ or ""
                    ),
                    epilog=cleandoc(self.epilog or ""),
                )
        return self._parser

    def sessions(self, args):
        print('Sessions', args)

    def new_session(self, args):
        if not args.name:
            sys.exit(f"{self.new_session.__parser.format_help()}\n\nSpecify a name for session.")

        s = state.new_session(args.name, gpu=args.gpu)
        print(f"Session [{s.name}] ready.")

    def stop_session(self, args):
        if not args.name:
            sys.exit(f"{self.stop_session.__parser.format_help()}\n\nSpecify a name to stop a session.")

        state.stop_session(args.name, reason='user_requested')
        print(f"Session [{args.name}] terminated")

    def list_sessions(self, args):
        sessions = state.get_sessions()
        if not sessions:
            sys.exit('No active sessions is found.')
        
        for s in sessions.values():
            parts = [
                f"[{s.name}] {s.endpoint}",
                f"Hardware: {'CPU' if s.accelerator == 'NONE' else s.accelerator}",
                f"Shape: {'High-RAM' if s.machine_shape in (Shape.HIGH_RAM, 'HIGH_RAM', 1) else 'Standard'}",
                f"Variant: {s.variant}",
            ]
            # if status is not None:
            #     parts.append(f"Status: {status}")
            print(" | ".join(parts))

    # Kernel
    def console(self, args):
        if not args.name:
            sys.exit(f"{self.console.__parser.format_help()}\n\nSpecify a name to connect to a console.")

        s = state.get_session(args.name)
        state.kernel.console(s)

    # Files
    def ls(self, args):
        s = state.get_session(args.name)
        data = state.contents.list_dir(s, args.remote_path)
        state.history.log_event(args.name, "file_operation", {"op": "ls", "path": args.remote_path})
        if data.get("type") == "directory":
            items = data.get("content", [])
            for item in sorted(
                items, key=lambda x: (x.get("type") != "directory", x.get("name"))
            ):
                suffix = "/" if item.get("type") == "directory" else ""
                modified = item.get("last_modified", "-")
                try:
                    modified = datetime.fromisoformat(
                        modified
                    ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError):
                    pass
                print(f"{modified}\t{item.get('name')}{suffix}")
        else:
            print(data)

    def cat(self, args):
        s = state.get_session(args.name)
        content = state.contents.read_bytes(s, args.remote_path)

        state.history.log_event(
            args.name,
            "file_operation",
            {"op": "cat", "remote": args.remote_path},
        )
        sys.stdout.write(content.decode('utf-8'))

    def tail(self, args):
        if args.lines < 0:
            raise SystemExit(f"{self.tail.__parser.format_help()}\n\nError: -n,--lines must be non-negative")
        if args.interval <= 0:
            raise SystemExit(f"{self.tail.__parser.format_help()}\n\nError: --interval must be greater than zero")

        s = state.get_session(args.name)
        path = args.remote_path

        # Read the initial contents once.
        content = state.contents.read_bytes(s, path)
        initial_lines = content.splitlines(keepends=True)

        if args.lines:
            sys.stdout.buffer.write(b"".join(initial_lines[-args.lines:]))
            sys.stdout.buffer.flush()
    
        offset = len(content)
    
        state.history.log_event(
            args.name,
            "file_operation",
            {"op": "tail", "path": path, "follow": args.follow},
        )
    
        if not args.follow:
            return

        try:
            while True:
                time.sleep(args.interval)
                chunk, total = state.contents.read_range(s, path, offset)
                
                if total < offset:
                    # The file was truncated below our previous offset.
                    print(
                        f"\n--- {path}: file truncated ---",
                        file=sys.stderr,
                    )
                    offset = 0
                    continue

                if chunk:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                    offset += len(chunk)

        except KeyboardInterrupt:
            print(file=sys.stderr)

    # Other
    def get_quota(self, args):
        data = asdict(state.client.get_consumption_user_info())
        for k, v in data.items():
            if isinstance(v, dict):
                for _k, _v in v.items():
                    if isinstance(_v, datetime):
                        v[_k] = _v.ctime()
            print(k, ':', v)

    def whoami(self, args):
        user_info = get_user_info()
        for k, v in user_info.items():
            print(k, ':', v)

    def run(self, cmdargs: list):
        args = self.parser.parse_args(cmdargs)
        args.func(args)

def main():
    args = sys.argv[1:]
    Colab().run(args)
