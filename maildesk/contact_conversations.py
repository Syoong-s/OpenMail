"""Worker-side compact contact projection with bounded collision-only MIME checks.

Construct freely, then call all database methods through LocalLoader workers.
Each refresh indexes at most 256 missing metadata rows and reports incomplete
coverage. Existing immutable parsed messages are indexed once per own-set scope.
"""
import hashlib
import json
import shlex
import threading
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from .participant_identity import conversation_envelope, own_identities, parse_participants

# Source-local routes remain untouched; only direct conversation presentation is remapped.
PERSON_JOIN=""" JOIN json_each(c.envelope,'$.contacts') cm
    LEFT JOIN address_mailboxes am ON am.address=json_extract(cm.value,'$.address') AND am.suppressed=0
    LEFT JOIN address_people ap ON ap.id=am.person
    LEFT JOIN contact_preferences cp ON cp.person=ap.id """
PERSON_KEY="coalesce(nullif(ap.conversation,''),json_extract(cm.value,'$.key'))"

INDEX_VERSION = '5'
DEFAULT_VERIFICATION_BYTES = 32 * 1024 * 1024


# ==========================================
# Function: Hash deterministic evidence without retaining message body strings.
# Method: Serialize canonical JSON and SHA-256 the resulting UTF-8 bytes.
# ==========================================
def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


# ==========================================
# Function: Require payload evidence whenever metadata may omit MIME content.
# Method: Treat multipart, non-text and unknown root types conservatively without raw reads.
# ==========================================
def _needs_payload_verification(parsed):
    headers = parsed.get('headers') or {}
    content_type = str(headers.get('content-type', '')).split(';', 1)[0].strip().lower()
    return bool(parsed.get('attachments')) or content_type not in ('text/plain', 'text/html')


