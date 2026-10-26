"""Local RFC 8098 displayed-MDN correlation; no remote pixels or tracking server."""
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import json
import time

# ==========================================
# Function: Correlate a returned displayed receipt with a confirmed outgoing job.
# Method: Require a top-level MDN report, original ID, sent job/account and envelope recipient.
# ==========================================
def ingest_report(store, account, identity, raw):
    if b'disposition-notification' not in raw[:8192].lower():return
    message=BytesParser(policy=policy.default).parsebytes(raw)
    if message.get_content_type()!='multipart/report' or message.get_param('report-type')!='disposition-notification':return
    for part in message.iter_parts():
        if part.get_content_type()!='message/disposition-notification':continue
        fields=part.get_payload()
        if not isinstance(fields,list) or not fields:continue
        report=fields[0];original=str(report.get('Original-Message-ID','')).strip()
        recipient=str(report.get('Final-Recipient','')).partition(';')[2].strip().casefold()
        disposition=str(report.get('Disposition','')).partition(';')[2].strip().split('/')[0].lower()
        if not original or not recipient or disposition!='displayed':continue
        senders={address.casefold() for _,address in getaddresses([str(message.get('From',''))])}
        if recipient not in senders:continue
        with store.db() as db:
            job=db.execute("SELECT id,envelope,draft FROM jobs WHERE account=? AND message_id=? AND state IN ('sent','partial')",(account,original)).fetchone()
            if not job or recipient not in {str(value).casefold() for value in json.loads(job['envelope'] or '[]')}:continue
            if not json.loads(job['draft']).get('request_receipt'):continue
            db.execute('INSERT OR IGNORE INTO read_receipts VALUES(?,?,?,?)',(job['id'],recipient,time.time(),identity))
