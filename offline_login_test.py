# -*- coding: utf-8 -*-
"""اختبار الدخول المحلي بدون إنترنت:
1) تسجيل منشأة -> موافقة المالك -> تفعيل -> تعيين اسم مستخدم وكلمة سر
2) تسجيل خروج ثم الدخول باسم المستخدم/البريد (مع الإنترنت)
3) قطع الإنترنت (BrowserContext offline=True) والتحقق من الدخول
4) كلمة سر خاطئة وحساب غير موجود في وضع عدم الاتصال => رسائل خطأ واضحة دون تعليق
5) الدخول المتذكر بعد إعادة تحميل الصفحة بدون إنترنت
"""
from playwright.sync_api import sync_playwright
import time, random

BASE = 'http://localhost:8899'
OWNER_PASS = 'MySecretPass2026'

def open_login_page(page):
    page.goto(BASE + '/tenant.html')
    page.wait_for_timeout(5000)
    # تخطي شاشة الترحيب إن ظهرت
    try:
        page.wait_for_selector('.onboard-skip', timeout=3000)
        page.click('.onboard-skip')
        page.wait_for_timeout(1000)
    except Exception:
        pass

def fill_input(page, selector, value):
    page.evaluate(f"""(() => {{ var el = document.querySelector('{selector}'); if(el) {{ el.value = '{value}'; el.dispatchEvent(new Event('input', {{bubbles:true}})); }} }})""")

def register_tenant(page, email):
    open_login_page(page)
    name = 'منشأة اختبار الدخول المحلي ' + str(random.randint(1000, 9999))
    # النقر عبر locator
    page.evaluate("document.querySelectorAll('a,button').forEach(e=>{if(e.textContent.includes('طلب تفعيل نظام جديد'))e.click()})")
    page.wait_for_timeout(2500)
    page.wait_for_selector('#reg-nursery-name', timeout=10000)
    fill_input(page, '#reg-nursery-name', name)
    fill_input(page, '#reg-email', email)
    fill_input(page, '#reg-phone', '967712345678')
    btn = page.query_selector('#view-register button.login-btn')
    assert btn is not None, 'register button missing'
    btn.click()
    # انتظار انتقال الشاشة إلى view-sms وامتلاء رسالة الإشعار
    page.wait_for_selector('#sms-msg-text', timeout=10000)
    for _ in range(10):
        sms = page.evaluate("document.getElementById('sms-msg-text').value || ''")
        if sms:
            break
        page.wait_for_timeout(500)
    # الرمز محفوظ في متغير الصفحة (رسالة الإشعار لا تتضمنه لأن المستأجر يراه فقط بعد موافقة المالك)
    code = page.evaluate("(window._lastRegData && window._lastRegData.code) || (window._lastReqCode) || ''")
    print('sms text:', sms[:100], '| extracted code:', code)
    assert code.startswith('TEN-'), 'code not found: ' + str(code)
    return name, code

def owner_approve(opage, code):
    opage.goto(BASE + '/owner.html?verify=owner')
    opage.wait_for_timeout(6000)
    try:
        opage.wait_for_selector('#owner-pass-input', timeout=3000)
        fill_input(opage, '#owner-pass-input', OWNER_PASS)
        opage.evaluate("""document.querySelectorAll('button').forEach(b => { if(b.textContent.includes('تأكيد التثبيت')) b.click(); })""")
        opage.wait_for_timeout(5000)
    except Exception:
        pass
    res = opage.evaluate(f"""async () => {{
        await approveNewTenant('{code}');
        await new Promise(r => setTimeout(r, 1500));
        var d = await db.collection('tenants_requests').doc('{code}').get();
        return d.exists ? JSON.stringify(d.data()) : 'MISSING';
    }}""")
    print('approve res:', res)
    import json
    try:
        data = json.loads(res)
        return data.get('activationCode', ''), data.get('cloudId', '')
    except Exception:
        return '', ''

