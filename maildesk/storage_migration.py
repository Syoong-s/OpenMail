"""Offline local copy/verify/switch migration, retaining all original user files.

Call execute_migration only after readers, workers and executors are drained,
while the caller still owns the original mailbox instance lock. A successful
return requires restarting with the original command-line arguments.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from .storage_paths import StorageLocations, commit_locations, safe_path, sync_directory, validate_profile_destinations

_CHUNK = 1024 * 1024


# ==========================================
# Function: Identify cancellation before the paths-only locator switches.
# Method: Keep interruption distinct from copy failures while preserving the old route.
# ==========================================
class MigrationCancelled(InterruptedError):
    """Cancellation before the locator switch leaves the original profile active."""


# ==========================================
# Function: Describe an immutable offline migration of selected owned roots.
# Method: Freeze desired paths and changes while retaining the original locator record.
# ==========================================
@dataclass(frozen=True)
class MigrationPlan:
    locations: StorageLocations
    data: Path
    config: Path
    cache: Path
    downloads: Path
    changed: tuple

    # ==========================================
    # Function: Return the final path mapping expected by the locator commit.
    # Method: Create a fresh dictionary so callers cannot mutate the frozen plan.
    # ==========================================
    def paths(self):
        return {name: getattr(self, name) for name in ('data', 'config', 'cache', 'downloads')}


# ==========================================
# Function: Compare physical roots with platform-appropriate case normalization.
# Method: Normalize already-validated absolute paths without resolving away links.
# ==========================================
def _identity(path):
    return os.path.normcase(os.path.normpath(str(path)))


# ==========================================
# Function: Detect equality or ancestry between two local storage paths.
# Method: Compare normalized paths using commonpath, allowing different Windows drives.
# ==========================================
def _overlap(left, right):
    left, right = _identity(left), _identity(right)
    try:
        return os.path.commonpath((left, right)) in (left, right)
    except ValueError:
        return False


# ==========================================
# Function: Derive the encrypted vault namespace without reading any credential values.
# Method: Match CredentialVault's resolved-config-path SHA256 folder naming exactly.
# ==========================================
def _vault(config):
    path = Path(config).resolve()
    return path.parent / ('credentials-' + hashlib.sha256(str(path).encode()).hexdigest()[:12])


# ==========================================
# Function: Validate a changed destination before staging or publishing into it.
# Method: Require a non-root empty directory or absent path with safe ancestors.
# ==========================================
def _destination(path):
    path = safe_path(path)
    if path == path.parent:
        raise ValueError('不能使用文件系统根目录作为存储目录')
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('新存储目录必须为空；已有文件不会被覆盖：' + str(path))
    return path


# ==========================================
# Function: Produce a validated immutable migration without touching user data.
# Method: Reject overlapping sources/targets, linked ancestors and nonempty destinations.
# ==========================================
def prepare_migration(locations, desired):
    if not isinstance(desired, dict) or set(desired) - {'data', 'cache', 'downloads'}:
        raise ValueError('仅支持数据、缓存和托管下载目录')
    paths = {name: safe_path(desired.get(name, getattr(locations, name)))
             for name in ('data', 'cache', 'downloads')}
    changed = tuple(name for name in paths if _identity(paths[name]) != _identity(getattr(locations, name)))
    if not changed:
        return None
    safe_path(locations.config)
    for name in paths:
        safe_path(getattr(locations, name))
    # Each final root has one clear owner. Config is deliberately inside data
    # after a data move; its old parent is included only as an exact source.
    for index, left in enumerate(paths):
        for right in list(paths)[index + 1:]:
            if _overlap(paths[left], paths[right]):
                raise ValueError('数据、缓存和下载目录不能互相包含')
    sources = [locations.data, locations.cache, locations.downloads, locations.config, _vault(locations.config)]
    for name in changed:
        target = _destination(paths[name])
        for source in sources:
            if _overlap(target, source):
                raise ValueError('新目录不能与任何原存储路径重叠：' + str(target))
    config = paths['data'] / 'settings' / locations.config.name if 'data' in changed else locations.config
    validate_profile_destinations(locations,{**paths,'config':config})
    return MigrationPlan(locations, paths['data'], config, paths['cache'], paths['downloads'], changed)


# ==========================================
# Function: Observe cancellation at bounded copy, verification and publication steps.
# Method: Raise a dedicated exception while the old locator remains authoritative.
# ==========================================
def _cancel(event):
    if event is not None and event.is_set():
        raise MigrationCancelled('已取消迁移，原存储位置继续可用')


# ==========================================
# Function: Reject unexpected file types and links in an owned source tree.
# Method: Use lstat so directories, symlinks and reparse points cannot masquerade as files.
# ==========================================
def _source_info(path):
    safe_path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise ValueError('存储目录中存在不支持的文件类型：' + str(path))
    return info


# ==========================================
# Function: Enumerate one owned tree without following linked files or directories.
# Method: Record regular file paths and preserve empty directories in deterministic order.
# ==========================================
def _inventory(source, relative=Path(), excluded=None, event=None):
    _cancel(event)
    safe_path(source)
    if not source.exists():
        return [], []
    info = _source_info(source)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('原存储路径不是目录：' + str(source))
    files, directories = [], [relative]
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        _cancel(event)
        if excluded is not None and excluded(entry):
            continue
        info = _source_info(entry)
        destination = relative / entry.name
        if stat.S_ISDIR(info.st_mode):
            nested_files, nested_directories = _inventory(entry, destination, excluded, event)
            files.extend(nested_files)
            directories.extend(nested_directories)
        else:
            files.append((entry, destination, info.st_size))
    return files, directories


# ==========================================
# Function: Check source identity before and after each streaming copy.
# Method: Compare inode, device, byte size and nanosecond modification timestamp.
# ==========================================
def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


# ==========================================
# Function: Hash a copied file in bounded chunks with cancellation and progress.
# Method: Open without following links and stream SHA256 over the actual descriptor.
# ==========================================
def _hash_file(path, event, emit):
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('校验对象不是普通文件：' + str(path))
        while True:
            _cancel(event)
            block = stream.read(_CHUNK)
            if not block:
                break
            digest.update(block)
            emit('verify', path, 0)
    return digest.digest()


# ==========================================
# Function: Copy one file privately and prove that its destination bytes match.
# Method: Stream SHA256, fsync, rehash the destination and detect source changes.
# ==========================================
def _copy_file(source, target, event, emit):
    _cancel(event)
    before = _source_info(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists():
        # A legacy cache can contain an identical owned file. Conflicting
        # versions are retained at source and require explicit user resolution.
        if _hash_file(source, event, emit) != _hash_file(target, event, emit):
            raise ValueError('缓存来源包含同名且不同的文件：' + str(target))
        emit('copy', source, before.st_size)
        return
    descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    digest = hashlib.sha256()
    with os.fdopen(descriptor, 'rb') as reader, target.open('xb') as writer:
        if _signature(os.fstat(reader.fileno())) != _signature(before):
            raise RuntimeError('复制期间原文件发生变化：' + str(source))
        while True:
            _cancel(event)
            block = reader.read(_CHUNK)
            if not block:
                break
            writer.write(block)
            digest.update(block)
            emit('copy', source, len(block))
        writer.flush()
        os.fsync(writer.fileno())
        after = os.fstat(reader.fileno())
    if _signature(before) != _signature(after) or _signature(before) != _signature(source.lstat()):
        raise RuntimeError('复制期间原文件发生变化：' + str(source))
    if digest.digest() != _hash_file(target, event, emit):
        raise RuntimeError('文件校验失败：' + str(target))
    os.chmod(target, stat.S_IMODE(before.st_mode) & 0o777)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))


# ==========================================
# Function: Create a consistent verified SQLite snapshot, including committed WAL data.
# Method: Use SQLite's online backup API, cancellable page batches and quick_check.
# ==========================================
def _backup_database(source, target, event, emit):
    _source_info(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _cancel(event)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as reader:
        with closing(sqlite3.connect(target, timeout=5)) as writer:
            # ==========================================
            # Function: Keep SQLite backup responsive while reporting page progress.
            # Method: Check cancellation on each bounded page batch without logging content.
            # ==========================================
            def progress(status, remaining, total):
                _cancel(event)
                emit('database', source, 0)
            reader.backup(writer, pages=128, progress=progress, sleep=0.05)
            if writer.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise RuntimeError('邮件数据库校验失败')
            writer.execute('PRAGMA journal_mode=DELETE')
    descriptor = os.open(target, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # Independent post-close streaming hashes verify the published snapshot.
    expected = _hash_file(target, event, emit)
    if expected != _hash_file(target, event, emit):
        raise RuntimeError('邮件数据库文件校验失败')
    os.chmod(target, stat.S_IMODE(source.stat().st_mode) & 0o777)
    emit('database', source, source.stat().st_size)


# ==========================================
# Function: Build only this profile's durable/cache/download copy manifests.
# Method: Exclude derived caches and stale settings, then inject exact config and vault paths.
# ==========================================
def _manifests(plan, event=None):
    locations = plan.locations
    manifests = {}
    if 'data' in plan.changed:
        old_config = locations.config
        old_vault = _vault(old_config)
        # ==========================================
        # Function: Omit transient locks, SQLite sidecars and legacy derived caches.
        # Method: Exclude only application-owned top-level caches/settings and vault namespaces.
        # ==========================================
        def excluded(path):
            relative = path.relative_to(locations.data)
            if relative.parts[0] in ('webview2', 'attachments', 'settings'):
                return True
            if len(relative.parts) == 1 and path.name in ('instance.lock', 'mail.sqlite3-wal', 'mail.sqlite3-shm'):
                return True
            if path == old_config or path == old_vault:
                return True
            if path.parent == old_config.parent and path.name.startswith('credentials-'):
                return True
            return False
        files, directories = _inventory(locations.data, excluded=excluded, event=event)
        if not locations.demo:
            if old_config.exists():
                info = _source_info(old_config)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('账户配置不是普通文件')
                files.append((old_config, Path('settings') / plan.config.name, info.st_size))
            vault_files, vault_directories = _inventory(old_vault, Path('settings') / _vault(plan.config).name, event=event)
            files.extend(vault_files)
            directories.extend(vault_directories)
        manifests['data'] = files, directories
    if 'cache' in plan.changed:
        # ==========================================
        # Function: Keep the live cache copy scoped to this profile's owned files.
        # Method: Reserve its top-level profiles directory for demo and explicit caches.
        # ==========================================
        def cache_excluded(path):
            return locations.scope=='live' and path.relative_to(locations.cache).parts[0]=='profiles'
        files, directories = _inventory(locations.cache, excluded=cache_excluded, event=event)
        for name in ('webview2', 'attachments'):
            legacy = locations.data / name
            if not _overlap(legacy, locations.cache):
                extra_files, extra_directories = _inventory(legacy, Path(name), event=event)
                files.extend(extra_files)
                directories.extend(extra_directories)
        manifests['cache'] = files, directories
    if 'downloads' in plan.changed:
        manifests['downloads'] = _inventory(locations.downloads, event=event)
    return manifests


# ==========================================
# Function: Execute the offline copy/verify/publish/switch transaction.
# Method: Stage private siblings, verify all files, then serialize the final locator commit.
# ==========================================
def execute_migration(plan, cancel_event=None, progress_callback=None):
    if not isinstance(plan, MigrationPlan):
        raise TypeError('需要有效的迁移计划')
    # Revalidate after readers and workers have drained, not just when Apply was clicked.
    confirmed = prepare_migration(plan.locations, {name: getattr(plan, name) for name in ('data', 'cache', 'downloads')})
    if confirmed != plan:
        raise RuntimeError('迁移计划已失效')
    _cancel(cancel_event)
    if progress_callback is not None:
        progress_callback({'phase': 'scan', 'path': str(plan.locations.data), 'completed': 0, 'total': 0})
    manifests = _manifests(plan, cancel_event)
    total = sum(size for files, _ in manifests.values() for _, _, size in files)
    completed = 0
    stages = {}
    published = []

    # ==========================================
    # Function: Report bounded progress without exposing message or credential contents.
    # Method: Send paths and aggregate copied bytes to the optional observer.
    # ==========================================
    def emit(phase, path, amount):
        nonlocal completed
        completed += amount
        if progress_callback is not None:
            progress_callback({'phase': phase, 'path': str(path), 'completed': completed, 'total': total})

    try:
        for name in plan.changed:
            _cancel(cancel_event)
            target = _destination(getattr(plan, name))
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            safe_path(target.parent)
            stage = Path(tempfile.mkdtemp(prefix='.' + target.name + '.maildesk-migration-', dir=target.parent))
            stages[name] = stage
            files, directories = manifests[name]
            for directory in directories:
                _cancel(cancel_event)
                (stage / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
            for source, relative, _ in files:
                if name == 'data' and source == plan.locations.data / 'mail.sqlite3':
                    _backup_database(source, stage / relative, cancel_event, emit)
                else:
                    _copy_file(source, stage / relative, cancel_event, emit)
            # Sync every created directory so verified files survive a power loss
            # before the locator's atomic replacement makes the target active.
            for directory, _, _ in os.walk(stage, topdown=False):
                sync_directory(Path(directory))
            emit('verified', target, 0)

        # ==========================================
        # Function: Publish complete verified roots immediately before the pointer switch.
        # Method: Revalidate emptiness and ancestors under the cross-process locator lock.
        # ==========================================
        def publish():
            _cancel(cancel_event)
            for name in plan.changed:
                _cancel(cancel_event)
                target = _destination(getattr(plan, name))
                if target.exists():
                    target.rmdir()  # Only an empty explicitly selected directory.
                os.rename(stages[name], target)
                published.append(target)
                sync_directory(target.parent)
                emit('publish', target, 0)
            _cancel(cancel_event)
        result = commit_locations(plan.locations, plan.paths(), publish, cancel_event)
        # The pointer has committed. Late cancellation cannot undo this success.
        # Observer errors after commit must likewise never be reported as rollback.
        try:
            emit('complete', result.data, 0)
        except Exception:
            pass
        return result
    except InterruptedError as error:
        suffix = ' 已验证的目标副本已保留；重试请选择空目录。' if published else ''
        raise MigrationCancelled('已取消迁移，原存储位置继续可用。' + suffix) from error
    except Exception as error:
        if published:
            raise RuntimeError('迁移未完成，原存储位置继续可用。已验证的目标副本已保留；重试请选择空目录。 ' + str(error)) from error
        raise
    finally:
        for stage in stages.values():
            if stage.exists():
                # Never mask the original cancellation/failure with a cleanup
                # error. A private orphan has no locator and is never adopted.
                shutil.rmtree(stage, ignore_errors=True)
