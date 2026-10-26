"""Trusted presentation-only content fitting for embedded email documents."""
import math

# Host code only: email scripts remain blocked by the existing immutable HTTP CSP.
MEASURE_MAIL = r'''(() => {
  const body = document.body;
  if (!body) return null;
  let state = window.__maildeskFit;
  if (!state) {
    state = window.__maildeskFit = {dirty:true, result:null};
    const dirty = () => { state.dirty = true; };
    new ResizeObserver(dirty).observe(body);
    new MutationObserver(dirty).observe(body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['src','width','height']});
    addEventListener('resize', dirty);
    body.addEventListener('load', dirty, true);
    body.addEventListener('error', dirty, true);
    if (document.fonts) document.fonts.ready.then(dirty);
  }
  if (!state.dirty && state.result) return {...state.result, viewport:innerHeight, title:document.title};
  const ink = el => !!(el.textContent || '').replace(/[\s\u00a0\u200b]/g,'') || !!el.querySelector('img,hr');
  let trimBudget=20000;
  const trim = (parent,depth=0) => {
    if(depth>64) return;
    for (let node = parent.lastChild; node; node = node.previousSibling) {
      if(--trimBudget<0) return;
      if (node.nodeType === 3) { if (node.textContent.trim()) break; else continue; }
      if (node.nodeType !== 1) continue;
      if (!ink(node) && !node.matches('img,hr')) { node.style.setProperty('display','none','important'); continue; }
      if (!node.matches('img,hr,pre,code,table,td,th')) {
        trim(node,depth+1);
        node.style.setProperty('height','auto','important');
        node.style.setProperty('min-height','0','important');
        const style = getComputedStyle(node);
        if (parseFloat(style.marginBottom)>16) node.style.setProperty('margin-bottom','8px','important');
        if (parseFloat(style.paddingBottom)>20) node.style.setProperty('padding-bottom','8px','important');
      }
      break;
    }
  };
  trim(body);
  for (const el of [document.documentElement,body]) {
    el.style.setProperty('height','auto','important'); el.style.setProperty('min-height','0','important');
    el.style.setProperty('margin-bottom','0','important'); el.style.setProperty('padding-bottom','8px','important');
  }
  const visible = el => {
    for (let n=el; n && n.nodeType===1; n=n.parentElement) {
      const s=getComputedStyle(n);
      if(s.display==='none' || s.visibility==='hidden' || parseFloat(s.opacity)===0) return false;
    }
    return true;
  };
  let bottom=0, count=0, complete=true;
  const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT);
  for(let node=walker.nextNode(); node; node=walker.nextNode()) {
    if(++count>20000) {complete=false;break;}
    const text=node.textContent, end=text.search(/[\s\u00a0\u200b]*$/);
    if(!end || !text.slice(0,end).trim() || !visible(node.parentElement)) continue;
    const range=document.createRange();range.setStart(node,0);range.setEnd(node,end);
    for(const r of range.getClientRects()) if(r.width>0 && r.height>0) bottom=Math.max(bottom,r.bottom+scrollY);
  }
  for(const el of body.querySelectorAll('img,hr')) {
    if(!visible(el)) continue;
    const r=el.getBoundingClientRect();
    if(r.width>2 && r.height>2) bottom=Math.max(bottom,r.bottom+scrollY);
  }
  if(!complete) bottom=Math.max(bottom,body.scrollHeight);
  state.dirty=false;
  state.result={height:Math.ceil(Math.max(28,bottom)+12),complete,viewport:innerHeight,title:document.title};
  return state.result;
})()'''

# ==========================================
# Function: Convert actual browser content bounds into a bounded logical GTK allocation.
# Method: Use the live viewport ratio for zoom/DPI and reject stale or nonfinite measurement values.
# ==========================================
def fitted_height(measurement,allocated):
    if not isinstance(measurement,dict):return None
    try:height=float(measurement['height']);viewport=float(measurement['viewport']);allocated=float(allocated)
    except (KeyError,TypeError,ValueError):return None
    if not all(math.isfinite(value) for value in (height,viewport,allocated)):return None
    if not 0<=height<=10000000 or viewport<8 or allocated<8:return None
    ratio=allocated/viewport
    if not .25<=ratio<=8:return None
    return min(5000,max(44,math.ceil(height*ratio)+2))