def tenant_activate(page, req_code, act_code, email, username, password):
    page.bring_to_front()
    # إعادة تحميل الصفحة والعودة لشاشة الإشعار (view-sms) أو شاشة التفعيل إن كانت ظاهرة
    page.reload()
    page.wait_for_timeout(6000)
    open_login_page(page)
    page.wait_for_timeout(2000)
    sms_visible = page.evaluate("document.getElementById('view-sms').style.display")
    act_visible = page.evaluate("document.getElementById('view-activate').style.display")
    print('view-sms:', sms_visible, 'view-activate:', act_visible)
    if sms_visible == 'block':
        fill_input(page, '#act-request-id', act_code)
        fill_input(page, '#act-email', email)
        page.evaluate("""document.querySelectorAll('#view-sms button').forEach(b => { if(b.textContent.includes('إدخال رمز التفعيل')) b.click(); })""")
        page.wait_for_timeout(1500)
    elif act_visible == 'block':
        fill_input(page, '#act-request-id', act_code)
        fill_input(page, '#act-email', email)
    else:
        # overlay مخفي — أعد عرض شاشة تسجيل الدخول ثم انتقل للتفعيل
        page.evaluate("""document.getElementById('login-overlay').classList.remove('hidden'); document.getElementById('login-overlay').style.display = 'flex'; showLoginView('activate');""")
        page.wait_for_timeout(2000)
        fill_input(page, '#act-request-id', act_code)
        fill_input(page, '#act-email', email)
    # الآن في view-activate: التحقق من الرمز (متابعة) — سحابي، يحتاج db جاهزًا
    page.evaluate("""(async () => { try { await verifyActivationCode(); } catch(e) { window.__actErr = String(e); } })""")
    page.wait_for_timeout(3000)
    err = page.evaluate("window.__actErr || 'none'")
    print('verifyActivationCode err:', err)
    page.wait_for_selector('#act-username', timeout=15000)
    fill_input(page, '#act-sms-code', act_code)
    fill_input(page, '#act-username', username)
    fill_input(page, '#act-pass', password)
    fill_input(page, '#act-pass2', password)
    page.evaluate("""document.querySelectorAll('#login-box button').forEach(b => { if(b.textContent.includes('حفظ والدخول')) b.click(); })""")
    page.wait_for_timeout(5500)
    # تسجيل خروج ومسح الجلسة المحلية للبدء من شاشة الدخول
    page.evaluate("""(async () => { if(typeof logout === 'function') logout(); localStorage.removeItem('nr_last_user'); localStorage.removeItem('elen_installed'); })""")
    page.wait_for_timeout(2500)
    open_login_page(page)

def clear_session(page):
    page.evaluate("""(() => { localStorage.removeItem('nr_last_user'); localStorage.removeItem('elen_installed'); })""")

