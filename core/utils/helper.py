from __future__ import annotations
import importlib
import json
import luadata
import os
import psycopg2
import re
import string
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta
from typing import Optional, Union, TYPE_CHECKING, Tuple, Generator

if TYPE_CHECKING:
    from core import Server


def is_in_timeframe(time: datetime, timeframe: str) -> bool:
    def parse_time(time_str: str) -> datetime:
        fmt, time_str = ('%H:%M', time_str.replace('24:', '00:')) \
            if time_str.find(':') > -1 else ('%H', time_str.replace('24', '00'))
        return datetime.strptime(time_str, fmt)

    pos = timeframe.find('-')
    if pos != -1:
        start_time = parse_time(timeframe[:pos])
        end_time = parse_time(timeframe[pos+1:])
        if end_time <= start_time:
            end_time += timedelta(days=1)
    else:
        start_time = end_time = parse_time(timeframe)
    check_time = time.replace(year=start_time.year, month=start_time.month, day=start_time.day, second=0, microsecond=0)
    return start_time <= check_time <= end_time


def is_match_daystate(time: datetime, daystate: str) -> bool:
    state = daystate[time.weekday()]
    return state.upper() == 'Y'


def str_to_class(name):
    try:
        module_name, class_name = name.rsplit('.', 1)
        return getattr(importlib.import_module(module_name), class_name)
    except AttributeError:
        return None


def format_string(string_: str, default_: Optional[str] = None, **kwargs) -> str:
    class NoneFormatter(string.Formatter):
        def format_field(self, value, spec):
            if value is None:
                spec = ''
                if default_:
                    value = default_
                else:
                    value = ""
            elif isinstance(value, list):
                value = '\n'.join(value)
            elif isinstance(value, dict):
                value = json.dumps(value)
            return super().format_field(value, spec)
    try:
        string_ = NoneFormatter().format(string_, **kwargs)
    except KeyError:
        string_ = ""
    return string_


def sanitize_string(s: str) -> str:
    # Replace single and double quotes, semicolons and backslashes
    s = re.sub(r"[\"';\\]", "", s)

    # Replace comment sequences
    s = re.sub(r"--|/\*|\*/", "", s)

    return s


def convert_time(seconds: int):
    retval = ""
    days = int(seconds / 86400)
    if days != 0:
        retval += f"{days}d"
    seconds = seconds - days * 86400
    hours = int(seconds / 3600)
    if hours != 0:
        if len(retval):
            retval += ":"
        retval += f"{hours:02d}h"
    seconds = seconds - hours * 3600
    minutes = int(seconds / 60)
    if len(retval):
        retval += ":"
    retval += f"{minutes:02d}m"
    return retval


def format_time(seconds: int):
    retval = ""
    days = int(seconds / 86400)
    if days != 0:
        retval += f"{days} day"
        if days > 1:
            retval += "s"
        seconds -= days * 86400
    hours = int(seconds / 3600)
    if hours != 0:
        if len(retval):
            retval += " "
        retval += f"{hours} hour"
        if hours > 1:
            retval += "s"
        seconds -= hours * 3600
    minutes = int(seconds / 60)
    if minutes != 0:
        if len(retval):
            retval += " "
        retval += f"{minutes} minute"
        if minutes > 1:
            retval += "s"
        seconds -= minutes * 60
    if seconds != 0:
        if len(retval):
            retval += " "
        retval += f"{seconds} second"
        if seconds > 1:
            retval += "s"
    return retval


def format_period(period: str) -> str:
    if period == 'day':
        return 'Daily'
    else:
        return period.capitalize() + 'ly'


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


def alternate_parse_settings(path: str):
    def parse(value: str) -> Union[int, str, bool]:
        if value.startswith('"'):
            return value[1:-1]
        elif value == 'true':
            return True
        elif value == 'false':
            return False
        else:
            return int(value)

    exp1 = re.compile(r'cfg\["(?P<key>.*)"\] = (?P<value>.*)')
    exp2 = re.compile(r'cfg\["(?P<key1>.*)"\]\[(?P<key2>.*)\] = (?P<value>.*)')

    settings = dict()
    with open(path, encoding='utf-8') as infile:
        for idx, line in enumerate(infile.readlines()):
            if idx == 0:
                continue
            match = exp2.search(line)
            if match:
                if match.group('key2').isnumeric():
                    settings[match.group('key1')].insert(int(match.group('key2')) - 1, parse(match.group('value')))
                else:
                    settings[match.group('key1')][parse(match.group('key2'))] = parse(match.group('value'))
            else:
                match = exp1.search(line)
                if match:
                    if match.group('value') == "{}":
                        if match.group('key') == 'missionList':
                            settings['missionList'] = list()
                        else:
                            settings[match.group('key')] = dict()
                    else:
                        settings[match.group('key')] = parse(match.group('value'))
    return settings


def get_all_servers(self) -> list[str]:
    conn = self.pool.getconn()
    try:
        with closing(conn.cursor()) as cursor:
            cursor.execute(f"SELECT server_name FROM servers WHERE last_seen > (DATE(NOW()) - interval '1 week')")
            return [row[0] for row in cursor.fetchall()]
    except (Exception, psycopg2.DatabaseError) as error:
        self.log.exception(error)
    finally:
        self.pool.putconn(conn)


