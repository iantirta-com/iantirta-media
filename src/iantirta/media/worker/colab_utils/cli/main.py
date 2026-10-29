import argparse
import sys
from inspect import cleandoc

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
        sessions = subs.add_parser(
            'session',
            help='Colab Sessions Management'
        )
        sessions.set_defaults(func=lambda _: exit(sessions.format_help()))
        sess_subs = sessions.add_subparsers()

        new = sess_subs.add_parser(
            'new',
            help='Create new session'
        )
        new.add_argument(
            '-s',
            help='Session name'
        )

        list = sess_subs.add_parser(
            'list',
            help='List all sessions'
        )

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

    def run(self, cmdargs: list):
        args = self.parser.parse_args(cmdargs)
        args.func(args)

def main():
    args = sys.argv[1:]
    Colab().run(args)
