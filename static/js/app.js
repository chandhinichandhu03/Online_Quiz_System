// ── Global JS ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {

  // Auto-dismiss flash messages
  document.querySelectorAll('.alert').forEach(function (alert) {
    setTimeout(function () {
      alert.style.transition = 'opacity 0.5s, transform 0.5s';
      alert.style.opacity = '0';
      alert.style.transform = 'translateY(-8px)';
      setTimeout(function () { alert.remove(); }, 500);
    }, 4000);

    const closeBtn = alert.querySelector('.alert-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        alert.style.opacity = '0';
        setTimeout(function () { alert.remove(); }, 300);
      });
    }
  });

  // Mobile nav toggle
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.navbar-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      nav.classList.toggle('open');
    });
    document.addEventListener('click', function (e) {
      if (!toggle.contains(e.target) && !nav.contains(e.target)) {
        nav.classList.remove('open');
      }
    });
  }

  // Option selection highlight
  document.querySelectorAll('.option-label').forEach(function (label) {
    label.addEventListener('click', function () {
      const name = this.querySelector('input[type="radio"]').name;
      document.querySelectorAll(`input[name="${name}"]`).forEach(function (r) {
        r.closest('.option-label').classList.remove('selected');
      });
      this.classList.add('selected');
    });
  });

  // Keyboard shortcut for options (1-4)
  document.addEventListener('keydown', function (e) {
    const key = e.key;
    if (['1', '2', '3', '4'].includes(key)) {
      const options = document.querySelectorAll('.option-label');
      const idx = parseInt(key) - 1;
      if (options[idx]) options[idx].click();
    }
  });

  // Score ring animation
  const fill = document.querySelector('.score-ring .fill');
  if (fill) {
    const pct = parseFloat(fill.dataset.score || 0);
    const r = parseFloat(fill.getAttribute('r'));
    const circ = 2 * Math.PI * r;
    fill.style.strokeDasharray = circ;
    fill.style.strokeDashoffset = circ;
    setTimeout(function () {
      fill.style.strokeDashoffset = circ - (circ * pct / 100);
    }, 200);
  }

  // Confirm delete
  document.querySelectorAll('.confirm-delete').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      if (!confirm('Are you sure you want to delete this? This action cannot be undone.')) {
        e.preventDefault();
      }
    });
  });

  // Progress tracking for quiz
  const form = document.getElementById('quiz-form');
  if (form) {
    const totalQ = parseInt(form.dataset.total || 0);
    function updateProgress() {
      const answered = new Set();
      form.querySelectorAll('input[type="radio"]:checked').forEach(function (r) {
        answered.add(r.name);
      });
      const pct = totalQ > 0 ? (answered.size / totalQ * 100) : 0;
      const bar = document.querySelector('.quiz-progress-fill');
      if (bar) bar.style.width = pct + '%';
      const counter = document.getElementById('answered-count');
      if (counter) counter.textContent = answered.size;
    }
    form.addEventListener('change', updateProgress);
    updateProgress();
  }

  // ── Frontend Question Validation ──────────────────────
  validateQuizQuestions();

});

// Validates quiz questions on page load and hides malformed ones
function validateQuizQuestions() {
  const BANNED = new Set([
    'correct', 'wrong', 'incorrect', 'true', 'false',
    'none of the above', 'all of the above', 'n/a', 'na',
    'not applicable', 'answer', 'right',
    'option a', 'option b', 'option c', 'option d'
  ]);

  const cards = document.querySelectorAll('.question-card[data-opt-1]');
  let invalidCount = 0;

  cards.forEach(function(card) {
    const opts = [
      (card.dataset.opt1 || '').trim(),
      (card.dataset.opt2 || '').trim(),
      (card.dataset.opt3 || '').trim(),
      (card.dataset.opt4 || '').trim()
    ];
    const correct = (card.dataset.correct || '').trim();
    const issues = [];

    // Check for empty options
    opts.forEach(function(opt, i) {
      if (!opt) issues.push('Option ' + (i+1) + ' is empty');
    });

    // Check for duplicates
    const lowerOpts = opts.map(function(o) { return o.toLowerCase(); });
    if (new Set(lowerOpts).size !== lowerOpts.length) {
      issues.push('Duplicate options detected');
    }

    // Check for banned placeholders
    opts.forEach(function(opt) {
      if (BANNED.has(opt.toLowerCase())) {
        issues.push('Banned option: ' + opt);
      }
    });

    // Check correct answer is in options
    if (correct && opts.indexOf(correct) === -1) {
      issues.push('Correct answer not in options');
    }

    if (issues.length > 0) {
      invalidCount++;
      card.style.opacity = '0.4';
      card.style.pointerEvents = 'none';
      const badge = document.createElement('div');
      badge.style.cssText = 'background:rgba(255,71,87,0.15);color:#ff4757;padding:8px 14px;border-radius:8px;font-size:0.8rem;margin-bottom:8px;font-weight:600;';
      badge.textContent = '⚠️ This question has formatting issues and has been disabled: ' + issues.join(', ');
      card.insertBefore(badge, card.firstChild);
    }
  });

  if (invalidCount > 0) {
    console.warn('[Quiz Validation] ' + invalidCount + ' question(s) failed frontend validation.');
  }
}

// ── Quiz Timer ──────────────────────────────────────────
function startQuizTimer(seconds, inputId) {
  const display = document.getElementById('timer-display');
  const widget  = document.querySelector('.timer-widget');
  const input   = document.getElementById(inputId);
  let elapsed   = 0;
  let remaining = seconds;

  function tick() {
    if (remaining <= 0) {
      display.textContent = '00:00';
      document.getElementById('quiz-form').submit();
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    display.textContent = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    if (input) input.value = elapsed;
    if (remaining <= 30 && widget) widget.classList.add('urgent');
    remaining--;
    elapsed++;
    setTimeout(tick, 1000);
  }
  tick();
}
