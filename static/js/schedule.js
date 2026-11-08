(() => {
  'use strict';
  document.getElementById('branch-sel')?.addEventListener('change', () => document.getElementById('branch-form').requestSubmit());
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab, focus = false) {
    tabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
    });
    if (focus) tab.focus();
  }
  if (tabs.length) {
    selectTab(tabs[0]);
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => selectTab(tab));
      tab.addEventListener('keydown', event => {
        let target;
        if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
        if (event.key === 'Home') target = tabs[0];
        if (event.key === 'End') target = tabs[tabs.length - 1];
        if (target) { event.preventDefault(); selectTab(target, true); }
      });
    });
    document.querySelectorAll('[data-show-full]').forEach(button => button.addEventListener('click', () => selectTab(tabs[1], true)));
  }
  const menu = document.querySelector('.account-menu');
  document.addEventListener('click', event => { if (menu && !menu.contains(event.target)) menu.open = false; });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  const dialog = document.getElementById('schedule-calendar');
  const trigger = document.getElementById('cal-btn');
  const input = document.getElementById('cal-input');
  const days = document.getElementById('calendar-days');
  const data = JSON.parse(document.getElementById('calendar-data').textContent) || [];
  const published = new Map(data.map(day => [day.iso, day]));
  const iso = date => [String(date.getFullYear()).padStart(4, '0'), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  const parse = value => { const [y, m, d] = value.split('-').map(Number); const date = new Date(2000, m - 1, d, 12); date.setFullYear(y); return date; };
  let month = parse(input.value);
  month.setDate(1);
  function renderMonth(focusIso) {
    document.getElementById('calendar-month').textContent = month.toLocaleDateString('ru-RU', {month: 'long', year: 'numeric'});
    days.replaceChildren();
    const offset = (month.getDay() + 6) % 7;
    const last = new Date(month); last.setMonth(last.getMonth() + 1); last.setDate(0);
    for (let i = 0; i < offset; i++) days.append(document.createElement('span'));
    for (let day = 1; day <= last.getDate(); day++) {
      const date = new Date(month); date.setDate(day);
      const value = iso(date), entry = published.get(value);
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = String(day); button.dataset.date = value;
      button.className = 'calendar-day' + (entry ? ' published' : '') + (entry?.is_new ? ' is-new' : '');
      button.setAttribute('aria-label', date.toLocaleDateString('ru-RU', {day: 'numeric', month: 'long', year: 'numeric'}) + (entry ? ', есть расписание' : '') + (entry?.is_new ? ', новое' : ''));
      button.setAttribute('aria-pressed', String(value === input.value));
      button.addEventListener('click', () => { input.value = value; document.getElementById('date-form').requestSubmit(); });
      button.addEventListener('keydown', event => {
        const shifts = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
        if (!(event.key in shifts)) return;
        event.preventDefault(); date.setDate(date.getDate() + shifts[event.key]);
        if (date.getFullYear() < 1 || date.getFullYear() > 9999) return;
        month = new Date(date); month.setDate(1); renderMonth(iso(date));
      });
      days.append(button);
    }
    if (focusIso) Array.from(days.children).find(button => button.dataset.date === focusIso)?.focus();
  }
  trigger.addEventListener('click', () => {
    month = parse(input.value); month.setDate(1); renderMonth();
    dialog.showModal(); trigger.setAttribute('aria-expanded', 'true');
  });
  document.getElementById('calendar-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { trigger.setAttribute('aria-expanded', 'false'); trigger.focus(); });
  dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
  document.getElementById('month-prev').addEventListener('click', () => { if (month.getFullYear() > 1 || month.getMonth() > 0) { month.setMonth(month.getMonth() - 1); renderMonth(); } });
  document.getElementById('month-next').addEventListener('click', () => { if (month.getFullYear() < 9999 || month.getMonth() < 11) { month.setMonth(month.getMonth() + 1); renderMonth(); } });
  input.addEventListener('change', () => { if (input.value && input.validity.valid) { month = parse(input.value); month.setDate(1); renderMonth(); } });
  document.getElementById('news-dismiss')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    const url = new URL(window.location.href);
    url.searchParams.set('ack_news', button.dataset.newsIds);
    try {
      const response = await fetch(url, {credentials: 'same-origin'});
      if (!response.ok || response.redirected) throw new Error('Unable to acknowledge');
      // Refresh calendar markers from the same server-side read state.
      window.location.reload();
    } catch (_) {
      document.getElementById('news-error').hidden = false;
      button.disabled = false;
    }
  });
})();