def do_login(page, ident, password, expect_ok=True):
    before = page.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    accounts = page.evaluate("""JSON.parse(localStorage.getItem('nr_local_accounts') || '[]').map(a => a.username + ':' + a.email)""")
    print('  local accounts:', accounts, '| overlay hidden before:', before)
    fill_input(page, '#login-email', ident)
    fill_input(page, '#login-pass', password)
    page.evaluate("tenantSecureLogin()")
    page.wait_for_timeout(6000)
    hidden = page.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    err = page.evaluate("""document.getElementById('login-error').textContent""")
    ok = hidden == expect_ok
    print(f"  result: hidden={hidden} error='{err}'")
    assert ok, f'login test failed (expect_ok={expect_ok})'
    return hidden

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale='ar')
    tpage = ctx.new_page()
    opage = ctx.new_page()
    email = 'off-' + str(random.randint(1000, 9999)) + '@elen.com'
    username = 'offlineuser'
    password = 'OfflinePass99'

    name, code = register_tenant(tpage, email)
    print('tenant code:', code, 'name:', name)
    act_code, cloud_id = owner_approve(opage, code)
    print('activation code:', act_code)
    tenant_activate(tpage, code, act_code, email, username, password)

    # اختبار 1: الدخول المحترف بالإنترنت (اسم المستخدم)
    print('--- Test 1: online login by username ---')
    do_login(tpage, username, password, expect_ok=True)
    clear_session(tpage)
    tpage.reload()
    tpage.wait_for_timeout(4500)

    # اختبار 2: الدخول بالبريد الإلكتروني مع الإنترنت
    print('--- Test 2: online login by email ---')
    do_login(tpage, email, password, expect_ok=True)
    clear_session(tpage)
    tpage.reload()
    tpage.wait_for_timeout(4500)

    # اختبار 3: الدخول بدون إنترنت (اسم المستخدم) — على نفس الصفحة/الجهاز الذي فُعّل فيه الحساب
    print('--- Test 3: OFFLINE login by username ---')
    # تسجيل الخروج في الصفحة الأصلية (tpage) للبدء من شاشة الدخول
    tpage.evaluate("""(() => { if(typeof logout === 'function') logout(); localStorage.removeItem('nr_last_user'); localStorage.removeItem('elen_installed'); localStorage.removeItem('elen_first_run'); })""")
    tpage.wait_for_timeout(1500)
    open_login_page(tpage)
    # قطع الاتصال (محاكاة انقطاع الإنترنت على الجهاز نفسه)
    ctx.set_offline(True)
    do_login(tpage, username, password, expect_ok=True)

    # اختبار 4: كلمة سر خاطئة بدون إنترنت
    print('--- Test 4: OFFLINE wrong password ---')
    fill_input(tpage, '#login-pass', 'WrongPass!!')
    tpage.evaluate("tenantSecureLogin()")
    tpage.wait_for_timeout(6000)
    err = tpage.evaluate("""document.getElementById('login-error').textContent""")
    hidden = tpage.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    print('  wrong-pass: hidden=', hidden, 'error="', err, '"')
    assert 'كلمة السر غير صحيحة' in err
    # ملاحظة: قد يُخفى overlay جزئيًا ثم يعاد عرضه؛ المهم وجود رسالة الخطأ

    # اختبار 5: حساب غير موجود بدون إنترنت
    print('--- Test 5: OFFLINE unknown account ---')
    fill_input(tpage, '#login-email', 'unknown-user-xyz')
    fill_input(tpage, '#login-pass', 'SomePass123')
    tpage.evaluate("tenantSecureLogin()")
    tpage.wait_for_timeout(9000)
    err = tpage.evaluate("""document.getElementById('login-error').textContent""")
    hidden = tpage.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    print('  unknown: hidden=', hidden, 'error="', err, '"')
    assert ('لا يوجد اتصال بالإنترنت' in err), 'expected offline error, got: ' + err + ' (hidden=' + str(hidden) + ')'

    # اختبار 6: الدخول المتذكر بدون إنترنت
    print('--- Test 6: remembered session reload OFFLINE ---')
    # أعد الدخول بنجاح أولًا ليُسجل nr_last_user
    fill_input(tpage, '#login-email', username)
    fill_input(tpage, '#login-pass', password)
    tpage.evaluate("tenantSecureLogin()")
    tpage.wait_for_timeout(6000)
    hidden = tpage.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    print('  re-login before reload: hidden=', hidden)
    assert hidden, 're-login must succeed offline'
    tpage.evaluate("location.reload()")
    tpage.wait_for_timeout(8000)
    hidden = tpage.evaluate("""document.getElementById('login-overlay').classList.contains('hidden')""")
    app_ready = tpage.evaluate("""document.getElementById('app') ? document.getElementById('app').style.display !== 'none' : 'no-app'""")
    print('  after reload: overlay hidden=', hidden, 'app_ready=', app_ready)
    assert hidden, 'remembered session must auto-enter offline'

    browser.close()
    print('=== جميع اختبارات الدخول المحلي بدون إنترنت ناجحة ===')
