/* NOP Intelligence - small helpers (no libraries).
   1. Forms: a form with data-confirm asks first ("Delete this chat ...?"); a submit button shows a
      spinner and locks, so nobody clicks twice (buttons with data-no-spin are left alone). */
(function () {
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var question = form.getAttribute('data-confirm');
      if (question && !window.confirm(question)) { e.preventDefault(); return; }
      var btn = form.querySelector('button[type=submit].btn');
      if (!btn || btn.disabled || btn.hasAttribute('data-no-spin')) { return; }
      if (!btn.querySelector('.spin')) {
        var s = document.createElement('span');
        s.className = 'spin';
        btn.insertBefore(s, btn.firstChild);
      }
      btn.classList.add('loading');
    });
  });
})();

/* 2. Ask NOP chat list: the "..." of a chat opens its menu (Rename / Remove from list / Delete);
      only one menu is open at a time, Escape or a click elsewhere closes it. On a phone the list is a
      drawer: "Chats" opens it, the cross / the dark backdrop / Escape closes it. */
(function () {
  var toggles = document.querySelectorAll('[data-menu-toggle]');
  function closeMenus(except) {
    toggles.forEach(function (t) {
      if (t === except) { return; }
      t.setAttribute('aria-expanded', 'false');
      var menu = t.closest('.chat-row').querySelector('.chat-menu');
      if (menu) { menu.hidden = true; }
    });
  }
  toggles.forEach(function (t) {
    t.addEventListener('click', function (e) {
      e.stopPropagation();
      var menu = t.closest('.chat-row').querySelector('.chat-menu');
      var open = menu.hidden;
      closeMenus(t);
      menu.hidden = !open;
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) { var title = menu.querySelector('input[name=title]'); if (title) { title.focus(); title.select(); } }
    });
  });
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.chat-menu')) { closeMenus(null); }
  });

  var list = document.getElementById('chats');
  var backdrop = document.querySelector('.chats-backdrop');
  function drawer(open) {
    if (!list) { return; }
    list.classList.toggle('open', open);
    if (backdrop) { backdrop.hidden = !open; }
    document.querySelectorAll('[data-chats-toggle]').forEach(function (b) {
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  document.querySelectorAll('[data-chats-toggle]').forEach(function (b) {
    b.addEventListener('click', function () { drawer(true); });
  });
  document.querySelectorAll('[data-chats-close]').forEach(function (b) {
    b.addEventListener('click', function () { drawer(false); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeMenus(null); drawer(false); }
  });
})();

/* 0. "Thinking..." can take up to a minute when the AI service makes us wait (its per-minute limit):
      after 20 s and 60 s the text says so, and that the answer is saved anyway. And when the browser
      shows an Ask page again from its back/forward memory (e.g. Back after visiting History while a
      question was running), that old snapshot may still say "Thinking..." - so reload it instead:
      the server then shows the saved answer. */
function slowNotes(el) {
  if (!el) { return; }
  var dots = '<span class="dots"><i></i><i></i><i></i></span> ';
  setTimeout(function () {
    el.innerHTML = dots + 'Still working… the AI service is busy, so this can take up to a minute.';
  }, 20000);
  setTimeout(function () {
    el.innerHTML = dots + 'Still working… the answer is saved as soon as it is ready - you can also find it in ' +
      '<a href="/history/">History</a>.';
  }, 60000);
}
window.addEventListener('pageshow', function (e) {
  if (e.persisted && document.body.classList.contains('page-ask')) { window.location.reload(); }
});

/* 3. The question box (like ChatGPT): it grows with the text, Enter sends, Shift+Enter makes a new
      line. After sending, the question appears as a bubble with a "Thinking..." animation and the
      box is locked until the answer page comes back (the request itself is a normal form post). */
(function () {
  var form = document.getElementById('composer');
  if (!form) { return; }
  var box = form.querySelector('textarea');
  var send = form.querySelector('button[type=submit]');
  function grow() {
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight, 220) + 'px';
  }
  box.addEventListener('input', grow);
  grow();
  box.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (box.value.trim() && !send.disabled) {
        if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
      }
    }
  });
  form.addEventListener('submit', function (e) {
    if (!box.value.trim()) { e.preventDefault(); box.focus(); return; }
    var thread = document.getElementById('thread');
    if (thread) {
      var welcome = document.getElementById('welcome');
      if (welcome) { welcome.hidden = true; }
      var item = document.createElement('div');
      item.className = 'chat-item pending';
      var q = document.createElement('div');
      q.className = 'chat-q';
      var bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = box.value.trim();
      q.appendChild(bubble);
      var thinking = document.createElement('div');
      thinking.className = 'thinking';
      thinking.setAttribute('role', 'status');
      thinking.innerHTML = '<span class="dots"><i></i><i></i><i></i></span> Thinking… writing the SQL and checking it';
      item.appendChild(q);
      item.appendChild(thinking);
      thread.appendChild(item);
      var panel = document.getElementById('conv-scroll');
      if (panel && panel.scrollHeight > panel.clientHeight + 1) {
        panel.scrollTo({top: panel.scrollHeight, behavior: 'smooth'});
      } else {
        item.scrollIntoView({block: 'end', behavior: 'smooth'});
      }
    }
    box.readOnly = true;          /* readOnly, not disabled: a disabled box would not be sent */
    send.disabled = true;
    send.classList.add('loading');
    slowNotes(document.querySelector('.chat-item.pending .thinking'));
  });
  if (/[?&]q=/.test(window.location.search)) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
})();

