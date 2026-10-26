"""Profile-scoped local paths and an atomic, paths-only relocation locator.

The locator never contains accounts or credentials. Its lock is distinct from the
mailbox instance lock; callers retain the latter while committing migrations.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from types import MappingProxyType

from .platform_native import WINDOWS, lock_instance, profile_homes

_active_cache = None
_KEYS = frozenset(('generation', 'data', 'config', 'cache', 'downloads'))


# ==========================================
# Function: Reject linked paths without resolving away evidence of a link.
# Method: Inspect each existing ancestor, including Windows reparse attributes.
# ==========================================
def safe_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('存储路径必须是绝对路径，且不能包含 ..')
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('存储路径及其父目录不能是链接：' + str(item))
    return path


# ==========================================
# Function: Reject duplicate locator fields rather than silently selecting one.
# Method: Decode JSON objects through a duplicate-checking pairs hook.
# ==========================================
def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('存储位置索引包含重复字段')
        result[key] = value
    return result


# ==========================================
# Function: Read only a strict, bounded paths-only locator.
# Method: Reject malformed versions, scopes, records, links and invalid paths.
# ==========================================
def read_locator(path):
    path = safe_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return {'version': 1, 'profiles': {}}
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('存储位置索引必须是普通文件')
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('存储位置索引过大')
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('存储位置索引损坏，请保留该文件并修复后重试') from error
    if (not isinstance(document, dict) or set(document) != {'version', 'profiles'}
            or type(document['version']) is not int or document['version'] != 1
            or not isinstance(document['profiles'], dict)):
        raise ValueError('存储位置索引格式无效')
    for scope, record in document['profiles'].items():
        if not isinstance(scope, str) or not re.fullmatch(r'(live|demo|explicit-[0-9a-f]{24})', scope):
            raise ValueError('存储位置索引的配置范围无效')
        if (not isinstance(record, dict) or set(record) != _KEYS
                or type(record['generation']) is not int or record['generation'] < 1):
            raise ValueError('存储位置索引的记录无效')
        for name in ('data', 'config', 'cache', 'downloads'):
            if not isinstance(record[name], str) or not record[name] or '\0' in record[name]:
                raise ValueError('存储位置索引的路径无效')
            safe_path(record[name])
    return document


# ==========================================
# Function: Resolve one launch scope while preserving the original launch arguments.
# Method: Use existing defaults until a paths-only locator overrides this scope.
# ==========================================
@dataclass(frozen=True, init=False)
class StorageLocations:
    demo: bool
    original_config: object
    original_data: object
    scope: str
    locator: Path
    config: Path
    data: Path
    cache: Path
    downloads: Path
    record: object

    # ==========================================
    # Function: Resolve immutable paths for live, demo or explicitly selected profiles.
    # Method: Hash original explicit arguments and consult one fixed OS config locator.
    # ==========================================
    def __init__(self, demo=False, config=None, data=None):
        config_home, data_home = profile_homes()
        config_home = config_home.expanduser().absolute()
        data_home = data_home.expanduser().absolute()
        explicit = config is not None or data is not None
        config = Path(os.path.abspath(Path(config).expanduser())) if config is not None else None
        data = Path(os.path.abspath(Path(data).expanduser())) if data is not None else None
        arguments = {'demo': bool(demo), 'config': os.path.normcase(str(config)) if config is not None else None,
                     'data': os.path.normcase(str(data)) if data is not None else None}
        scope = ('explicit-' + hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:24]
                 if explicit else ('demo' if demo else 'live'))
        locator = config_home / 'telemail/storage-locations.json'
        defaults = {'data': Path(os.path.abspath(Path(data).expanduser())) if data else data_home / 'telemail' / ('demo' if demo else 'live'),
                    'config': Path(os.path.abspath(Path(config).expanduser())) if config else config_home / 'telemail/accounts.json'}
        cache_base = data_home / 'TeleMail/cache' if WINDOWS else Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')).expanduser().absolute() / 'telemail'
        defaults['cache'] = cache_base if scope == 'live' else cache_base / 'profiles' / scope
        defaults['downloads'] = Path.home() / 'Downloads' / ('TeleMail' if scope == 'live' else 'TeleMail-' + scope)
        record = read_locator(locator)['profiles'].get(scope)
        if record and not Path(record['data']).is_dir():
            raise ValueError('已配置的数据目录不可用，请恢复该目录或修复存储位置索引；不会创建空邮箱：' + record['data'])
        for key, value in {'demo': bool(demo), 'original_config': config, 'original_data': data,
                           'scope': scope, 'locator': locator, 'record': MappingProxyType(dict(record or {}))}.items():
            object.__setattr__(self, key, value)
        for key, default in defaults.items():
            object.__setattr__(self, key, Path(record[key]) if record else default)


# ==========================================
# Function: Route process-local derived files through the selected profile's cache.
# Method: Retain the path in memory without changing global environment settings.
# ==========================================
def configure_cache(locations):
    global _active_cache
    _active_cache = Path(locations.cache)
    return _active_cache


# ==========================================
# Function: Return the configured derived-file root for this process.
# Method: Resolve live defaults lazily when desktop startup has not selected a profile.
# ==========================================
def active_cache():
    return _active_cache if _active_cache is not None else StorageLocations().cache


# ==========================================
# Function: Reserve other configured and built-in profile roots before a directory move.
# Method: Compare changed destinations with recorded paths and live/demo defaults, allowing owned profiles cache nesting.
# ==========================================
def validate_profile_destinations(locations,paths,document=None):
    document=read_locator(locations.locator) if document is None else document
    config_home,data_home=profile_homes()
    config_home=config_home.expanduser().absolute();data_home=data_home.expanduser().absolute()
    cache=data_home/'TeleMail/cache' if WINDOWS else Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache')).expanduser().absolute()/'telemail'
    defaults={scope:{'data':data_home/'telemail'/scope,'config':config_home/'telemail/accounts.json',
                     'cache':cache if scope=='live' else cache/'profiles/demo',
                     'downloads':Path.home()/'Downloads'/('TeleMail' if scope=='live' else 'TeleMail-demo')} for scope in ('live','demo')}
    others=[(scope,record,False) for scope,record in document['profiles'].items() if scope!=locations.scope]
    others.extend((scope,record,True) for scope,record in defaults.items() if scope!=locations.scope)
    for name in ('data','cache','downloads'):
        target=os.path.normcase(os.path.normpath(str(paths[name])))
        if target==os.path.normcase(os.path.normpath(str(getattr(locations,name)))):continue
        for scope,other,is_default in others:
            for other_name,root in other.items():
                if other_name not in ('data','cache','downloads','config'):continue
                source=os.path.normcase(os.path.normpath(str(root)))
                if other_name=='config' and source==os.path.normcase(os.path.normpath(str(locations.config))):continue
                try:overlap=os.path.commonpath((target,source)) in (target,source)
                except ValueError:overlap=False
                if not overlap:continue
                # The default live cache deliberately reserves profiles/ for separate scopes.
                profiles=os.path.normcase(os.path.normpath(str(cache/'profiles')))
                if scope=='live' and other_name=='cache' and source==os.path.normcase(os.path.normpath(str(cache))):
                    try:
                        if target!=profiles and os.path.commonpath((target,profiles))==profiles:continue
                    except ValueError:pass
                raise ValueError('新目录与另一个配置的存储位置重叠：'+str(paths[name]))


# ==========================================
# Function: Flush a directory entry after replacing the locator on POSIX.
# Method: Fsync its directory descriptor where the operating system supports it.
# ==========================================
def sync_directory(path):
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# ==========================================
# Function: Write a complete private JSON document without exposing partial content.
# Method: Flush a sibling temporary file before atomic replacement and directory sync.
# ==========================================
def _atomic_json(path, document, final=False):
    descriptor, temporary = tempfile.mkstemp(prefix='.storage-locator-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            sync_directory(path.parent)
        except OSError:
            # Once the final pointer is replaced, reporting rollback would be
            # incorrect. Atomic replacement already made the new profile active.
            if not final:
                raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# ==========================================
# Function: Serialize locator commits from separate desktop processes.
# Method: Hold an OS advisory lock on a separate persistent file with a bounded wait.
# ==========================================
@contextmanager
def locator_lock(path, cancel_event=None):
    safe_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lockpath = safe_path(path.with_suffix('.lock'))
    descriptor = os.open(lockpath, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'r+b') as stream:
        deadline = time.monotonic() + 30
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError('已取消存储位置切换')
            try:
                lock_instance(stream)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('另一个窗口正在更新存储位置，请稍后重试')
                time.sleep(0.05)
        yield


# ==========================================
# Function: Publish a verified migration and switch its pointer as the final mutation.
# Method: Recheck the current scope under lock, preserve other scopes and backup old JSON.
# ==========================================
def commit_locations(locations, paths, publish, cancel_event=None, backup=True):
    with locator_lock(locations.locator, cancel_event):
        document = read_locator(locations.locator)
        current = document['profiles'].get(locations.scope, {})
        if current != dict(locations.record):
            raise RuntimeError('此配置的存储位置已被另一个窗口修改，请重新打开设置')
        record = {'generation': current.get('generation', 0) + 1}
        record.update({name: str(safe_path(paths[name])) for name in ('data', 'config', 'cache', 'downloads')})
        validate_profile_destinations(locations,record,document)
        if backup and locations.locator.exists():
            backup_path = safe_path(locations.locator.with_suffix('.json.bak'))
            _atomic_json(backup_path, document)
        # Prepare the returned value before the irreversible pointer replace,
        # avoiding a post-commit disk read that could fail or observe a later edit.
        result = object.__new__(StorageLocations)
        for name in StorageLocations.__dataclass_fields__:
            object.__setattr__(result, name, getattr(locations, name))
        for name in ('data', 'config', 'cache', 'downloads'):
            object.__setattr__(result, name, Path(record[name]))
        object.__setattr__(result, 'record', MappingProxyType(record))
        publish()
        document['profiles'][locations.scope] = record
        _atomic_json(locations.locator, document, final=True)
    return result