def get_all_players(self, **kwargs) -> list[Tuple[str, str]]:
    name = kwargs.get('name')
    ucid = kwargs.get('ucid')
    sql = "SELECT ucid, name FROM players"
    if name:
        sql += ' WHERE name ILIKE %s'
        name = f'%{name}%'
    elif ucid:
        sql += ' WHERE ucid ILIKE %s'
        ucid = f'%{ucid}%'
    sql += ' ORDER BY 2 LIMIT 25'

    conn = self.pool.getconn()
    try:
        with closing(conn.cursor()) as cursor:
            cursor.execute(sql, (name or ucid, ))
            return [(row[0], row[1]) for row in cursor.fetchall()]
    except (Exception, psycopg2.DatabaseError) as error:
        self.log.exception(error)
    finally:
        self.pool.putconn(conn)


def is_banned(self, ucid: str):
    conn = self.pool.getconn()
    try:
        with closing(conn.cursor()) as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM bans WHERE ucid = %s AND banned_until >= NOW()", (ucid,))
            return cursor.fetchone()[0] > 0
    except (Exception, psycopg2.DatabaseError) as error:
        self.log.exception(error)
    finally:
        self.pool.putconn(conn)


def is_ucid(ucid: str) -> bool:
    return len(ucid) == 32 and ucid.isalnum() and ucid == ucid.lower()


class SettingsDict(dict):
    def __init__(self, server: Server, path: str, root: Optional[str] = None):
        super().__init__()
        self.path = path
        self.root = root
        self.mtime = 0
        self.server = server
        self.bot = server.bot
        self.log = server.log
        self.read_file()

    def read_file(self):
        self.mtime = os.path.getmtime(self.path)
        if self.path.lower().endswith('.lua'):
            try:
                data = luadata.read(self.path, encoding='utf-8')
            except Exception as ex:
                self.log.debug(f"Exception while reading {self.path}:\n{ex}")
                data = alternate_parse_settings(self.path)
                if not data:
                    self.log.error("- Error while parsing {}!".format(os.path.basename(self.path)))
                    raise ex
        elif self.path.lower().endswith('.json'):
            with open(self.path, encoding='utf-8') as file:
                data = json.load(file)
        if data:
            self.clear()
            self.update(data)

    def write_file(self):
        if self.path.lower().endswith('.lua'):
            with open(self.path, 'wb') as outfile:
                self.mtime = os.path.getmtime(self.path)
                outfile.write((f"{self.root} = " + luadata.serialize(self, indent='\t', indent_level=0)).encode('utf-8'))
        elif self.path.lower().endswith('.json'):
            with open(self.path, "w", encoding='utf-8') as outfile:
                json.dump(self, outfile)

    def __setitem__(self, key, value):
        if self.mtime < os.path.getmtime(self.path):
            self.log.debug(f'{self.path} changed, re-reading from disk.')
            self.read_file()
        super().__setitem__(key, value)
        if len(self):
            self.write_file()
        else:
            self.log.error("- Writing of {} aborted due to empty set.".format(os.path.basename(self.path)))

    def __getitem__(self, item):
        if self.mtime < os.path.getmtime(self.path):
            self.log.debug(f'{self.path} changed, re-reading from disk.')
            self.read_file()
        return super().__getitem__(item)


def evaluate(value: Union[str, int, bool], **kwargs) -> Union[str, int, bool]:
    if isinstance(value, int) or isinstance(value, bool) or not value.startswith('$'):
        return value
    return eval(format_string(value[1:], **kwargs))


# Helper function to find a specific node inside a dictionary with a format like
# /node1/node2/*/node4/$... python evaluation code .../*
# * is a wildcard to describe any item in a specific list
# (...) is python code that will be evaluated to find a specific item inside a list
def for_each(data: dict, search: list[str], depth: Optional[int] = 0, *,
             debug: Optional[bool] = False) -> Generator[dict]:
    if len(search) == depth:
        if debug:
            print("  " * depth + ("|_ RESULT found => Processing ..." if data else "|_ NO result found, skipping."))
        yield data
    else:
        _next = search[depth]
        if _next == '*':
            if debug:
                print("  " * depth + f"|_ Iterating over {len(data)} {search[depth-1]} elements")
            for value in data:
                yield from for_each(value, search, depth+1, debug=debug)
        elif _next.startswith('$'):
            if isinstance(data, list):
                if debug:
                    print("  " * depth + f"|_ Searching pattern {_next} on {len(data)} {search[depth-1]} elements")
                for idx, value in enumerate(data):
                    if evaluate(_next, **value):
                        if debug:
                            print("  " * depth + f"  - Element {idx+1} matches.")
                        yield from for_each(value, search, depth+1, debug=debug)
            else:
                if debug:
                    print("  " * depth + f"|_ Evaluating {_next} ...")
                if evaluate(_next, **data):
                    if debug:
                        print("  " * depth + "  - Element matches.")
                    yield from for_each(data, search, depth+1, debug=debug)
        elif _next in data:
            if debug:
                print("  " * depth + f"|_ {_next} found.")
            yield from for_each(data.get(_next), search, depth+1, debug=debug)
