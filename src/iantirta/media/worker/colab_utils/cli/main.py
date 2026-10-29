import argparse
import sys
from inspect import cleandoc
from ..state import state
from ..client import Shape


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

        s = state.new_session(args.name)
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

    def run(self, cmdargs: list):
        args = self.parser.parse_args(cmdargs)
        args.func(args)

def main():
    args = sys.argv[1:]
    Colab().run(args)