# ==========================================
# Function: Compare decoded MIME contents despite rewritten transport headers.
# Method: Hash ordered decoded parts, excluding multipart boundaries and top headers.
# ==========================================
def _payload_fingerprint(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    evidence = []
    for part in message.walk():
        metadata = [part.get_content_type(), part.get_content_disposition(),
                    part.get_filename(), str(part.get('Content-ID', ''))]
        if part.get_content_maintype() == 'message' and isinstance(part.get_payload(), list):
            for child in part.get_payload():
                # Encapsulated-message headers are payload content, not outer transport.
                metadata.append(sorted((key.lower(), str(value)) for key, value in child.items()
                                       if key.lower() not in ('received', 'return-path', 'content-type',
                                                              'content-transfer-encoding', 'authentication-results', 'dkim-signature')
                                       and not key.lower().startswith('arc-')))
        if not part.is_multipart():
            payload = part.get_payload(decode=True)
            if payload is None:
                payload = str(part.get_payload() or '').encode('utf-8')
            if part.get_content_maintype() == 'text' and not part.get_filename() and part.get_content_disposition() != 'attachment':
                payload = payload.replace(b'\r\n', b'\n')
            metadata.append(hashlib.sha256(payload).hexdigest())
        if part.defects:
            raise ValueError('Malformed MIME payload cannot establish duplicate equivalence')
        evidence.append(metadata)
    return _digest(evidence)


# ==========================================
# Function: Provide bounded indexing and live contact conversations over Store.
# Method: Persist compact immutable envelopes and join current flags on every read.
# ==========================================
class ContactConversations:
    # ==========================================
    # Function: Define a projection for all accounts without touching SQLite.
    # Method: Snapshot mailbox identities; include demo identity explicitly via extra_own.
    # ==========================================
    def __init__(self, store, accounts, extra_own=()):
        self.store = store
        self.own = own_identities(accounts, extra_own)
        self.scope = _digest([INDEX_VERSION, sorted(self.own)])
        self._index_lock = threading.RLock()
        self._initialized = False
        self._members_complete=False;self._last_status=None

    # ==========================================
    # Function: Add the projection schema inside a background loader operation.
    # Method: Keep migrations additive and separate from constructors or GTK setup.
    # ==========================================
    def initialize(self):
        if self._initialized:return
        with self._index_lock:
            if self._initialized:
                return
            with self.store.db() as db:
                self.initialize_schema(db)
            self._initialized = True

    # ==========================================
    # Function: Install empty contact projections within the Store migration transaction.
    # Method: Share additive DDL with lazy initialization without reading cached messages.
    # ==========================================
    @staticmethod
    def initialize_schema(db):
        db.executescript('''
        CREATE TABLE IF NOT EXISTS contact_envelopes (
            message TEXT NOT NULL, scope TEXT NOT NULL, conversation TEXT NOT NULL,
            dedup TEXT NOT NULL, envelope TEXT NOT NULL, preview TEXT NOT NULL,
            sender TEXT NOT NULL, recipients TEXT NOT NULL, attachments INTEGER NOT NULL,
            PRIMARY KEY(scope,message));
        CREATE INDEX IF NOT EXISTS contact_members ON contact_envelopes(scope,conversation,dedup);
        CREATE TABLE IF NOT EXISTS contact_member_index(
            scope TEXT NOT NULL,message TEXT NOT NULL,address TEXT NOT NULL,conversation TEXT NOT NULL,value TEXT NOT NULL,
            PRIMARY KEY(scope,message,address));
        CREATE INDEX IF NOT EXISTS contact_member_key ON contact_member_index(scope,conversation,message);
        CREATE INDEX IF NOT EXISTS contact_member_address ON contact_member_index(scope,address,message);
        CREATE TABLE IF NOT EXISTS contact_member_scopes(scope TEXT PRIMARY KEY);
        CREATE INDEX IF NOT EXISTS contact_unread_sender ON messages(sender) WHERE seen=0;
        CREATE TRIGGER IF NOT EXISTS contact_member_insert AFTER INSERT ON contact_envelopes BEGIN
            DELETE FROM contact_member_index WHERE scope=new.scope AND message=new.message;
            INSERT INTO contact_member_index SELECT new.scope,new.message,json_extract(value,'$.address'),json_extract(value,'$.key'),value FROM json_each(new.envelope,'$.contacts');
        END;
        CREATE TRIGGER IF NOT EXISTS contact_member_update AFTER UPDATE OF envelope ON contact_envelopes BEGIN
            DELETE FROM contact_member_index WHERE scope=old.scope AND message=old.message;
            INSERT INTO contact_member_index SELECT new.scope,new.message,json_extract(value,'$.address'),json_extract(value,'$.key'),value FROM json_each(new.envelope,'$.contacts');
        END;
        CREATE TRIGGER IF NOT EXISTS contact_member_delete AFTER DELETE ON contact_envelopes BEGIN
            DELETE FROM contact_member_index WHERE scope=old.scope AND message=old.message;
        END;

        CREATE TABLE IF NOT EXISTS contact_attachment_candidates (
            scope TEXT NOT NULL,message TEXT NOT NULL,base TEXT NOT NULL,
            PRIMARY KEY(scope,message));
        CREATE INDEX IF NOT EXISTS contact_attachment_collisions
            ON contact_attachment_candidates(scope,base);
        CREATE TABLE IF NOT EXISTS contact_payload_fingerprints (
            message TEXT PRIMARY KEY,digest TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',raw_bytes INTEGER NOT NULL DEFAULT 0);
                    ''')

    # ==========================================
    # Function: Backfill a bounded batch of cached metadata, including new ingests.
    # Method: Serialize same-instance index writers, allowing concurrent list/read workers.
    # ==========================================
    def backfill(self, limit=256, verification_limit=8, verification_bytes=DEFAULT_VERIFICATION_BYTES):
        if not limit and not verification_limit:
            self.initialize();return self.cached_status()
        with self._index_lock:
            self._last_status=self._backfill(limit, verification_limit, verification_bytes)
            return dict(self._last_status)

    # ==========================================
    # Function: Reuse the last background coverage snapshot without global counts or an index lock.
    # Method: Keep foreground reads observational and let the bounded list/index worker update coverage.
    # ==========================================
    def cached_status(self):
        if self._last_status:return {**self._last_status,'foreground_snapshot':True,'processed':0,'verification_processed':0,'membership_processed':0}
        return {'foreground_snapshot':True,'total':0,'indexed':0,'remaining':0,'incomplete':True,'metadata_incomplete':True,'verification_remaining':0,'verification_error_count':0,'verification_min_bytes':None,'verification_incomplete':False,'processed':0,'verification_processed':0,'membership_remaining':0}

    # ==========================================
    # Function: Upgrade existing compact envelopes to an indexed contact-address projection.
    # Method: Fill at most one small metadata batch; triggers maintain all later inserts, changes and deletes.
    # ==========================================
    def fill_members(self,limit=512):
        if self._members_complete:return 0
        with self.store.db() as db:
            if db.execute('SELECT 1 FROM contact_member_scopes WHERE scope=?',(self.scope,)).fetchone():self._members_complete=True;return 0
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT c.message,c.envelope FROM contact_envelopes c WHERE c.scope=? AND NOT EXISTS(SELECT 1 FROM contact_member_index x WHERE x.scope=c.scope AND x.message=c.message) LIMIT ?",(self.scope,min(2048,max(1,int(limit))))).fetchall()
            for row in rows:
                for member in json.loads(row['envelope']).get('contacts',[]):
                    db.execute('INSERT INTO contact_member_index VALUES(?,?,?,?,?)',(self.scope,row['message'],member['address'],member['key'],json.dumps(member,ensure_ascii=False)))
            missing=db.execute('SELECT 1 FROM contact_envelopes c WHERE c.scope=? AND NOT EXISTS(SELECT 1 FROM contact_member_index x WHERE x.scope=c.scope AND x.message=c.message) LIMIT 1',(self.scope,)).fetchone()
            if not missing:db.execute('INSERT INTO contact_member_scopes VALUES(?) ON CONFLICT(scope) DO NOTHING',(self.scope,))
        self._members_complete=not bool(missing)
        return len(rows)

    # ==========================================
    # Function: Restrict one contact through actual indexed keys or saved alias membership.
    # Method: Keep the legacy JSON join only during the bounded upgrade and never cache editable aliases.
    # ==========================================
    def member_lookup(self,key='',db=None):
        if db is None:
            with self.store.db() as connection:return self.member_lookup(key,connection)
        if not self._members_complete:self._members_complete=bool(db.execute('SELECT 1 FROM contact_member_scopes WHERE scope=?',(self.scope,)).fetchone())
        if not self._members_complete:return PERSON_JOIN,[],[]
        join=PERSON_JOIN.replace("JOIN json_each(c.envelope,'$.contacts') cm","JOIN contact_member_index cm ON cm.scope=c.scope AND cm.message=c.message")
        if not key:return join,[],[]
        if key.startswith('contact:person:'):
            aliases=[row[0] for row in db.execute('SELECT address FROM address_mailboxes WHERE person=? AND suppressed=0',(key.removeprefix('contact:person:'),))]
            return join,['cm.address IN ('+','.join('?' for _ in aliases)+')' if aliases else '0'],aliases
        return join,['cm.conversation=?'],[key]

    # ==========================================
    # Function: Index bounded metadata and verify budgeted MIME payload collisions.
    # Method: Use a read-only completion path or reserve the writer before pending work.
    # ==========================================
    def _backfill(self, limit, verification_limit, verification_bytes):
        self.initialize()
        membership_processed=self.fill_members(max(512,int(limit))) if limit else 0
        limit = min(256, max(0, int(limit)))
        verification_limit = min(32, max(0, int(verification_limit)))
        verification_bytes = min(64 * 1024 * 1024, max(0, int(verification_bytes)))
        work = {'membership_processed':membership_processed,'processed': 0, 'verification_processed': 0, 'verification_bytes': 0,
                'verification_count_budget': verification_limit, 'verification_byte_budget': verification_bytes,
                'verification_deferred': 0}
        processed = 0
        with self.store.db() as db:
            status = self._status(db)
            can_verify = (status['verification_remaining'] and verification_limit and verification_bytes
                          and status['verification_min_bytes'] <= verification_bytes)
            if ((not status['remaining'] or not limit)
                    and not can_verify):
                if status['verification_remaining'] and verification_limit and verification_bytes:
                    work['verification_deferred'] = status['verification_remaining']
                return {**status, **work}
            db.execute('BEGIN IMMEDIATE')
            cursor = db.execute('''SELECT m.id,m.parsed,m.message_id,m.sender,m.subject,m.timestamp
                FROM messages m LEFT JOIN contact_envelopes c ON c.message=m.id AND c.scope=?
                WHERE c.message IS NULL ORDER BY m.timestamp DESC,m.id DESC LIMIT ?''', (self.scope, limit))
            for row in cursor:
                try:
                    parsed = json.loads(row['parsed'])
                    if not isinstance(parsed, dict):
                        parsed = {}
                except (TypeError, ValueError):
                    parsed = {}
                parsed.setdefault('sender', row['sender'])
                body = str(parsed.get('body', ''))
                attachments = parsed.get('attachments') or []
                headers = parsed.get('headers') or {}
                try:
                    date = parsedate_to_datetime(str(headers.get('date', '')))
                    event_time = (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
                except (TypeError, ValueError, OverflowError):
                    # parse_message uses ingestion time for missing dates; that is
                    # not stable evidence when the same RFC mail is cached twice.
                    event_time = str(headers.get('date', ''))
                fallback = _digest([row['message_id'], row['sender'], event_time, row['subject'],
                                    _digest(body), headers.get('from'), headers.get('to'), headers.get('cc'), headers.get('bcc')])
                envelope = conversation_envelope(parsed, self.own, fallback)
                from .address_book import observe_message
                observe_message(db,parsed,self.own)
                participants=envelope['to']+envelope['cc']+envelope['hidden_recipients'] if envelope['outgoing'] and envelope['kind']!='unknown' else envelope['peers']
                peers={item['address']:item for item in participants if item['address'] not in self.own}
                envelope['contacts']=[{**peer,'key':'contact:'+hashlib.sha256(json.dumps([address],ensure_ascii=False).encode()).hexdigest()[:32]} for address,peer in peers.items()]
                if not envelope['contacts']:envelope['contacts']=[{'address':'','name':'','key':envelope['key']}]

                # Message-ID alone is insufficient: changed payloads stay distinct.
                evidence = [str(headers.get('message-id') or row['message_id']),
                            [item['address'] for item in envelope['sender']], event_time,
                            row['subject'], _digest(body.replace('\r\n', '\n')),
                            _digest(parsed.get('html', '')),
                            [[item.get('name'), item.get('type'), item.get('size')] for item in attachments],
                            sorted(item['address'] for item in envelope['to'] + envelope['cc']),
                            # Routing variants must not inherit a safer copy's envelope.
                            sorted(item['address'] for item in envelope['reply_to']),
                            sorted(item['address'] for item in envelope['hidden_recipients']),
                            envelope['route']['safe'], envelope['route']['reason'],
                            str(headers.get('reply-to', '')), str(headers.get('bcc', ''))]
                base = _digest(evidence)
                dedup = base
                if _needs_payload_verification(parsed):
                    dedup = base + ':unverified:' + row['id']
                    db.execute('INSERT OR REPLACE INTO contact_attachment_candidates(scope,message,base) VALUES(?,?,?)',
                               (self.scope, row['id'], base))
                db.execute('''INSERT OR REPLACE INTO contact_envelopes
                    (message,scope,conversation,dedup,envelope,preview,sender,recipients,attachments)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (row['id'], self.scope, envelope['key'], dedup,
                     json.dumps(envelope, ensure_ascii=False), ' '.join(body.split())[:180],
                     ' '.join(item['address'] for item in envelope['sender']),
                     ' '.join(item['address'] for item in envelope['to'] + envelope['cc']), len(attachments)))
                processed += 1
            verification = self._verify_collisions(db, verification_limit, verification_bytes)
            status = self._status(db)
        return {**status, **work, **verification, 'processed': processed}

    # ==========================================
    # Function: Find payload-requiring metadata collisions among eligible live copies only.
    # Method: Count compact candidate hashes before considering any MIME payload bytes.
    # ==========================================
    def _collision_queue(self):
        where, values = self._where('')
        sql = '''WITH candidates AS (
            SELECT a.message,a.base,p.state,length(m.raw) AS raw_bytes,
                count(*) OVER (PARTITION BY a.base) AS candidates
            FROM contact_attachment_candidates a
            JOIN contact_envelopes c ON c.message=a.message AND c.scope=a.scope
            JOIN messages m ON m.id=a.message
            LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            LEFT JOIN contact_payload_fingerprints p ON p.message=a.message
            WHERE a.scope=? AND ''' + ' AND '.join(where) + ''')
            SELECT * FROM candidates WHERE candidates>1'''
        return sql, values

    # ==========================================
    # Function: Verify only colliding MIME payload candidates within explicit budgets.
    # Method: Persist canonical decoded-part hashes; keep unknown and failed rows separate.
    # ==========================================
    def _verify_collisions(self, db, limit, byte_budget):
        result = {'verification_processed': 0, 'verification_bytes': 0, 'verification_deferred': 0}
        if not limit or not byte_budget:
            return result
        queue, values = self._collision_queue()
        rows = db.execute('SELECT * FROM (' + queue + ') WHERE state IS NULL ORDER BY raw_bytes,message LIMIT ?',
                          values + [limit]).fetchall()
        for row in rows:
            if row['raw_bytes'] > byte_budget - result['verification_bytes']:
                result['verification_deferred'] += 1
                continue
            # The only raw SELECT in this module: one collision candidate after
            # count/byte admission, never singleton or full-mailbox MIME scanning.
            raw = db.execute('SELECT raw FROM messages WHERE id=?', (row['message'],)).fetchone()['raw']
            result['verification_processed'] += 1
            result['verification_bytes'] += len(raw)
            try:
                digest = _payload_fingerprint(raw)
                state, error = 'verified', ''
            except Exception as exc:
                digest, state, error = '', 'error', type(exc).__name__
            db.execute('''INSERT OR REPLACE INTO contact_payload_fingerprints
                (message,digest,state,error,raw_bytes) VALUES(?,?,?,?,?)''',
                (row['message'], digest, state, error, len(raw)))
        return result

    # ==========================================
    # Function: Expose projection coverage without concealing partially indexed mail.
    # Method: Count current messages with a live join rather than cached counters.
    # ==========================================
    def _status(self, db):
        row = db.execute('''SELECT count(*) AS total,count(c.message) AS indexed
            FROM messages m LEFT JOIN contact_envelopes c ON c.message=m.id AND c.scope=?''', (self.scope,)).fetchone()
        queue, values = self._collision_queue()
        verification = db.execute('''SELECT
            coalesce(sum(CASE WHEN state IS NULL THEN 1 ELSE 0 END),0) AS remaining,
            coalesce(sum(CASE WHEN state='error' THEN 1 ELSE 0 END),0) AS errors,
            min(CASE WHEN state IS NULL THEN raw_bytes END) AS min_bytes FROM (''' + queue + ')', values).fetchone()
        membership_remaining=0 if self._members_complete else db.execute('SELECT count(*) FROM contact_envelopes c WHERE c.scope=? AND NOT EXISTS(SELECT 1 FROM contact_member_index x WHERE x.scope=c.scope AND x.message=c.message)',(self.scope,)).fetchone()[0]
        metadata_incomplete = row['total'] != row['indexed']
        verification_incomplete = bool(verification['remaining'] or verification['errors'])
        return {'membership_remaining':membership_remaining,'total': row['total'], 'indexed': row['indexed'],
                'remaining': row['total'] - row['indexed'], 'metadata_incomplete': metadata_incomplete,
                'verification_remaining': verification['remaining'], 'verification_error_count': verification['errors'],
                'verification_min_bytes': verification['min_bytes'], 'verification_incomplete': verification_incomplete,
                'incomplete': metadata_incomplete or verification_incomplete or bool(membership_remaining)}

    # ==========================================
    # Function: Restrict account selection and visible cached successful messages.
    # Method: Bind account values and apply the shared folder-selection predicates to live cached sources.
    # ==========================================
    def _where(self, account):
        from .conversation_folders import predicates
        where,folder_values=predicates(self.store)
        values = [self.scope]+folder_values
        if isinstance(account, (list, tuple, set, frozenset)):
            where.append('m.account IN (' + ','.join('?' for _ in account) + ')' if account else '0')
            values.extend(account)
        elif account:
            where.append('m.account=?')
            values.append(account)
        return where, values

    # ==========================================
    # Function: Build live deduplicated message metadata without loading bodies.
    # Method: Use SQLite windows to merge copies and preserve current account flags.
    # ==========================================
    def _ctes(self, account='', key=''):
        where, values = self._where(account)
        member_join,extra,arguments=self.member_lookup(key);where.extend(extra);values.extend(arguments)
        if key:
            where.append(PERSON_KEY+'=?')
            values.append(key)
        sql = '''WITH member_rows AS (
            SELECT m.id,m.account,m.folder,m.subject,m.timestamp,m.seen,m.pinned,m.priority,
                m.category,m.message_id,'''+PERSON_KEY+''' AS conversation,ap.name AS person_name,ap.id AS person_id,cm.value AS contact_meta,
                coalesce(cp.muted,0) AS contact_muted,coalesce(cp.pinned,0) AS contact_pinned,coalesce(cp.blocked,0) AS contact_blocked,
                coalesce((SELECT min(address) FROM address_mailboxes WHERE person=ap.id AND suppressed=0),json_extract(cm.value,'$.address')) AS contact_address,
                CASE WHEN p.state='verified' AND a.message IS NOT NULL
                    THEN a.base||':'||p.digest ELSE c.dedup END AS dedup,
                c.envelope,c.preview,c.sender,c.recipients,c.attachments,
                CASE WHEN a.message IS NULL THEN 'not_needed' ELSE coalesce(p.state,'unverified') END AS verification_state,
                CASE WHEN a.message IS NULL THEN 0 ELSE 1 END AS payload_verification_required
            FROM messages m JOIN contact_envelopes c ON c.message=m.id AND c.scope=?
            LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            ''' + member_join + '''
            LEFT JOIN contact_attachment_candidates a ON a.message=c.message AND a.scope=c.scope
            LEFT JOIN contact_payload_fingerprints p ON p.message=m.id
            WHERE ''' + ' AND '.join(where) + '''), indexed AS (
                SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY conversation,id ORDER BY json_extract(contact_meta,'$.address')) AS member_rank FROM member_rows) WHERE member_rank=1), live AS (
                SELECT *,max(seen) OVER (PARTITION BY conversation,dedup) AS copy_seen,
                    max(pinned) OVER (PARTITION BY conversation,dedup) AS copy_pinned,
                    count(*) OVER (PARTITION BY conversation,dedup) AS copy_count,
                    row_number() OVER (PARTITION BY conversation,dedup ORDER BY
                        CASE WHEN folder='@sent' THEN 0 ELSE 1 END,account,id) AS copy_rank
                FROM indexed), unique_mail AS (
                SELECT * FROM live WHERE copy_rank=1)'''
        return sql, values

    # ==========================================
    # Function: Compile compact metadata search plus explicit body queries in SQLite.
    # Method: Bind literals; return matching conversations with their complete counts.
    # ==========================================
    def _search(self, query):
        if len(query) > 2000:
            raise ValueError('搜索条件过长')
        try:
            tokens = shlex.split(query)
        except ValueError:
            raise ValueError('搜索引号尚未闭合') from None
        clauses, values = [], []
        for token in tokens:
            negative = token.startswith('-')
            token = token[1:] if negative else token
            key, sep, term = token.partition(':')
            column = {'from': 'sender', 'to': 'recipients', 'subject': 'subject',
                      'account': 'account', 'folder': 'folder', 'in': 'folder', 'category': 'category'}.get(key.lower())
            if sep and column:
                clause = column + ' LIKE ?'
                parameters = ['%' + term + '%']
            elif sep and key.lower() == 'body':
                clause = 'EXISTS(SELECT 1 FROM messages bm WHERE bm.id=live.id AND bm.body LIKE ?)'
                parameters = ['%' + term + '%']
            elif token.lower() in ('is:unread', 'is:read', 'has:attachment'):
                clause = {'is:unread': 'copy_seen=0', 'is:read': 'copy_seen=1', 'has:attachment': 'attachments>0'}[token.lower()]
                parameters = []
            else:
                clause = '(subject LIKE ? OR sender LIKE ? OR recipients LIKE ? OR preview LIKE ? OR person_name LIKE ?)'
                parameters = ['%' + token + '%'] * 5
            clauses.append(('NOT (' + clause + ')') if negative else '(' + clause + ')')
            values.extend(parameters)
        return ' AND '.join(clauses) or '1', values

    # ==========================================
    # Function: Produce contact conversations across inbound and own-sent mail.
    # Method: Filter blocked people and sort pinned first in SQL before fetching bounded list rows.
    # ==========================================
    def list_conversations(self, account='', search='', limit=100, offset=0, backfill_limit=256,
                           verification_limit=8, verification_bytes=DEFAULT_VERIFICATION_BYTES):
        indexing = self.backfill(backfill_limit, verification_limit, verification_bytes)
        ctes, values = self._ctes(account)
        match, search_values = self._search(search)
        ctes += ''', matching AS (SELECT DISTINCT conversation FROM live WHERE contact_blocked=0 AND ''' + match + '''),
            ranked AS (SELECT *,row_number() OVER (PARTITION BY conversation ORDER BY timestamp DESC,id DESC) AS latest_rank
                FROM unique_mail), totals AS (
                SELECT conversation,count(*) AS count,sum(CASE WHEN copy_seen=0 THEN 1 ELSE 0 END) AS unread_count,
                    sum(copy_count) AS copies FROM unique_mail GROUP BY conversation)'''
        with self.store.db() as db:
            db.execute('BEGIN')
            total = db.execute(ctes + ' SELECT count(*) FROM matching', values + search_values).fetchone()[0]
            rows = db.execute(ctes + ''' SELECT r.*,t.count,t.unread_count,t.copies FROM ranked r
                JOIN totals t USING(conversation) JOIN matching s USING(conversation)
                WHERE latest_rank=1 ORDER BY contact_pinned DESC,timestamp DESC,id DESC LIMIT ? OFFSET ?''',
                values + search_values + [min(200, max(1, int(limit))), max(0, int(offset))]).fetchall()
            source_from = {}
            if rows:
                ids = [row['id'] for row in rows]
                placeholders = ','.join('?' for _ in ids)
                source_from = {source['id']: source['raw_from'] for source in db.execute(
                    "SELECT m.id,coalesce(d.raw_from,json_extract(m.parsed,'$.headers.from')) AS raw_from FROM messages m LEFT JOIN message_display d ON d.message=m.id WHERE m.id IN (" + placeholders + ')', ids)}
            items = [self._summary(row, source_from.get(row['id'])) for row in rows]
            for item in items:
                item['accounts'] = self._accounts(db, account, item['key'])
                item['route']['accounts'] = item['accounts']
                item['locations'] = self._copies(db, account, item['key'], item['message_key'])
                item['copy_ids'] = [copy['id'] for copy in item['locations']]
        return {'items': items, 'total': total, 'indexing': indexing, 'incomplete': indexing['incomplete']}

    # ==========================================
    # Function: Preserve all account choices behind a conversation, including copies.
    # Method: Query live indexed rows without expanding complete message payloads.
    # ==========================================
    def _accounts(self, db, account, key):
        where, values = self._where(account)
        member_join,extra,arguments=self.member_lookup(key,db);where.extend(extra);values.extend(arguments)
        return [row[0] for row in db.execute('''SELECT DISTINCT m.account FROM messages m
            JOIN contact_envelopes c ON c.message=m.id AND c.scope=?
            LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            '''+member_join+'''
            WHERE ''' + ' AND '.join(where) + ' AND '+PERSON_KEY+'=? ORDER BY m.account', values + [key])]

    # ==========================================
    # Function: Expose exact live duplicate locations for read flags and account choices.
    # Method: Restrict by both contact and content evidence, never the RFC id alone.
    # ==========================================
    def _copies(self, db, account, key, dedup):
        where, values = self._where(account)
        member_join,extra,arguments=self.member_lookup(key,db);where.extend(extra);values.extend(arguments)
        return [dict(row) for row in db.execute('''SELECT DISTINCT m.id,m.account,m.folder,m.seen,m.pinned
            FROM messages m JOIN contact_envelopes c ON c.message=m.id AND c.scope=?
            LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            ''' + member_join + '''
            LEFT JOIN contact_attachment_candidates a ON a.message=c.message AND a.scope=c.scope
            LEFT JOIN contact_payload_fingerprints p ON p.message=m.id
            WHERE ''' + ' AND '.join(where) + ''' AND '''+PERSON_KEY+'''=? AND
            (CASE WHEN p.state='verified' AND a.message IS NOT NULL THEN a.base||':'||p.digest ELSE c.dedup END)=?
            ORDER BY m.account,m.folder,m.id''',
            values + [key, dedup])]

    # ==========================================
    # Function: Shape stable contact identity separately from the latest mail author.
    # Method: Preserve original RFC routing, expose durable policies and never substitute own author for the contact.
    # ==========================================
    def _summary(self, row, raw_from=None):
        envelope = json.loads(row['envelope'])
        sender = parse_participants(raw_from) if raw_from is not None else envelope['sender']
        author = sender[0] if sender else {'address': '', 'name': ''}
        member=json.loads(row['contact_meta']);peers=[{'address':member['address'],'name':member['name']}] if member['address'] else [dict(peer) for peer in envelope['peers']]
        for peer in peers:
            if peer['address'] == author['address']:
                peer['name'] = author['name']
        title = peers[0]['name'] or peers[0]['address'] if peers else ''
        if 'person_name' in row.keys() and row['person_name']:title=row['person_name']
        if envelope['kind'] == 'sent' and not member['address']:
            title = '我发出的多收件人邮件 · ' + (author['address'] or '本邮箱')
        else:
            title = title or {'self': '自己', 'unknown': '未知发件人'}.get(envelope['kind'], '未知发件人')
        author_name = '我' if envelope['outgoing'] else author['name'] or author['address'] or '未知发件人'
        route = {**envelope['route'], 'account': row['account'], 'message': row['id'],
                 'in_reply_to': row['message_id'], 'subject': row['subject']}
        if envelope['kind']=='sent' and member['address']:
            route.update(safe=False,reason=route.get('reason') or 'multiple_recipients',requires_full_editor=True)
        return {'person_id':row['person_id'] or '', 'contact_address':row['contact_address'] or '', 'contact_name':title,
                'muted':bool(row['contact_muted']),'contact_pinned':bool(row['contact_pinned']),'blocked':bool(row['contact_blocked']),
                'key': row['conversation'], 'message_key': row['dedup'], 'title': title, 'kind': 'direct' if member['address'] else envelope['kind'], 'peers': peers,
                'id': row['id'], 'latest_id': row['id'], 'account': row['account'], 'folder': row['folder'],
                'subject': row['subject'], 'preview': row['preview'], 'timestamp': row['timestamp'],
                'seen': bool(row['copy_seen']), 'pinned': bool(row['copy_pinned']),
                'outgoing': envelope['outgoing'], 'own_direction': 'outgoing' if envelope['outgoing'] else 'incoming',
                'sender': sender, 'latest_author': author_name, 'latest_author_address': author['address'],
                'count': row['count'] if 'count' in row.keys() else 1,
                'unread_count': row['unread_count'] if 'unread_count' in row.keys() else int(not row['copy_seen']),
                'copies': row['copies'] if 'copies' in row.keys() else row['copy_count'], 'route': route,
                'verification_state': row['verification_state'],
                'payload_verification_required': bool(row['payload_verification_required']),
                'dedup_verified': row['verification_state'] in ('verified', 'not_needed')}

    # ==========================================
    # Function: Read every live unread source copy for one canonical contact across all accounts.
    # Method: Use indexed membership plus relevant unindexed headers, without completing unrelated mailbox indexing.
    # ==========================================
    def unread_sources(self,key):
        self.initialize();where,values=self._where('')
        with self.store.db() as db:
            member_join,extra,arguments=self.member_lookup(key,db);where.extend(extra);values.extend(arguments)
            sources=[dict(row) for row in db.execute('SELECT DISTINCT m.id,m.account,m.folder FROM messages m JOIN contact_envelopes c ON c.message=m.id AND c.scope=? LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder '+member_join+' WHERE '+' AND '.join(where)+' AND m.seen=0 AND '+PERSON_KEY+'=?',values+[key])]
            if key.startswith('contact:person:'):
                aliases={row[0] for row in db.execute('SELECT address FROM address_mailboxes WHERE person=? AND suppressed=0',(key.removeprefix('contact:person:'),))}
            else:
                row=db.execute('SELECT value FROM contact_member_index WHERE scope=? AND conversation=? LIMIT 1',(self.scope,key)).fetchone()
                if row:aliases={json.loads(row[0])['address']}
                else:
                    row=db.execute('SELECT envelope FROM contact_envelopes WHERE scope=? AND conversation=? LIMIT 1',(self.scope,key)).fetchone()
                    aliases={member['address'] for member in json.loads(row[0]).get('contacts',[]) if member['key']==key} if row else set()
            if not aliases and not self._members_complete:
                row=db.execute('SELECT cm.value FROM contact_envelopes c JOIN messages m ON m.id=c.message '+PERSON_JOIN+' WHERE c.scope=? AND '+PERSON_KEY+'=? LIMIT 1',(self.scope,key)).fetchone()
                if row:aliases={json.loads(row[0])['address']}
            aliases.discard('')
            if aliases:
                senders=sorted(aliases|set(self.own));marks=','.join('?' for _ in senders);raw_where,raw_values=self._where('')
                candidates=db.execute("SELECT m.id,m.account,m.folder,json_extract(m.parsed,'$.headers') AS headers,json_extract(m.parsed,'$.from_valid') AS from_valid FROM messages m LEFT JOIN contact_envelopes c ON c.message=m.id AND c.scope=? LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder WHERE "+' AND '.join(raw_where)+" AND c.message IS NULL AND m.seen=0 AND (m.sender IN ("+marks+") OR m.sender GLOB '*[^ -~]*' OR m.sender GLOB '*.')",raw_values+senders).fetchall()
                from .participant_identity import _single_from
                for row in candidates:
                    headers=json.loads(row['headers'] or '{}');raw=headers.get('from','')
                    if row['from_valid']==0 or not _single_from(raw):continue
                    sender=parse_participants(raw);outgoing=bool(sender and sender[0]['address'] in self.own)
                    participants=parse_participants([headers.get(name,'') for name in ('to','cc','bcc')]) if outgoing else sender
                    if any(participant['address'] in aliases for participant in participants):sources.append({name:row[name] for name in ('id','account','folder')})
        return sources

    # ==========================================
    # Function: Read a bounded chronological chat window with an older-message cursor.
    # Method: Select deduplicated summaries first, then fetch parsed content for that slice.
    # ==========================================
    def conversation_messages(self, key, account='', before=None, limit=50, backfill_limit=256,
                              verification_limit=8, verification_bytes=DEFAULT_VERIFICATION_BYTES,
                              content_bytes=8 * 1024 * 1024):
        indexing = self.backfill(backfill_limit, verification_limit, verification_bytes)
        limit = min(100, max(1, int(limit)))
        content_budget = min(64 * 1024 * 1024, max(1, int(content_bytes)))
        loaded_bytes, content_limited = 0, False
        ctes, values = self._ctes(account, key)
        where, page_values = '', []
        if before is not None:
            if not isinstance(before, (tuple, list)) or len(before) != 2:
                raise ValueError('before must be [timestamp, message identity]')
            where = ' WHERE (timestamp<? OR (timestamp=? AND id<?))'
            page_values = [float(before[0]), float(before[0]), str(before[1])]
        with self.store.db() as db:
            db.execute('BEGIN')
            count = db.execute(ctes + ' SELECT count(*) FROM unique_mail', values).fetchone()[0]
            rows = db.execute(ctes + ' SELECT * FROM unique_mail' + where + ' ORDER BY timestamp DESC,id DESC LIMIT ?', values + page_values + [limit + 1]).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            items = []
            for row in selected:
                size = db.execute('SELECT length(CAST(parsed AS BLOB)) FROM messages WHERE id=?', (row['id'],)).fetchone()[0]
                if items and loaded_bytes + size > content_budget:
                    has_more, content_limited = True, True
                    break
                content = db.execute('SELECT parsed FROM messages WHERE id=?', (row['id'],)).fetchone()
                loaded_bytes += size
                try:
                    parsed = json.loads(content['parsed'])
                except (TypeError, ValueError):
                    parsed = {}
                item = self._summary(row, (parsed.get('headers') or {}).get('from'))
                item.update(body=str(parsed.get('body', '')), attachments=parsed.get('attachments') or [],
                            parsed=parsed, envelope=json.loads(row['envelope']))
                item['locations'] = self._copies(db, account, key, row['dedup'])
                item['copy_ids'] = [copy['id'] for copy in item['locations']]
                items.append(item)
            items.reverse()
            accounts = self._accounts(db, account, key)
        oldest = [items[0]['timestamp'], items[0]['id']] if items else None
        return {'key': key, 'items': items, 'count': count, 'oldest': oldest,
                'has_more': has_more, 'before': oldest if has_more else None,
                'accounts': accounts, 'indexing': indexing, 'incomplete': indexing['incomplete'],
                'content_bytes': loaded_bytes, 'content_byte_budget': content_budget,
                'content_limited': content_limited, 'content_budget_exceeded': loaded_bytes > content_budget}
