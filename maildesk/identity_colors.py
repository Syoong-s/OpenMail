"""Independent stable sender fills and persistent mail-account outline colors."""
from functools import lru_cache
import colorsys
import hashlib
import re
from email.utils import parseaddr

ACCOUNT_PALETTE=('#4fa8ff','#f2ad5e','#59c5a3','#b295ef','#eb8295','#65c9d7','#d7c66a','#b6c5db')

# ==========================================
# Function: Derive a stable readable avatar fill from a sender address.
# Method: Hash the normalized address into a muted HLS background independently of account/name.
# ==========================================
@lru_cache(maxsize=512)
def sender_color(address):
    canonical=(parseaddr(address)[1] or address).strip().casefold()
    digest=hashlib.sha256(canonical.encode()).digest()
    hue=int.from_bytes(digest[:2],'big')/65535
    saturation=.36+digest[2]/255*.18
    red,green,blue=colorsys.hls_to_rgb(hue,.31,saturation)
    return '#'+''.join(f'{round(value*255):02x}' for value in (red,green,blue))

# ==========================================
# Function: Preserve explicit account colors and allocate distinct available defaults.
# Method: Store assignments locally so adding or reordering accounts never shifts existing colors.
# ==========================================
class IdentityColors:
    # ==========================================
    # Function: Bind identity settings to the existing local preference store.
    # Method: Keep color data separate from provider credentials and sender fill calculation.
    # ==========================================
    def __init__(self,store):
        self.store=store

    # ==========================================
    # Function: Resolve a durable account outline color.
    # Method: Allocate the first unused palette entry, then use a stable fallback when exhausted.
    # ==========================================
    def account_color(self,account):
        return self.snapshot([account])['colors'][account]

    # ==========================================
    # Function: Read one consistent set of account assignments for a list refresh.
    # Method: Allocate missing colors in one batch and avoid per-row SQLite preference queries.
    # ==========================================
    def snapshot(self,accounts):
        colors=self.store.preference('account_colors',{});changed=False
        for account in dict.fromkeys(accounts):
            value=colors.get(account)
            if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value):continue
            value=next((item for item in ACCOUNT_PALETTE if item not in colors.values()),None)
            if value is None:
                hue=int.from_bytes(hashlib.sha256(account.encode()).digest()[:2],'big')/65535
                for attempt in range(len(colors)+1):
                    rgb=colorsys.hls_to_rgb((hue+attempt*.381966)%1,.68,.64)
                    value='#'+''.join(f'{round(channel*255):02x}' for channel in rgb)
                    if value not in colors.values():break
            colors[account]=value;changed=True
        if changed:self.store.set_preference('account_colors',colors)
        return {'colors':colors,'enabled':self.store.preference('account_colors_enabled',True)}

    # ==========================================
    # Function: Save a user-selected account outline.
    # Method: Validate the entire hex color before it reaches native CSS.
    # ==========================================
    def set_account_color(self,account,color):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('请选择有效的账户颜色')
        colors=self.store.preference('account_colors',{});colors[account]=color.lower();self.store.set_preference('account_colors',colors)

    # ==========================================
    # Function: Describe independent avatar fill and account border settings.
    # Method: Keep the sender fill constant across accounts and permit disabling only the outline.
    # ==========================================
    def style(self,sender,account,state=None):
        state=state or self.snapshot([account])
        return {'background':sender_color(sender),'border':state['colors'][account].lower() if state['enabled'] else 'transparent'}