/* 4. Open a chat at its newest answer (or at the #q-<id> answer of the address). On a desktop only the
      conversation panel scrolls, so that panel is moved - never the page or the chat list. */
(function () {
  var target = null;
  if (/^#q-\d+$/.test(window.location.hash)) { target = document.getElementById(window.location.hash.slice(1)); }
  if (!target) { target = document.querySelector('[data-chat-newest]'); }
  if (!target) { return; }
  var panel = document.getElementById('conv-scroll');
  var main = document.querySelector('.main');
  function place() {
    if (panel && panel.scrollHeight > panel.clientHeight + 1) {
      panel.scrollTop = Math.max(0, target.offsetTop - 14);
      if (main) { main.scrollTop = 0; }        /* the page itself never moves on a desktop */
    } else if (!window.location.hash) {
      target.scrollIntoView({block: 'start'}); /* phone: the page scrolls as usual */
    }
  }
  place();
  window.addEventListener('load', place);      /* again once fonts and the rows table have their size */
})();

/* 6. Edit an old question (pencil on its bubble, like ChatGPT): the bubble becomes a box with the text;
      Enter (or "Save & ask") asks the edited question - its answer takes this one's place; Cancel or
      Escape puts the bubble back. Only one question is edited at a time. */
(function () {
  function close(wrap) {
    var form = wrap.querySelector('.q-edit-form');
    if (!form || form.classList.contains('sending')) { return; }
    form.hidden = true;
    wrap.classList.remove('editing');
  }
  document.querySelectorAll('[data-edit-wrap]').forEach(function (wrap) {
    var form = wrap.querySelector('.q-edit-form');
    var box = form.querySelector('textarea');
    wrap.querySelector('[data-edit-toggle]').addEventListener('click', function () {
      document.querySelectorAll('[data-edit-wrap].editing').forEach(function (w) { if (w !== wrap) { close(w); } });
      wrap.classList.add('editing');
      form.hidden = false;
      box.style.height = 'auto';
      box.style.height = Math.min(box.scrollHeight + 2, 220) + 'px';
      box.focus();
      box.setSelectionRange(box.value.length, box.value.length);
    });
    form.querySelector('[data-edit-cancel]').addEventListener('click', function () { close(wrap); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); close(wrap); return; }
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (box.value.trim()) { if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); } }
      }
    });
    box.addEventListener('input', function () {
      box.style.height = 'auto';
      box.style.height = Math.min(box.scrollHeight + 2, 220) + 'px';
    });
    form.addEventListener('submit', function (e) {
      if (!box.value.trim()) { e.preventDefault(); box.focus(); return; }
      form.classList.add('sending');
      box.readOnly = true;
      form.querySelectorAll('button').forEach(function (b) { if (b.type !== 'submit') { b.disabled = true; } });
      var thinking = document.createElement('div');
      thinking.className = 'thinking';
      thinking.setAttribute('role', 'status');
      thinking.innerHTML = '<span class="dots"><i></i><i></i><i></i></span> Thinking… asking the edited question';
      wrap.parentNode.insertBefore(thinking, wrap.nextSibling);
      slowNotes(thinking);
    });
  });
})();

/* 5. One-time token notice under a just-answered question: fades away after 20 seconds. */
(function () {
  document.querySelectorAll('[data-fade-after]').forEach(function (el) {
    var ms = parseInt(el.getAttribute('data-fade-after'), 10) || 20000;
    setTimeout(function () {
      el.classList.add('fading');
      setTimeout(function () { el.hidden = true; }, 900);
    }, ms);
  });
})();
