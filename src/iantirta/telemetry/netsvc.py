
import locale
import logging
import logging.handlers
import os
import platform
import sys
import warnings
from collections.abc import Callable
from typing import Literal

DEFAULT_LOGGING_FORMAT = '[%(asctime)s] %(levelname)s %(name)s: %(message)s %(perf_info)s'


BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, _NOTHING, DEFAULT = range(10)
#The background is set with 40 plus the number of the color, and the foreground with 30
#These are the sequences needed to get colored output
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"
COLOR_PATTERN = f"{COLOR_SEQ}{COLOR_SEQ}%s{RESET_SEQ}"
LEVEL_COLOR_MAPPING = {
    logging.DEBUG: (BLUE, DEFAULT),
    logging.INFO: (GREEN, DEFAULT),
    logging.WARNING: (YELLOW, DEFAULT),
    logging.ERROR: (RED, DEFAULT),
    logging.CRITICAL: (WHITE, RED),
}


def get_locales(lang=None):
    if lang is None:
        lang = locale.getlocale()[0]

    def process(enc):
        ln = locale._build_localename((lang, enc))
        yield ln
        nln = locale.normalize(ln)
        if nln != ln:
            yield nln

    for x in process('utf8'): yield x

    prefenc = locale.getpreferredencoding()
    if prefenc:
        for x in process(prefenc): yield x

        prefenc = {
            'latin1': 'latin9',
            'iso-8859-1': 'iso8859-15',
            'cp1252': '1252',
        }.get(prefenc.lower())
        if prefenc:
            for x in process(prefenc): yield x

    yield lang


def resetlocale():
    # locale.resetlocale is bugged with some locales.
    for ln in get_locales():
        try:
            return locale.setlocale(locale.LC_ALL, ln)
        except locale.Error:
            continue


class LoggingHookManager:
    _hooks: list[Callable] = []

    @classmethod
    def dispatch(cls, record):
        if not cls._hooks:
            return
        try:
            for hook in cls._hooks:
                hook(record)
        except:
            pass


def add_hook(hook: Callable):
    LoggingHookManager._hooks.append(hook)


class WatchedFileHandler(logging.handlers.WatchedFileHandler):
    def __init__(self, filename):
        self.errors = None  # py38
        super().__init__(filename)
        # Unfix bpo-26789, in case the fix is present
        self._builtin_open = None

    def _open(self):
        return open(self.baseFilename, self.mode, encoding=self.encoding, errors=self.errors)


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        fg_color, bg_color = LEVEL_COLOR_MAPPING.get(record.levelno, (GREEN, DEFAULT))
        record.levelname = COLOR_PATTERN % (30 + fg_color, 40 + bg_color, record.levelname.ljust(8))
        return super().format(record)


class LogRecord(logging.LogRecord):
    def __init__(self, name, level, pathname, lineno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
        super().__init__(name, level, pathname, lineno, msg, args, exc_info, func=func, sinfo=sinfo, **kwargs)
        self.perf_info = ""


def setup_logger(
    appname: str,
    format: str = DEFAULT_LOGGING_FORMAT,
    handler_type: Literal["syslog", "filelog", "streamlog"] = "streamlog",
    filelog_path: str | None = None, # Required if filelog
    default_level=logging.WARNING,
    post_emit: bool = True
):
    if logging.getLogRecordFactory() is LogRecord:
        return

    logging.setLogRecordFactory(LogRecord)

    logging.captureWarnings(True)
    # enable deprecation warnings (disabled by default)
    warnings.simplefilter('default', category=DeprecationWarning)
    # need to be adapted later but too muchwork for this pr.
    warnings.filterwarnings('ignore', r'^datetime.datetime.utcnow\(\) is deprecated and scheduled for removal in a future version.*', category=DeprecationWarning)

    resetlocale()

    # Normal Handler on stderr
    handler = logging.StreamHandler()

    if handler_type == 'syslog':
        # SysLog Handler
        if os.name == 'nt':
            handler = logging.handlers.NTEventLogHandler(appname)

        elif platform.system() == 'Darwin':
            handler = logging.handlers.SysLogHandler('/var/run/log')

        else:
            handler = logging.handlers.SysLogHandler('/dev/log')

        format = f'{appname}:%(levelname)s:%(name)s:%(message)s'

    elif handler_type == 'filelog':
        # LogFile Handler
        if not filelog_path:
            raise ValueError("filelog_path required when choosing filelog")

        try:
            # We check we have the right location for the log files
            dirname = os.path.dirname(filelog_path)
            if dirname and not os.path.isdir(dirname):
                os.makedirs(dirname)

            if os.name == 'posix':
                handler = WatchedFileHandler(filelog_path)

            else:
                handler = logging.FileHandler(filelog_path)

        except Exception:
            sys.stderr.write("ERROR: couldn't create the logfile directory. Logging to the standard output.\n")

    if isinstance(handler, logging.StreamHandler):
        formatter = ColoredFormatter(format, datefmt='(%z) %y/%m/%d %H:%M:%S')
    else:
        formatter = logging.Formatter(format)

    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)

    logging.getLogger(appname).setLevel(default_level)

    logging.getLogger(__name__).debug('logger initialized with default: "%s"', default_level)

    if post_emit:
        original_emit = handler.emit

        def new_emit(record):
            try:
                original_emit(record)
            except:
                raise
            else:
                LoggingHookManager.dispatch(record)

        handler.emit = new_emit


if __name__ == "__main__":
    setup_logger("iantirta", default_level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    from rich import inspect as i

    i(logging.Handler.format)

    def custom_hook(record):
        root_handler = logging.getLogger().handlers[0]
        msg = root_handler.formatter.format(record)
        
        print("--- HOOK INTERCEPTED ---")
        print(msg)
        print("========================")
        

    add_hook(custom_hook)
    logger.debug("debug")
    logger.info("info")
    logger.warning("warning")
    logger.critical("critical")
    logger.error("error")
    logger.fatal("fatal")
