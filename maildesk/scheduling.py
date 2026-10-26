"""Local send-later date presets, validation and native calendar selection."""
import ctypes as C
from datetime import datetime,timedelta
import time

PRESETS=[('today','今天稍后'),('tonight','今晚'),('tomorrow','明天上午'),('tomorrow_evening','明晚'),
         ('weekend','周末'),('next_week','下周'),('month','一个月后')]

# ==========================================
# Function: Resolve a local schedule preset using user-selected morning/evening times.
# Method: Preserve wall-clock meaning and move expired same-day presets to the next valid date.
# ==========================================
def preset_time(key, store, now=None):
    now=now or datetime.now();morning=store.preference('schedule_morning','09:00');evening=store.preference('schedule_evening','20:00')
    # ==========================================
    # Function: Combine a preset day and validated local clock preference.
    # Method: Keep date arithmetic independent of the timezone conversion at queue time.
    # ==========================================
    def at(date,value):return datetime.combine(date,datetime.strptime(value,'%H:%M').time())
    if key=='today':return (now+timedelta(hours=store.preference('schedule_today_hours',2))).replace(second=0,microsecond=0)
    if key=='tonight':result=at(now.date(),evening)
    elif key=='tomorrow':result=at(now.date()+timedelta(days=1),morning)
    elif key=='tomorrow_evening':result=at(now.date()+timedelta(days=1),evening)
    elif key=='weekend':result=at(now.date()+timedelta(days=(5-now.weekday())%7),morning)
    elif key=='next_week':result=at(now.date()+timedelta(days=7-now.weekday()),morning)
    elif key=='month':result=at(now.date()+timedelta(days=30),morning)
    else:raise ValueError('未知时间预设')
    if result<=now:result+=timedelta(days=7 if key=='weekend' else 1)
    return result

# ==========================================
# Function: Validate a future local/offset-aware time before queueing delivery.
# Method: Reject past, excessively distant and nonexistent local DST wall-clock values.
# ==========================================
def schedule_timestamp(value, now=None):
    now=time.time() if now is None else now
    selected=datetime.fromisoformat(value.strip()) if isinstance(value,str) else value
    stamp=selected.timestamp()
    if selected.tzinfo is None and datetime.fromtimestamp(stamp).replace(microsecond=0)!=selected.replace(microsecond=0):
        raise ValueError('这个本地时间不存在，请重新选择')
    if stamp<=now:raise ValueError('请选择未来的发送时间')
    if stamp>now+366*86400:raise ValueError('发送时间最多提前一年')
    return stamp

# ==========================================
# Function: Select a schedule with quick presets, a native calendar and editable local time.
# Method: Return only after explicit confirmation, keeping invalid choices open for correction.
# ==========================================
def choose_schedule(app, title='稍后发送', current='', clear=True):
    from .desktop_forms import Form
    g=app.g;enabled=app.service.store.preference('schedule_enabled',[key for key,_ in PRESETS])
    options=[(key,label) for key,label in PRESETS if key in enabled]+[('custom','自定日期和时间')]
    form=Form(app,title,[('preset','快捷时间','combo',options),('when','日期和时间','text',[])],580)
    calendar=g.gtk_calendar_new();g.gtk_box_pack_start(g.gtk_dialog_get_content_area(form.window),calendar,0,1,6)
    form.calendar=calendar;form.value('when',current or preset_time('tomorrow',app.service.store).isoformat(timespec='minutes'))
    updating=[False]
    # ==========================================
    # Function: Apply a time preset while keeping the displayed date and time explicit.
    # Method: Convert the stored local preference to an ISO field consumed by validation.
    # ==========================================
    def selected(*unused):
        key=form.value('preset')
        if key and key!='custom':
            value=preset_time(key,app.service.store);updating[0]=True
            form.value('when',value.isoformat(timespec='minutes'))
            g.gtk_calendar_select_month(calendar,value.month-1,value.year);g.gtk_calendar_select_day(calendar,value.day)
            updating[0]=False
    # ==========================================
    # Function: Combine a calendar day with the user's currently chosen local clock time.
    # Method: Read GtkCalendar's zero-based month through its public C API.
    # ==========================================
    def day_selected(*unused):
        if updating[0]:return
        year,month,day=C.c_uint(),C.c_uint(),C.c_uint()
        g.gtk_calendar_get_date(calendar,C.byref(year),C.byref(month),C.byref(day))
        try:clock=datetime.fromisoformat(form.value('when')).time()
        except ValueError:clock=datetime.strptime(app.service.store.preference('schedule_morning','09:00'),'%H:%M').time()
        value=datetime(year.value,month.value+1,day.value,clock.hour,clock.minute)
        form.value('preset','custom');form.value('when',value.isoformat(timespec='minutes'))
    value=datetime.fromisoformat(form.value('when'))
    g.gtk_calendar_select_month(calendar,value.month-1,value.year);g.gtk_calendar_select_day(calendar,value.day)
    g.connect(form.fields['preset'][0],'changed',selected,group=form.group)
    g.connect(calendar,'day-selected',day_selected,group=form.group)
    form.value('preset','custom' if current or 'tomorrow' not in enabled else 'tomorrow')
    form.button('取消',-6)
    if clear:form.button('清除计划',2)
    form.button('确认时间',1)
    g.label(form.note,'使用此系统本地时间。客户端运行时投递；关闭后保留计划，下次启动处理已到期邮件。')
    g.gtk_widget_show_all(form.window)
    try:
        while True:
            response=g.gtk_dialog_run(form.window)
            if response==2:return ''
            if response!=1:return None
            try:
                stamp=schedule_timestamp(form.value('when'))
                return datetime.fromtimestamp(stamp).isoformat(timespec='minutes')
            except ValueError as error:g.label(form.note,str(error))
    finally:form.close()
